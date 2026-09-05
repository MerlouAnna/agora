from dotenv import load_dotenv
from fastapi import FastAPI

# The AI workflow needs OPENAI_API_KEY, so the environment is read at import time, before
# any client is constructed. The catalogue service needs no configuration of its own.
load_dotenv()

app = FastAPI(title="Agora — Offer Service")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "offer_service"}
