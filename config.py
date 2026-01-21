# config.py
import os

SEARCH_KEYWORD = os.getenv("SEARCH_KEYWORD", "프리스타일 리브레2")

HEADLESS = True
SCREENSHOT_DIR = "screenshots"

NAVER_SEARCH_URL = "https://search.shopping.naver.com/search/all?query={}"
COUPANG_SEARCH_URL = "https://www.coupang.com/np/search?q={}"

MAX_QUANTITY = 7

# MySQL (환경변수 기반)
# Railway 환경 변수 우선, 없으면 일반 환경 변수 사용
DB_HOST = os.getenv("MYSQLHOST") or os.getenv("DB_HOST")
DB_PORT = int(os.getenv("MYSQLPORT") or os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("MYSQLUSER") or os.getenv("DB_USER")
DB_PASSWORD = os.getenv("MYSQLPASSWORD") or os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("MYSQLDATABASE") or os.getenv("DB_NAME")
DB_TABLE = os.getenv("DB_TABLE", "products")

ENABLE_DB_SAVE = os.getenv("ENABLE_DB_SAVE", "false").lower() == "true"
ENABLE_CARD_RENDER = os.getenv("ENABLE_CARD_RENDER", "false").lower() == "true"

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# 검증은 실제 사용 시점에 수행 (save_to_db, database.py 등에서)