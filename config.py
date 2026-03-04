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
ENABLE_S3_UPLOAD = os.getenv("ENABLE_S3_UPLOAD", "false").lower() == "true"

# S3 (AWS S3 / S3-compatible)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_PREFIX = os.getenv("S3_PREFIX", "libre2")
S3_PUBLIC_BASE_URL = os.getenv("S3_PUBLIC_BASE_URL")  # e.g. CloudFront URL
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")  # optional for S3-compatible storage
# <= 0 이면 해당 실행에서 생성된 모든 상품 카드를 업로드
S3_UPLOAD_MAX_PER_RUN = int(os.getenv("S3_UPLOAD_MAX_PER_RUN", "0"))

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# 가격 모니터링 설정
TARGET_PRICE = int(os.getenv("TARGET_PRICE", 90000))  # 기준가 (이 가격 이하면 알림)

# 주요 판매처 목록 (환경변수로 설정 가능, 쉼표로 구분)
# 예: TRACKED_MALLS=레디투힐,무화당,메디프라,글루어트
_tracked_malls_env = os.getenv("TRACKED_MALLS", "")
TRACKED_MALLS = [m.strip() for m in _tracked_malls_env.split(",") if m.strip()] if _tracked_malls_env else []

# 검증은 실제 사용 시점에 수행 (save_to_db, database.py 등에서)