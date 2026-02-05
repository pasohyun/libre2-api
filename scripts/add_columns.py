#!/usr/bin/env python3
"""
로컬 DB에 channel, market 컬럼 추가
사용법: python scripts/add_columns.py
"""
import mysql.connector

# 로컬 DB 정보 (여기에 본인의 DB 정보 입력)
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",  # 본인의 MySQL 사용자명
    "password": "",  # 본인의 MySQL 비밀번호
    "database": "daewoong",  # 본인의 DB 이름
}

def add_columns():
    try:
        conn = mysql.connector.connect(**DB_CONFIG, charset="utf8mb4")
        cur = conn.cursor()
        
        # channel 컬럼 추가
        try:
            cur.execute("ALTER TABLE products ADD COLUMN channel VARCHAR(50) AFTER card_image_path")
            print("✅ channel 컬럼 추가 완료")
        except mysql.connector.Error as e:
            if "Duplicate column name" in str(e):
                print("ℹ️  channel 컬럼이 이미 존재합니다")
            else:
                raise
        
        # market 컬럼 추가
        try:
            cur.execute("ALTER TABLE products ADD COLUMN market VARCHAR(100) AFTER channel")
            print("✅ market 컬럼 추가 완료")
        except mysql.connector.Error as e:
            if "Duplicate column name" in str(e):
                print("ℹ️  market 컬럼이 이미 존재합니다")
            else:
                raise
        
        # 인덱스 추가
        try:
            cur.execute("CREATE INDEX idx_channel ON products(channel)")
            print("✅ channel 인덱스 추가 완료")
        except mysql.connector.Error as e:
            if "Duplicate key name" in str(e):
                print("ℹ️  channel 인덱스가 이미 존재합니다")
            else:
                raise
        
        conn.commit()
        print("\n✅ 완료! 이제 크롤링을 다시 실행하세요.")
        
    except mysql.connector.Error as e:
        print(f"❌ 에러: {e}")
        print("\n💡 DB 정보를 확인하고 스크립트의 DB_CONFIG를 수정하세요.")
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    print("로컬 DB에 channel, market 컬럼 추가 중...")
    print("⚠️  스크립트의 DB_CONFIG에 본인의 DB 정보를 입력하세요!\n")
    add_columns()
