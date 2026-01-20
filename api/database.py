# api/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

import config

# Railway 배포 시 환경 변수 필수
# 로컬 개발 시에는 환경 변수가 없으면 기본값 사용
IS_RAILWAY = (
    os.getenv("RAILWAY_ENVIRONMENT") is not None 
    or os.getenv("RAILWAY") is not None
    or os.getenv("PORT") is not None  # Railway는 PORT 환경 변수를 자동 설정
)

if IS_RAILWAY:
    # Railway MySQL 서비스의 환경 변수 사용 (자동 설정됨)
    # Railway가 MySQL 서비스를 추가하면 MYSQL* 환경 변수를 자동으로 설정합니다
    DB_HOST = os.getenv("MYSQLHOST") or config.DB_HOST
    DB_USER = os.getenv("MYSQLUSER") or config.DB_USER
    DB_PASSWORD = os.getenv("MYSQLPASSWORD") or config.DB_PASSWORD
    DB_NAME = os.getenv("MYSQLDATABASE") or config.DB_NAME
    DB_PORT = int(os.getenv("MYSQLPORT", config.DB_PORT or 3306))
    
    # Railway MySQL 환경 변수 또는 수동 설정된 환경 변수 확인
    if not (DB_HOST and DB_USER and DB_PASSWORD and DB_NAME):
        raise ValueError(
            "Database environment variables are required in Railway. "
            "Please add a MySQL service in Railway or set DB_HOST, DB_USER, DB_PASSWORD, and DB_NAME manually."
        )
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
