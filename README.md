# Libre2 Price Monitoring API

프리스타일 리브레2 가격 모니터링 API 서버

## 🚀 Railway 배포 가이드

### 1. 프로젝트 구조

Railway에서 다음 서비스들이 배포됩니다:

- **`web`**: FastAPI 서버 (24/7 실행)
- **`Cron Job A (00:00 KST)`**: 매일 자정 크롤링 실행
- **`Cron Job B (12:00 KST)`**: 매일 정오 크롤링 실행
- **`MySQL`**: 데이터베이스 서비스

### 2. Railway 설정

#### 2.1 MySQL 서비스 추가

1. Railway 프로젝트 → **+ New** → **Database** → **MySQL** 선택
2. MySQL 서비스가 자동으로 생성됩니다

#### 2.2 Web 서비스 설정

1. GitHub 저장소 연결
2. Railway가 자동으로 `Procfile`의 `web` 명령어를 사용하여 배포
3. **Variables** 탭에서 환경 변수 설정:
   - `NAVER_CLIENT_ID`: 네이버 API 클라이언트 ID
   - `NAVER_CLIENT_SECRET`: 네이버 API 클라이언트 시크릿
   - `SEARCH_KEYWORD`: 검색 키워드 (기본값: "프리스타일 리브레2")

#### 2.3 Cron Job 서비스 추가

1. **+ New** → **Cron Job** 선택
2. **Schedule**: `0 0 * * *` (매일 00:00 KST) 또는 `0 12 * * *` (매일 12:00 KST)
3. **Command**: `python -m scripts.crawl_naver`
4. **Variables** 탭에서 환경 변수 설정:
   - `MYSQLHOST = ${{ MySQL.MYSQLHOST }}`
   - `MYSQLUSER = ${{ MySQL.MYSQLUSER }}`
   - `MYSQLPASSWORD = ${{ MySQL.MYSQLPASSWORD }}`
   - `MYSQLDATABASE = ${{ MySQL.MYSQLDATABASE }}`
   - `MYSQLPORT = ${{ MySQL.MYSQLPORT }}`
   - `NAVER_CLIENT_ID`: 네이버 API 클라이언트 ID
   - `NAVER_CLIENT_SECRET`: 네이버 API 클라이언트 시크릿
   - `SEARCH_KEYWORD`: 검색 키워드
   - `ENABLE_DB_SAVE=true`

**참고**: Variables에서 MySQL 서비스를 참조하는 변수를 추가하면 Architecture 탭에서 자동으로 화살표(연결)가 생성됩니다.

### 3. API 엔드포인트

- `GET /` - API 정보
- `GET /docs` - Swagger UI 문서
- `GET /health` - 헬스 체크
- `GET /products/latest` - 최신 상품 데이터 (최신 크롤링 스냅샷)
- `GET /products/lowest?limit=10` - 최저가 상품 조회

## 로컬 개발

```bash
# 가상환경 생성
python -m venv venv

# 가상환경 활성화 (Windows)
venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt

# 서버 실행
uvicorn api.main:app --reload
```
