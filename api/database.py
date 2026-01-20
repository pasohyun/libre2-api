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

# 디버깅: Railway 환경 변수 확인
if IS_RAILWAY:
    print(f"🔍 Railway 환경 감지됨")
    print(f"   MYSQLHOST: {os.getenv('MYSQLHOST')}")
    print(f"   MYSQLUSER: {os.getenv('MYSQLUSER')}")
    print(f"   MYSQLDATABASE: {os.getenv('MYSQLDATABASE')}")
    print(f"   PORT: {os.getenv('PORT')}")

if IS_RAILWAY:
    # Railway MySQL 서비스의 환경 변수 사용 (자동 설정됨)
    # Railway가 MySQL 서비스를 추가하면 MYSQL* 환경 변수를 자동으로 설정합니다
    # 또는 MySQL 서비스의 변수 참조: ${{ MySQL.MYSQLHOST }} 형식
    DB_HOST = os.getenv("MYSQLHOST") or os.getenv("MYSQL_HOST") or config.DB_HOST
    DB_USER = os.getenv("MYSQLUSER") or os.getenv("MYSQL_USER") or config.DB_USER
    DB_PASSWORD = os.getenv("MYSQLPASSWORD") or os.getenv("MYSQL_PASSWORD") or config.DB_PASSWORD
    DB_NAME = os.getenv("MYSQLDATABASE") or os.getenv("MYSQL_DATABASE") or config.DB_NAME
    DB_PORT = int(os.getenv("MYSQLPORT") or os.getenv("MYSQL_PORT") or config.DB_PORT or 3306)
    
    print(f"📊 사용할 DB 설정:")
    print(f"   DB_HOST: {DB_HOST}")
    print(f"   DB_USER: {DB_USER}")
    print(f"   DB_NAME: {DB_NAME}")
    print(f"   DB_PORT: {DB_PORT}")
    
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

# 테이블 자동 생성
def init_db():
    """데이터베이스 테이블이 없으면 자동으로 생성"""
    from sqlalchemy import text
    
    create_table_sql = text("""
        CREATE TABLE IF NOT EXISTS products (
            id INT AUTO_INCREMENT PRIMARY KEY,
            keyword VARCHAR(255),
            product_name TEXT,
            unit_price INT,
            quantity INT,
            total_price INT,
            mall_name VARCHAR(255),
            calc_method VARCHAR(50),
            link TEXT,
            image_url TEXT,
            card_image_path TEXT,
            channel VARCHAR(50),
            market VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_unit_price (unit_price),
            INDEX idx_created_at (created_at),
            INDEX idx_channel (channel)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    
    try:
        with engine.connect() as conn:
            conn.execute(create_table_sql)
            conn.commit()
        print("✅ Database table 'products' initialized successfully")
    except Exception as e:
        print(f"⚠️ Warning: Could not initialize database table: {e}")
