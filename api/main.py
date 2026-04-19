# api/main.py
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import scheduler
from api.auth_dashboard import require_dashboard_auth
from api.database import init_db  # 테이블 자동 생성
from api.routers import auth_dashboard, health, memos, products, reports


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(
    title="Libre2 Price Monitoring API",
    version="1.0.0",
    description="프리스타일 리브레2 가격 모니터링 API",
    lifespan=lifespan,
)

# CORS 설정 (Vercel 프론트엔드에서 호출 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # 로컬 개발
        "http://localhost:5173",  # Vite 로컬
        "http://127.0.0.1:5173",  # Vite 로컬(127.0.0.1은 localhost와 origin이 다름)
        "https://libre-price-monitor-client.vercel.app",  # Vercel Production 도메인 (기존)
        "https://libre-price-monitor-client-quz71ujve-libre2-monitoring.vercel.app",  # Vercel Pro팀 도메인
        "https://*.vercel.app",   # Vercel 모든 프리뷰 도메인
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post(
    "/crawl/trigger",
    tags=["crawl"],
    dependencies=[Depends(require_dashboard_auth)],
)
async def trigger_crawl(background_tasks: BackgroundTasks):
    """수동으로 쿠팡 크롤링 즉시 실행"""
    scheduler.run_now()
    return {"status": "started", "message": "크롤링이 백그라운드에서 시작되었습니다."}


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
app.include_router(auth_dashboard.router)
app.include_router(products.router, dependencies=[Depends(require_dashboard_auth)])
app.include_router(reports.router, dependencies=[Depends(require_dashboard_auth)])
app.include_router(memos.router, dependencies=[Depends(require_dashboard_auth)])