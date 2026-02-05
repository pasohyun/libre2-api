#!/usr/bin/env python3
"""
Railway MySQL DB에 channel, market 컬럼 추가 스크립트

사용법:
1. Railway MySQL 연결 정보 입력:
   python scripts/update_railway_db.py

2. 또는 환경 변수로 설정:
   set DB_HOST=interchange.proxy.rlwy.net
   set DB_USER=root
   set DB_PASSWORD=본인의_비밀번호
   set DB_NAME=railway
   set DB_PORT=43937
   python scripts/update_railway_db.py
"""
import mysql.connector
import os

def update_railway_db():
    """Railway MySQL products 테이블에 channel, market 컬럼 추가"""
    
    # Railway MySQL 연결 정보
    # Railway Connect 화면에서 본 정보를 여기에 입력하세요
    db_config = {
        "host": os.getenv("DB_HOST") or "interchange.proxy.rlwy.net",
        "port": int(os.getenv("DB_PORT") or 43937),
        "user": os.getenv("DB_USER") or "root",
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME") or "railway",
        "charset": "utf8mb4",
    }
    
    if not db_config["password"]:
        raise ValueError("DB_PASSWORD 환경 변수가 설정되지 않았습니다.")
    
    print("🔗 Railway MySQL에 연결 중...")
    print(f"   Host: {db_config['host']}:{db_config['port']}")
    print(f"   Database: {db_config['database']}\n")
    
    try:
        conn = mysql.connector.connect(**db_config)
        cur = conn.cursor()
        
        print("✅ 연결 성공!\n")
        
        # channel 컬럼 추가
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
        
        # market 컬럼 추가
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
        
        # 인덱스 추가
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
        print("\n✅ Railway DB 스키마 업데이트 완료!")
        print("   이제 API를 다시 테스트해보세요!")
        
    except mysql.connector.Error as e:
        print(f"❌ 에러 발생: {e}")
        if "Access denied" in str(e):
            print("\n💡 Railway Connect 화면에서 'show'를 클릭해서 비밀번호를 확인하세요.")
        raise
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("Railway MySQL DB 스키마 업데이트")
    print("=" * 60)
    
    # 환경 변수에서 먼저 확인
    if not all([os.getenv("DB_HOST"), os.getenv("DB_PASSWORD")]):
        print("\n📋 Railway Connect 화면에서 다음 정보를 확인하세요:")
        print("   - Connection URL 또는 Raw mysql 명령어에서")
        print("   - Host, Port, User, Password, Database 이름")
        print("\n💡 환경 변수로 설정하거나 아래 정보를 입력하세요.\n")
        
        try:
            # 사용자가 정보를 직접 입력하도록 안내
            host = input("MySQL Host (기본값: interchange.proxy.rlwy.net): ").strip()
            port = input("MySQL Port (기본값: 43937): ").strip()
            user = input("MySQL User (기본값: root): ").strip()
            password = input("MySQL Password: ").strip()
            database = input("MySQL Database (기본값: railway): ").strip()
            
            if host:
                os.environ["DB_HOST"] = host
            if port:
                os.environ["DB_PORT"] = port
            if user:
                os.environ["DB_USER"] = user
            if password:
                os.environ["DB_PASSWORD"] = password
            if database:
                os.environ["DB_NAME"] = database
        except (EOFError, KeyboardInterrupt):
            print("\n⚠️  입력이 취소되었습니다. 환경 변수로 설정해주세요.")
            print("   예: $env:DB_HOST='...'; $env:DB_PASSWORD='...'")
            exit(1)
    
    print()
    update_railway_db()
