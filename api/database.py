# api/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

import config

# Railway 배포 시 환경 변수 필수
# 로컬 개발 시에는 환경 변수가 없으면 기본값 사용
IS_RAILWAY = os.getenv("RAILWAY_ENVIRONMENT") is not None or os.getenv("RAILWAY") is not None

if IS_RAILWAY:
    # Railway에서는 환경 변수 필수
    assert config.DB_HOST and config.DB_USER and config.DB_PASSWORD and config.DB_NAME, \
        "DB environment variables are required in Railway"
    DB_USER = config.DB_USER
    DB_PASSWORD = config.DB_PASSWORD
    DB_HOST = config.DB_HOST
    DB_PORT = config.DB_PORT or 3306
    DB_NAME = config.DB_NAME
else:
    # 로컬 개발: 환경 변수가 없으면 기본값 사용
    DB_USER = config.DB_USER or "daewoong_user"
    DB_PASSWORD = config.DB_PASSWORD or "Tnreodnd11!!"
    DB_HOST = config.DB_HOST or "localhost"
    DB_PORT = config.DB_PORT or 3306
    DB_NAME = config.DB_NAME or "daewoong"

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)

engine = create_engine(DATABASE_URL, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
