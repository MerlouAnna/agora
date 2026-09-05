# Agora — Agentic Sales Support System

An AI assistant for salespeople in a reseller business. The salesperson describes a
customer need in plain language and gets back five validated offer scenarios, built from
real catalogue, stock and pricing data.

> Final project for the **AI for Developers** course, Athens University of Economics and
> Business (Centre for Training and Lifelong Learning).

**Status: under development.** See `PROJECT_PLAN.md` for what is done and what is next.

---

## 1. What it does

A request like

> "I need cable for 1000 WATT, 20 meters, around €100 budget."

goes through: requirement extraction → catalogue search → scenario generation →
validation against the database → a written recommendation. Prices, stock and totals
always come from the data, never from the language model.

## 2. Installation

```bash
git clone <repository-url>
cd agora

python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate      # macOS / Linux

pip install -r requirements.txt

copy .env.example .env         # Windows  (cp on macOS / Linux)
```

Then open `.env` and add your OpenAI key.

## 3. Run the backend

Agora is two FastAPI services. Start each one from the **repository root**, in its own
terminal:

```bash
uvicorn services.data_service.main:app  --reload --port 8001   # the catalogue
uvicorn services.offer_service.main:app --reload --port 8000   # the AI workflow
```

Swagger UI: http://localhost:8001/docs and http://localhost:8000/docs.
Both services answer `GET /health`.

## 4. Run the UI

_TODO_

## 5. API endpoints

_TODO_

## 6. GenAI logic

_TODO — prompt engineering, system prompts, RAG, agents, tool calling, structured outputs._

## 7. Documentation

_TODO — link to the full documentation._
