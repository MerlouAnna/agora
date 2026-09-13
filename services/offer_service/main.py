from fastapi import FastAPI

from services.offer_service.routers import offers

app = FastAPI(title="Agora — Offer Service")

app.include_router(offers.router, prefix="/offers", tags=["Offers"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "offer_service"}
