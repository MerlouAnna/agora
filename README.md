# Agora — Agentic Sales Support System

An AI assistant for salespeople in a reseller business. The salesperson describes a
customer need in plain language and gets back five validated offer scenarios, built from
real catalogue, stock and pricing data — and asks, on the same screen, the questions that
come up around an offer.

> Final project for the **AI for Developers** course, Athens University of Economics and
> Business (Centre for Training and Lifelong Learning).

---

## 1. What it does

A request like

> "I need cable for 1000 WATT, 20 meters, around EUR 100 budget."

goes through: requirement extraction -> catalogue search -> scenario generation ->
validation against the database -> a written recommendation. Prices, stock and totals
always come from the data, never from the language model.

The salesperson stays the decision maker. Every offer is shown side by side with the one
the system recommends, together with the scenarios it refused to offer and the reason for
each, so the choice of what reaches the customer is made by a person.

Next to the offers there is an assistant for the questions that surround them — what is in
stock, what a category holds under a price, how long the warranty runs on a UPS, when an
order still ships the same day. There the model decides for itself which tools to call and
how many times, and every product code and every figure it writes is checked against what
those tools returned before the answer reaches the screen. Each salesperson's questions
are kept as a conversation, so a follow-up can be asked in three words.

## 2. Installation

Agora needs **Python 3.14** and [Poetry](https://python-poetry.org/) for dependency
management.

```bash
git clone <repository-url>
cd agora

poetry install
```

Poetry creates the virtual environment and installs everything from `pyproject.toml`,
locked by `poetry.lock`. If Poetry is not on your machine:

```bash
pipx install poetry        # or: pip install --user poetry
```

Then copy the environment template:

```bash
copy .env.example .env     # Windows  (cp on macOS / Linux)
```

Two values in it are needed: `OPENAI_API_KEY`, and `JWT_SECRET_KEY` for signing the login
tokens. Any long random string will do for the second:

```bash
poetry run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Without a secret the services refuse to issue or accept a token and say so, rather than
falling back to a default that would be the same on every clone.

The catalogue database is committed to the repository, already populated with 226
products, four warehouses and their suppliers, so there is nothing to import first. It
carries no users: two demo accounts are written into it the first time the catalogue
service starts against an empty user table, so a fresh clone has someone to log in as —
**pmoschos** / `ai-for-devs-moschos` and **amerlou** / `ai-for-devs-merlou`.

## 3. Run the backend

Agora is two FastAPI services. Start each one from the **repository root**, in its own
terminal:

```bash
poetry run uvicorn services.data_service.main:app  --reload --port 8001   # the catalogue
poetry run uvicorn services.offer_service.main:app --reload --port 8000   # the AI workflow
```

Swagger UI: http://localhost:8001/docs and http://localhost:8000/docs.
Both services answer `GET /health`.

### Build the search index

The vector store is not committed, so build it once with the catalogue service running:

```bash
poetry run python -m services.offer_service.rag.indexer
```

This reads the products from the catalogue service and the ten business documents in
`data/docs/`, and writes both collections into `data/chroma/`. The vectors themselves
**are** committed, in `data/raw/`, and the indexer asks OpenAI only for texts whose
content has changed — so on a fresh clone with untouched data it builds the index without
spending anything.

## 4. Run the UI

With both services up and the index built:

```bash
poetry run python ui/gradio_app.py
```

Gradio serves the screen on http://localhost:7860. It talks to the offer service over
HTTP and to nothing else; set `OFFER_SERVICE_URL` if that service is not on
`http://localhost:8000`.

The screen asks for a username and password first — one of the demo accounts above — and
then opens on two tabs.

**Προσφορές** is the offer desk: the request, the offers side by side, and an expandable
section showing what the request was understood to mean, which products the search
reached, and what the validator said about every scenario built, including the ones it
withheld.

**Ερωτήσεις** is the assistant: a chat, one thread per conversation, with that user's
earlier threads in a dropdown beside it. Under every answer is the line of tools it was
built from, so what the answer rests on is visible without opening anything.

The same flow runs on the command line, printing each step as it goes:

```bash
poetry run python -m tools.run_offer "Ten 80+ Gold ATX power supplies, at least 750W."
```

## 5. API endpoints

**Catalogue service** — `http://localhost:8001`

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Service check |
| POST | `/auth/login` | Log in and receive a bearer token |
| GET | `/products/search` | Search the catalogue |
| POST | `/products/lookup` | Read several products at once |
| GET | `/products/{sku}/stock` | Where a product is held, and how much of it |
| GET | `/suppliers` | The supplier registry |
| GET | `/stats` | What is in the catalogue right now |
| POST | `/admin/generate` | Add products to the catalogue |
| GET | `/admin/runs` | Previous generation runs |
| DELETE | `/admin/runs/{request_id}` | Take a generation run back out |
| POST | `/admin/rebuild` | Rebuild the catalogue from the source files |
| GET | `/admin/usage` | What the models have cost so far |
| GET | `/admin/import/template` | Download the import template |
| POST | `/admin/import` | Import a filled-in CSV |
| GET | `/sql/schema` | What there is to query |
| POST | `/sql/query` | Run one SELECT against the catalogue |
| POST | `/conversations` | Open a conversation for a user |
| GET | `/conversations` | A user's conversations, newest first |
| GET | `/conversations/{id}` | One conversation with every turn in it |
| POST | `/conversations/{id}/messages` | Append a turn to a conversation |

The conversation routes are internal. The offer service calls them with the username it
read out of the token; nothing on this port is reached from the browser, and a thread that
belongs to somebody else answers 404 rather than 403.

**Offer service** — `http://localhost:8000`

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Service check |
| POST | `/auth/login` | Log in, forwarded to the catalogue service |
| POST | `/offers/generate` | Turn a request into offers and a recommendation |
| POST | `/assistant/ask` | Ask a question, answered from tool results |
| GET | `/assistant/conversations` | The logged-in user's conversations |
| GET | `/assistant/conversations/{id}` | One conversation with every turn in it |

Everything under `/offers` and `/assistant` needs `Authorization: Bearer …`. The token
comes from `/auth/login`, which exists on both services so that the screen and Swagger talk
to one origin. The catalogue service owns the users and issues the token; the offer service
forwards the login form as it is, hands the token back unchanged, and from then on verifies
it with the shared secret alone, without asking the catalogue service again.

`POST /offers/generate` takes the request, the branch it is raised from and whether the
order is confirmed before the 13:00 cut-off. It answers with the requirements the request
was read as, the offers that passed validation, the recommendation and the words to send
it with, every scenario that was built together with its verdict, and a trace of what each
step of the graph did. A request the catalogue cannot answer comes back as a 200 with a
reason, not as an error: there being nothing to sell is an answer.

`POST /assistant/ask` takes the question and, when the conversation is already open, its
id. It answers with the text, the tool calls behind it, how many rounds it took, and
whether it is a refusal — which is also a 200, and is also written into the thread, because
a refusal is an answer too. A model that never stopped calling tools is a 502 and leaves
nothing behind, because that is a failure.

## 6. GenAI logic

**Structured outputs.** The request is read into a Pydantic model through the OpenAI
structured-output API, so the category, quantity, technical constraints and budgets arrive
as typed fields instead of prose to be parsed. What the schema refuses goes back to the
model with the reason it was refused, three rounds at most, and then the request is
declined rather than guessed at.

**Prompt engineering.** The prompts are modules under `services/offer_service/prompts/`.
The extraction prompt is generated from the label registry rather than written beside it,
so a new category or a new unit cannot leave the prompt behind. Every rule in every prompt
was kept or dropped on a measurement over a fixed set of requests at `temperature=0`, run
three times — including several that were written, measured, and taken back out because
they made the answers worse.

**System prompts.** Each call carries a role, a task, and a numbered rule list that names
what the answer may contain and, above all, what it may not: the recommendation is told
that every figure it writes must already appear in the offers it was handed, and the
assistant that it knows nothing about this catalogue or these terms beyond what a tool
returned in this very turn.

**RAG.** Two Chroma collections — 226 product cards and 66 passages cut from the ten
business documents in `data/docs/`, one passage per section. Product search is hybrid: the
vector query proposes candidates and hard SQL constraints from the request cut them down,
so a semantically close product cannot survive a requirement it does not meet. The policy
sections that travel with a recommendation are chosen from what the offers carry rather
than from the customer's words, because a request rarely mentions the terms its answer has
to explain. A datasheet section belongs to one product, so when the assistant searches the
documents it is handed back only for a product the conversation is actually about. Prices
are deliberately not indexed — they change, and an index is a photograph.

**Agents.** Both paths are LangGraph state machines, and they are different machines on
purpose. The offer path is a fixed workflow: six nodes — extract, retrieve, build the
scenarios, validate, recommend, and the sixth for when validation leaves nothing that may
be offered — with one conditional edge between the last two. The assistant is a loop of
two: ask the model, run what it asked for, back to the model, five rounds at most. Each
node reads the state and returns only the keys it changed.

**Grounding as a loop, not a score.** Nothing written by the model is shown before it is
checked. A recommendation naming a product code or a figure that is not in the offers it
was handed goes back with the reason, three rounds, then nothing. An assistant answer is
read against the tool results of that turn: a product code may also come from an earlier
turn, since that is the subject being talked about, but a figure may not — a price said
once is written again only after a tool has returned it again. One repair, and then a
refusal that names what could not be supported. Whether an answer is *good* is not scored
— that is a judgement, and a number for it would be the model marking its own work.

**Tool calling.** Which side holds the tools is decided by what is at stake. On the offer
path the graph fetches: it calls the catalogue service and the vector store itself, at
fixed points, with arguments the previous step computed. Every figure that reaches a
customer is therefore fetched by code whose behaviour is tested, and the model is left the
two jobs it is actually good at — reading a sentence, and writing one. On the question path
the model fetches: it is given three tools with their schemas — a product's stock, a search
of one category under a price and above a stock floor, and a search of the business
documents — and it decides which to call, with what arguments, and how many times. Nothing
it asks for changes anything; every tool returns a row of the catalogue or a section of a
document, as it is.

## 7. Documentation

The full documentation — purpose and use case, architecture and data flow, the technology
choices and the argument for each, the GenAI techniques, how the system was measured, its
limits and what comes next — is in [`docs/agora.pdf`](docs/agora.pdf).

Worked examples of complete requests and the answers they produced are in
[`examples/`](examples/).

## 8. Tests

```bash
poetry run pytest          # the whole suite
poetry run ruff check .    # linting
```

The suite runs offline: every model call is answered by a fixture, so it needs no key and
costs nothing. What the model actually does is measured separately, by the scripts in
`tools/` — extraction, retrieval, policy search, scenarios, the recommendation and the
assistant — each over a fixed set of cases whose expected answers were written by hand
before the first run.

```bash
poetry run python -m tools.measure_assistant
```
