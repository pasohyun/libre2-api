# api/database.py
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os

import config

IS_RAILWAY = (
    os.getenv("RAILWAY_ENVIRONMENT") is not None
    or os.getenv("RAILWAY") is not None
    or os.getenv("PORT") is not None
)

if IS_RAILWAY:
    print(f"🔍 Railway 환경 감지됨")
    print(f"   MYSQLHOST: {os.getenv('MYSQLHOST')}")
    print(f"   MYSQLUSER: {os.getenv('MYSQLUSER')}")
    print(f"   MYSQLDATABASE: {os.getenv('MYSQLDATABASE')}")
    print(f"   PORT: {os.getenv('PORT')}")

if IS_RAILWAY:
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

    if not (DB_HOST and DB_USER and DB_PASSWORD and DB_NAME):
        raise ValueError(
            "Database environment variables are required in Railway. "
            "Please add a MySQL service in Railway or set DB_HOST, DB_USER, DB_PASSWORD, and DB_NAME manually."
        )
else:
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


def _safe_alter(conn, ddl_sql: str):
    """컬럼/인덱스가 이미 있으면 에러 무시"""
    try:
        conn.execute(text(ddl_sql))
    except Exception as e:
        msg = str(e).lower()
        if "duplicate" in msg or "already" in msg or "exists" in msg:
            return
        if "1060" in msg or "1061" in msg or "duplicate column" in msg or "duplicate key" in msg:
            return
        raise


def init_db():
    """데이터베이스 테이블/컬럼이 없으면 자동으로 생성/추가"""

    create_products_sql = text(
        """
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
            snapshot_id VARCHAR(40) NULL,
            snapshot_at DATETIME NULL,
            calc_valid TINYINT(1) DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_unit_price (unit_price),
            INDEX idx_created_at (created_at),
            INDEX idx_channel (channel),
            INDEX idx_snapshot_at (snapshot_at),
            INDEX idx_snapshot_id (snapshot_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    create_monthly_metrics_sql = text(
        """
        CREATE TABLE IF NOT EXISTS monthly_seller_metrics (
            id INT AUTO_INCREMENT PRIMARY KEY,
            month CHAR(7) NOT NULL,
            threshold_price INT NOT NULL,
            channel VARCHAR(50) NOT NULL,
            seller_name_std VARCHAR(255) NOT NULL,

            observations INT NOT NULL,
            below_threshold_count INT NOT NULL,
            below_ratio FLOAT NOT NULL,

            min_unit_price INT NULL,
            min_time DATETIME NULL,
            last_below_time DATETIME NULL,

            volatility FLOAT NULL,
            representative_links JSON NULL,
            calc_method_stats JSON NULL,

            dip_recover_count INT NULL,
            sustained_below_count INT NULL,
            cross_platform_mismatch TINYINT(1) NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

            UNIQUE KEY uq_month_seller (month, threshold_price, channel, seller_name_std),
            INDEX idx_month_channel (month, channel)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    create_monthly_reports_sql = text(
        """
        CREATE TABLE IF NOT EXISTS monthly_reports (
            id INT AUTO_INCREMENT PRIMARY KEY,
            month CHAR(7) NOT NULL,
            threshold_price INT NOT NULL,
            channel VARCHAR(50) NOT NULL,

            report_md LONGTEXT NULL,
            report_json JSON NULL,

            generated_at DATETIME NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

            UNIQUE KEY uq_month_report (month, threshold_price, channel)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    try:
        with engine.connect() as conn:
            conn.execute(create_products_sql)
            conn.execute(create_monthly_metrics_sql)
            conn.execute(create_monthly_reports_sql)

            _safe_alter(conn, "ALTER TABLE products ADD COLUMN snapshot_id VARCHAR(40) NULL")
            _safe_alter(conn, "ALTER TABLE products ADD COLUMN snapshot_at DATETIME NULL")
            _safe_alter(conn, "ALTER TABLE products ADD COLUMN calc_valid TINYINT(1) DEFAULT 1")
            _safe_alter(conn, "CREATE INDEX idx_snapshot_at ON products(snapshot_at)")
            _safe_alter(conn, "CREATE INDEX idx_snapshot_id ON products(snapshot_id)")

            conn.commit()

        print("✅ Database initialized successfully (products + monthly report tables)")
    except Exception as e:
        print(f"⚠️ Warning: Could not initialize database tables: {e}")
