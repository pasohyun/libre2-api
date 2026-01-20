# api/main.py
from fastapi import FastAPI
from api.routers import health, products
from api.database import init_db  # 테이블 자동 생성

app = FastAPI(
    title="Libre2 Price Monitoring API",
    version="1.0.0",
    description="프리스타일 리브레2 가격 모니터링 API"
)

# 애플리케이션 시작 시 데이터베이스 테이블 초기화
@app.on_event("startup")
async def startup_event():
    init_db()

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
