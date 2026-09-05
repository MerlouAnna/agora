from fastapi import FastAPI

app = FastAPI(title="Agora — Catalogue Service")

# Everything that touches the database lives behind this service. The product routers
# arrive in phase 3; until then /health is the whole API.


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "data_service"}
