from fastapi import FastAPI

from services.offer_service.routers import assistant, auth, offers

app = FastAPI(title="Agora — Offer Service")

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(offers.router, prefix="/offers", tags=["Offers"])
app.include_router(assistant.router, prefix="/assistant", tags=["Assistant"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "offer_service"}
