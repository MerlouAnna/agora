"""
Assistant graph
===============
The question loop: the model either asks for a tool or answers, and an answer is held
against what the tools returned before it is let through. Two nodes, one fork, and a cap
on how long the model may keep asking.
"""

import json
import logging
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from services.offer_service.assistant import grounding, model, tools
from services.offer_service.prompts.assistant import SYSTEM

logger = logging.getLogger(__name__)

MAX_ROUNDS = 5
MAX_REPAIRS = 1


class AssistantFailed(RuntimeError):
    """The model kept asking for tools and never answered."""


class AssistantState(TypedDict):
    """One question on its way to an answer.

    `messages` is the conversation as the model sees it and grows by whatever each node
    adds. `evidence` is every tool result of this turn, which is all an answer may rest on.
    """

    question: str
    earlier: list[str]
    messages: Annotated[list[dict], operator.add]
    tools_used: Annotated[list[dict], operator.add]
    evidence: Annotated[list[str], operator.add]
    rounds: int
    repairs: int
    answer: str | None
    refused: str | None


def make_initial_state(question: str, history: list[dict]) -> AssistantState:
    """A fresh state: the instructions, the earlier turns as plain words, and the question."""
    return {
        "question": question,
        "earlier": [turn["content"] for turn in history if turn.get("content")],
        "messages": [
            {"role": "system", "content": SYSTEM},
            *history,
            {"role": "user", "content": question},
        ],
        "tools_used": [],
        "evidence": [],
        "rounds": 0,
        "repairs": 0,
        "answer": None,
        "refused": None,
    }


def ask_model(state: AssistantState) -> dict:
    """One round with the model, and the check on what it wrote when it wrote something."""
    rounds = state["rounds"] + 1
    reply = model.complete(state["messages"])

    if reply.get("tool_calls"):
        if rounds >= MAX_ROUNDS:
            raise AssistantFailed(f"the model asked for tools {rounds} times and never answered")
        return {"messages": [reply], "rounds": rounds}

    answer = (reply.get("content") or "").strip()
    strange = grounding.unsupported(answer, state["evidence"], state["question"], state["earlier"])
    if not strange:
        return {"messages": [reply], "rounds": rounds, "answer": answer}

    if state["repairs"] < MAX_REPAIRS:
        fix = (
            f"{', '.join(strange)} appears in no tool result of this turn. Write only codes "
            "and figures a tool returned, call a tool to get them, or say you do not have them"
        )
        logger.info("round %d sent back — %s", rounds, fix)
        return {
            "messages": [reply, {"role": "user", "content": json.dumps({"fix": fix})}],
            "rounds": rounds,
            "repairs": state["repairs"] + 1,
        }

    logger.info("the answer is refused — %s could not be supported", ", ".join(strange))
    return {"messages": [reply], "rounds": rounds, "refused": _refusal(strange)}


def run_tools(state: AssistantState) -> dict:
    """Every tool the last reply asked for, in turn, its result fed back as it came."""
    subjects = tuple(grounding.SKU.findall(" ".join([state["question"], *state["earlier"]])))
    replies, used, evidence = [], [], []
    for call in state["messages"][-1]["tool_calls"]:
        name = call["function"]["name"]
        arguments = _arguments(call["function"]["arguments"])
        result = (
            tools.run(name, arguments, subjects)
            if arguments is not None
            else {"error": "the arguments were not a JSON object"}
        )
        written = json.dumps(result, ensure_ascii=False)
        logger.info("tool %s(%s)", name, arguments)

        replies.append({"role": "tool", "tool_call_id": call["id"], "content": written})
        used.append({"name": name, "arguments": arguments})
        evidence.append(written)

    return {"messages": replies, "tools_used": used, "evidence": evidence}


def route_after_model(state: AssistantState) -> str:
    """The one fork: run what was asked for, answer again after a repair, or stop."""
    if state["answer"] is not None or state["refused"] is not None:
        return "end"

    return "tools" if state["messages"][-1].get("tool_calls") else "again"


def build_graph():
    """Compile the loop.

    START → ask_model, and from there to run_tools, back to ask_model after a repair, or
    END. run_tools always returns to ask_model.

    Returns:
        The compiled graph, ready to `invoke()` a state from `make_initial_state`.
    """
    graph = StateGraph(AssistantState)

    graph.add_node("ask_model", ask_model)
    graph.add_node("run_tools", run_tools)

    graph.add_edge(START, "ask_model")
    graph.add_conditional_edges(
        "ask_model",
        route_after_model,
        {"tools": "run_tools", "again": "ask_model", "end": END},
    )
    graph.add_edge("run_tools", "ask_model")

    logger.info("the assistant graph is compiled — two nodes, one fork")
    return graph.compile()


def _arguments(written: str) -> dict | None:
    try:
        parsed = json.loads(written or "{}")
    except ValueError:
        return None

    return parsed if isinstance(parsed, dict) else None


def _refusal(strange: list[str]) -> str:
    return (
        "Δεν μπορώ να τεκμηριώσω αυτή την απάντηση από τον κατάλογο και τα έγγραφα: "
        f"«{', '.join(strange)}» δεν προέκυψε από κανένα εργαλείο. Ρώτησε πιο συγκεκριμένα, "
        "με τον κωδικό του προϊόντος αν τον ξέρεις."
    )
