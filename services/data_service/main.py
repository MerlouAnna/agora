from fastapi import FastAPI

from services.data_service import models
from services.data_service.database import engine
from services.data_service.routers import admin, products, sql, stats

app = FastAPI(title="Agora — Catalogue Service")

models.TableBase.metadata.create_all(bind=engine)

app.include_router(products.router, prefix="/products", tags=["Products"])
app.include_router(stats.router, prefix="/stats", tags=["Statistics"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(sql.router, prefix="/sql", tags=["SQL console"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "data_service"}
