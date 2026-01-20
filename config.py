# config.py
import os

SEARCH_KEYWORD = os.getenv("SEARCH_KEYWORD", "프리스타일 리브레2")

HEADLESS = True
SCREENSHOT_DIR = "screenshots"

NAVER_SEARCH_URL = "https://search.shopping.naver.com/search/all?query={}"
COUPANG_SEARCH_URL = "https://www.coupang.com/np/search?q={}"

MAX_QUANTITY = 7

# MySQL (환경변수 기반)
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_TABLE = os.getenv("DB_TABLE", "products")

ENABLE_DB_SAVE = os.getenv("ENABLE_DB_SAVE", "false").lower() == "true"
ENABLE_CARD_RENDER = os.getenv("ENABLE_CARD_RENDER", "false").lower() == "true"

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# Railway 배포를 위한 환경 변수 검증
# API 서버가 아닌 경우(예: worker 서비스)에는 선택적으로 검증
import sys
is_api_server = "api.main" in " ".join(sys.argv) or "gunicorn" in " ".join(sys.argv)

if is_api_server:
    # API 서버인 경우에만 NAVER API 검증 (실제로는 API 서버에서 사용 안 함)
    # 하지만 config를 import할 때 검증되므로 일단 주석 처리
    # assert NAVER_CLIENT_ID and NAVER_CLIENT_SECRET, "NAVER API env missing"
    pass

if ENABLE_DB_SAVE:
    assert DB_HOST and DB_USER and DB_PASSWORD and DB_NAME, "DB env missing"