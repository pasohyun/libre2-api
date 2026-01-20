# api/main.py
from fastapi import FastAPI
from api.routers import health, products

app = FastAPI(
    title="Libre2 Price Monitoring API",
    version="1.0.0",
    description="프리스타일 리브레2 가격 모니터링 API"
)

@app.get("/")
def root():
    return {
        "message": "Libre2 Price Monitoring API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "products": "/products"
    }

app.include_router(health.router)
app.include_router(products.router)
