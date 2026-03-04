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

## 💻 로컬 개발

### 필수 환경 변수

`.env` 파일을 생성하거나 환경 변수를 설정하세요:

```bash
# 데이터베이스 (로컬 MySQL)
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=daewoong
DB_PORT=3306
ENABLE_DB_SAVE=true

# 네이버 API
NAVER_CLIENT_ID=your_client_id
NAVER_CLIENT_SECRET=your_client_secret

# 검색 키워드
SEARCH_KEYWORD=프리스타일 리브레2

# S3 (선택)
ENABLE_S3_UPLOAD=true
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=ap-northeast-2
S3_BUCKET=your_bucket_name
S3_PREFIX=libre2
S3_UPLOAD_MAX_PER_RUN=20
ENABLE_CARD_RENDER=true
# S3_PUBLIC_BASE_URL=https://cdn.example.com  # CloudFront 사용 시
# S3_ENDPOINT_URL=https://s3.ap-northeast-2.amazonaws.com  # S3 호환 스토리지 사용 시
```

`ENABLE_CARD_RENDER=true`이면 크롤링 시 상품 썸네일을 기반으로 증빙 카드 PNG를 생성한 뒤 S3에 업로드합니다.
카드에는 생성 시각(KST), 단가, 총가격, 수량, 판매처, 링크가 포함됩니다.

### 실행 방법

```bash
# 가상환경 생성
python -m venv venv

# 가상환경 활성화 (Windows)
venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt

# API 서버 실행
uvicorn api.main:app --reload

# 크롤링 수동 실행
python -m scripts.crawl_naver
```

## 📁 프로젝트 구조

```
.
├── api/                 # FastAPI 애플리케이션
│   ├── main.py         # FastAPI 앱 진입점
│   ├── database.py     # 데이터베이스 연결 및 초기화
│   ├── schemas.py      # Pydantic 스키마
│   └── routers/        # API 라우터
│       ├── health.py   # 헬스 체크
│       └── products.py # 상품 데이터 API
├── scripts/            # 크롤링 스크립트
│   ├── crawl_naver.py # 네이버 쇼핑 크롤링
│   └── render_evidence_card.py  # 증빙 카드 이미지 생성 (Playwright)
├── config.py          # 환경 변수 설정
├── Procfile           # Railway 배포 설정
└── requirements.txt   # Python 패키지 의존성
```

## 🤝 협업 가이드

### GitHub 협업자 초대

1. GitHub 저장소 → **Settings** → **Collaborators**
2. **Add people** 클릭
3. 협업자의 GitHub 사용자명 또는 이메일 입력
4. 초대 수락 대기

### 코드 기여

1. 새로운 브랜치 생성: `git checkout -b feature/your-feature`
2. 변경사항 커밋: `git commit -m "Add feature"`
3. 브랜치 푸시: `git push origin feature/your-feature`
4. Pull Request 생성

## 📝 참고사항

- 크롤링은 매일 00:00 KST와 12:00 KST에 자동 실행됩니다
- Railway Cron Job은 스케줄 시간에 컨테이너를 시작하고 작업 완료 후 종료합니다
- 데이터베이스 스키마는 API 서버 시작 시 자동으로 생성됩니다 (`init_db()`)