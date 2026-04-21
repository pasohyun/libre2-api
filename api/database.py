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


def _merge_monthly_metrics_seller_rename(conn, old_name: str, new_name: str) -> None:
    """
    동일 (month, threshold_price, channel)에 old·new 행이 둘 다 있으면
    단순 UPDATE seller_name_std 시 uq_month_seller 충돌(1062)이 난다.
    기존 new 행으로 수치를 합친 뒤 old 행을 삭제한다.
    """
    conn.execute(
        text(
            """
            UPDATE monthly_seller_metrics AS k
            INNER JOIN monthly_seller_metrics AS o
              ON k.month = o.month
             AND k.threshold_price = o.threshold_price
             AND k.channel = o.channel
             AND k.seller_name_std = :new_name
             AND o.seller_name_std = :old_name
            SET
              k.observations = k.observations + o.observations,
              k.below_threshold_count = k.below_threshold_count + o.below_threshold_count,
              k.below_ratio = CASE
                WHEN (k.observations + o.observations) > 0 THEN
                  (k.below_threshold_count + o.below_threshold_count) * 1.0
                  / (k.observations + o.observations)
                ELSE k.below_ratio
              END,
              k.min_unit_price = CASE
                WHEN k.min_unit_price IS NULL THEN o.min_unit_price
                WHEN o.min_unit_price IS NULL THEN k.min_unit_price
                ELSE LEAST(k.min_unit_price, o.min_unit_price)
              END,
              k.min_time = CASE
                WHEN k.min_time IS NULL THEN o.min_time
                WHEN o.min_time IS NULL THEN k.min_time
                ELSE LEAST(k.min_time, o.min_time)
              END,
              k.last_below_time = CASE
                WHEN k.last_below_time IS NULL THEN o.last_below_time
                WHEN o.last_below_time IS NULL THEN k.last_below_time
                ELSE GREATEST(k.last_below_time, o.last_below_time)
              END,
              k.representative_links = COALESCE(k.representative_links, o.representative_links),
              k.calc_method_stats = COALESCE(k.calc_method_stats, o.calc_method_stats),
              k.dip_recover_count = COALESCE(k.dip_recover_count, 0)
                + COALESCE(o.dip_recover_count, 0),
              k.sustained_below_count = COALESCE(k.sustained_below_count, 0)
                + COALESCE(o.sustained_below_count, 0),
              k.cross_platform_mismatch = GREATEST(
                COALESCE(k.cross_platform_mismatch, 0),
                COALESCE(o.cross_platform_mismatch, 0)
              )
            """
        ),
        {"new_name": new_name, "old_name": old_name},
    )
    conn.execute(
        text(
            """
            DELETE o FROM monthly_seller_metrics o
            INNER JOIN monthly_seller_metrics k
              ON o.month = k.month
             AND o.threshold_price = k.threshold_price
             AND o.channel = k.channel
             AND o.seller_name_std = :old_name
             AND k.seller_name_std = :new_name
            """
        ),
        {"new_name": new_name, "old_name": old_name},
    )


def _normalize_mall_names(conn):
    """
    과거 판매처명을 표준명으로 치환한다.
    - products.mall_name
    - monthly_seller_metrics.seller_name_std
    """
    mappings = [
        ("글루어트", "글루코핏"),
        ("무화당", "닥다몰"),
    ]

    for old_name, new_name in mappings:
        conn.execute(
            text("UPDATE products SET mall_name = :new_name WHERE mall_name = :old_name"),
            {"new_name": new_name, "old_name": old_name},
        )
        _merge_monthly_metrics_seller_rename(conn, old_name, new_name)
        conn.execute(
            text(
                "UPDATE monthly_seller_metrics "
                "SET seller_name_std = :new_name "
                "WHERE seller_name_std = :old_name"
            ),
            {"new_name": new_name, "old_name": old_name},
        )


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

    create_dashboard_memos_sql = text(
        """
        CREATE TABLE IF NOT EXISTS dashboard_memos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            scope VARCHAR(20) NOT NULL,
            channel VARCHAR(50) NULL,
            vendor_label VARCHAR(255) NULL,
            body LONGTEXT NOT NULL,
            summary VARCHAR(500) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_scope_created (scope, created_at),
            INDEX idx_vendor (scope, channel, vendor_label)
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

    create_alert_settings_sql = text(
        """
        CREATE TABLE IF NOT EXISTS alert_settings (
            id INT PRIMARY KEY,
            enabled TINYINT(1) NOT NULL DEFAULT 0,
            recipient_email VARCHAR(255) NOT NULL,
            threshold_price INT NOT NULL,
            source_times_kst VARCHAR(100) NOT NULL DEFAULT '00:00,12:00',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    create_alert_delivery_logs_sql = text(
        """
        CREATE TABLE IF NOT EXISTS alert_delivery_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            target_date DATE NOT NULL,
            recipient_email VARCHAR(255) NOT NULL,
            threshold_price INT NOT NULL,
            mall_count INT NOT NULL DEFAULT 0,
            sent_at DATETIME NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_alert_daily_send (target_date, recipient_email, threshold_price)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )

    try:
        with engine.connect() as conn:
            conn.execute(create_products_sql)
            conn.execute(create_monthly_metrics_sql)
            conn.execute(create_dashboard_memos_sql)
            conn.execute(create_monthly_reports_sql)
            conn.execute(create_alert_settings_sql)
            conn.execute(create_alert_delivery_logs_sql)

            _safe_alter(conn, "ALTER TABLE products ADD COLUMN snapshot_id VARCHAR(40) NULL")
            _safe_alter(conn, "ALTER TABLE products ADD COLUMN snapshot_at DATETIME NULL")
            _safe_alter(conn, "ALTER TABLE products ADD COLUMN calc_valid TINYINT(1) DEFAULT 1")
            _safe_alter(conn, "ALTER TABLE products ADD COLUMN channel VARCHAR(50) NULL")
            _safe_alter(conn, "ALTER TABLE products ADD COLUMN market VARCHAR(100) NULL")
            _safe_alter(conn, "CREATE INDEX idx_snapshot_at ON products(snapshot_at)")
            _safe_alter(conn, "CREATE INDEX idx_snapshot_id ON products(snapshot_id)")

            _normalize_mall_names(conn)
            conn.commit()

        print("✅ Database initialized successfully (products + memos + reports + alerts tables)")
    except Exception as e:
        print(f"⚠️ Warning: Could not initialize database tables: {e}")
