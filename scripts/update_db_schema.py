#!/usr/bin/env python3
"""
로컬 DB 테이블에 channel, market 컬럼 추가 스크립트
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector
import config

def update_schema():
    """products 테이블에 channel, market 컬럼 추가"""
    conn = mysql.connector.connect(
        host=config.DB_HOST or "localhost",
        port=config.DB_PORT or 3306,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
    )
    cur = conn.cursor()
    
    try:
        # channel 컬럼 추가 (없는 경우만)
        try:
            cur.execute("""
                ALTER TABLE products 
                ADD COLUMN channel VARCHAR(50) AFTER card_image_path
            """)
            print("✅ channel 컬럼 추가 완료")
        except mysql.connector.Error as e:
            if "Duplicate column name" in str(e):
                print("ℹ️  channel 컬럼이 이미 존재합니다")
            else:
                raise
        
        # market 컬럼 추가 (없는 경우만)
        try:
            cur.execute("""
                ALTER TABLE products 
                ADD COLUMN market VARCHAR(100) AFTER channel
            """)
            print("✅ market 컬럼 추가 완료")
        except mysql.connector.Error as e:
            if "Duplicate column name" in str(e):
                print("ℹ️  market 컬럼이 이미 존재합니다")
            else:
                raise
        
        # 인덱스 추가 (없는 경우만)
        try:
            cur.execute("""
                CREATE INDEX idx_channel ON products(channel)
            """)
            print("✅ channel 인덱스 추가 완료")
        except mysql.connector.Error as e:
            if "Duplicate key name" in str(e):
                print("ℹ️  channel 인덱스가 이미 존재합니다")
            else:
                raise
        
        conn.commit()
        print("\n✅ DB 스키마 업데이트 완료!")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ 에러 발생: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    # 로컬 개발용: 환경 변수 또는 config에서 가져오기
    db_host = config.DB_HOST or os.getenv("DB_HOST") or "localhost"
    db_user = config.DB_USER or os.getenv("DB_USER")
    db_password = config.DB_PASSWORD or os.getenv("DB_PASSWORD")
    db_name = config.DB_NAME or os.getenv("DB_NAME")
    db_port = config.DB_PORT or int(os.getenv("DB_PORT", 3306))
    
    if not all([db_user, db_password, db_name]):
        print("⚠️  DB 환경 변수가 설정되지 않았습니다.")
        print("   config.py 또는 환경 변수에 DB_HOST, DB_USER, DB_PASSWORD, DB_NAME을 설정하세요.")
        exit(1)
    
    # config 객체 업데이트 (임시)
    config.DB_HOST = db_host
    config.DB_USER = db_user
    config.DB_PASSWORD = db_password
    config.DB_NAME = db_name
    config.DB_PORT = db_port
    
    print("로컬 DB 스키마 업데이트 시작...")
    update_schema()
