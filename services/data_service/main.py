from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.data_service import models, users
from services.data_service.database import SessionLocal, engine
from services.data_service.routers import admin, auth, products, sql, stats, suppliers

models.TableBase.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as db:
        users.seed_demo_users(db)
    yield


app = FastAPI(title="Agora — Catalogue Service", lifespan=lifespan)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(products.router, prefix="/products", tags=["Products"])
app.include_router(suppliers.router, prefix="/suppliers", tags=["Suppliers"])
app.include_router(stats.router, prefix="/stats", tags=["Statistics"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(sql.router, prefix="/sql", tags=["SQL console"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "data_service"}
