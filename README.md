# Libre2 Price Monitoring API

프리스타일 리브레2 가격 모니터링 API 서버

## 🚀 Railway 배포 가이드

### 1. 프로젝트 구조

Railway에서 다음 서비스들이 배포됩니다:

- **`web`**: FastAPI 서버 (24/7 실행)
- **`Cron Job (네이버)`**: 하루 6회 네이버 자동 크롤링 (03:00, 06:00, 09:00, 15:00, 18:00, 21:00 KST)
- **`MySQL`**: 데이터베이스 서비스

**쿠팡 크롤링은 Railway가 아니라 회사 서버 crontab에서 실행됩니다.** 쿠팡은 anti-bot 우회를 위해
Bright Data Scraping Browser(한국 주거용 프록시)가 필요해 사내 서버에서 돌리며, 수집 결과는 네이버와
동일한 Railway MySQL에 저장됩니다. 상세는 아래 **쿠팡 크롤러 운영 (회사 서버)** 섹션을 참고하세요.

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
2. **Schedule**: `0 0,6,9,12,18,21 * * *`
   - Railway Cron은 **UTC 기준**입니다. 위 식은 KST 03:00 / 06:00 / 09:00 / 15:00 / 18:00 / 21:00에 해당합니다 (KST = UTC + 9).
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

> **참고**: DB 저장은 위 `MYSQL*` 5개 변수만 있으면 동작합니다.
> `ENABLE_DB_SAVE`는 `config.py`에 정의만 되어 있고 이를 읽는 코드가 없으므로, 설정해도 아무 효과가 없습니다.

**참고**: Variables에서 MySQL 서비스를 참조하는 변수를 추가하면 Architecture 탭에서 자동으로 화살표(연결)가 생성됩니다.

### 3. API 엔드포인트

- `GET /` - API 정보
- `GET /docs` - Swagger UI 문서
- `GET /health` - 헬스 체크
- `GET /products/latest` - 최신 상품 데이터 (최신 크롤링 스냅샷)
- `GET /products/lowest?limit=10` - 최저가 상품 조회
- `POST /products/crawl/run` - 수동 크롤링 실행 (대시보드 버튼용)
- `GET /products/crawl/status` - 수동/자동 크롤링 실행 상태 조회

## 🛒 쿠팡 크롤러 운영 (회사 서버)

쿠팡은 Cloudflare/Akamai 계열 anti-bot 때문에 Bright Data Scraping Browser(원격 Chrome + 한국 주거용
프록시)를 경유해야 해서, Railway가 아닌 **회사 서버 crontab**에서 실행합니다. 서버의 클론은 사내
GitLab을 바라보므로, 코드 수정 시 GitHub와 GitLab **양쪽에 반영**해야 합니다.

> ⚠️ `scripts/crawl_coupang_brand.py`는 `scripts/crawl_naver.py`의 `analyze_product`, `save_to_db`,
> `NON_LIBRE_CGM_EXCLUDE_PATTERNS`, `load_confirmed_qty_by_link_map`를 그대로 가져다 씁니다.
> 즉 단가 계산·수량 추론·제외 키워드는 **네이버와 쿠팡 공용 로직**이며, 한쪽 저장소에만 반영하면
> 채널 간 단가가 어긋납니다.

### 환경 구성

```bash
cd /home/develop/daewoong/libre2-monitor/libre2-api
python3 -m venv .venv
. .venv/bin/activate   # 서버 기본 셸이 sh이므로 source 대신 . 사용
pip install -r requirements.txt
playwright install chromium
```

### 환경변수 파일 (git 제외 — `.gitignore`의 `*.env` 패턴)

- `.env`: `MYSQLHOST` / `MYSQLPORT` / `MYSQLUSER` / `MYSQLPASSWORD` / `MYSQLDATABASE`, `SEARCH_KEYWORD`
- `proxy.env`: `BRIGHT_DATA_PROXY` / `BRIGHT_DATA_USERNAME` / `BRIGHT_DATA_PASSWORD` / `BRIGHT_DATA_BROWSER_WSS`

`crawl_coupang_brand.py`는 시작 시 `.env`와 `proxy.env`를 모두 로드합니다.
(AWS·S3 키는 쿠팡 크롤러에서 사용하지 않으므로 서버에 둘 필요가 없습니다.)

### 실행 및 스케줄

```bash
python -m scripts.crawl_coupang_brand
```

crontab (하루 6회, 서버 시간대 KST 기준):

```
0 3,6,9,15,18,21 * * * cd /home/develop/daewoong/libre2-monitor/libre2-api && .venv/bin/python -m scripts.crawl_coupang_brand >> coupang_cron.log 2>&1
```

로그 확인: `tail -f coupang_cron.log` (성공 시 `DB inserted: N개` 출력)

대시보드의 "수동 크롤링" 버튼은 `POST /products/crawl/run`으로 들어와, 쿠팡의 경우
`api/services/coupang_remote.py`가 `COUPANG_SSH_*` 환경변수로 이 서버에 SSH 접속해 같은 명령을
백그라운드 실행합니다(로그는 `coupang_manual.log`로 분리). `COUPANG_SSH_HOST` / `USER` / `PASSWORD`가
모두 설정되어 있지 않으면 에러 없이 `skipped`로 넘어갑니다.

### 크롤링 대상 브랜드 스토어

`scripts/crawl_coupang_brand.py`의 `BRAND_STORES` 리스트에 스토어별 URL, 최소가 필터(`min_price`),
상품명 필터(`name_filter`)가 정의되어 있습니다. 신규 브랜드는 이 리스트에 항목만 추가하면 됩니다.

### 트러블슈팅

| 증상 | 확인 사항 |
| --- | --- |
| Access Denied | `proxy.env` 크리덴셜, Bright Data Zone 활성 상태 및 잔여 크레딧 |
| WSS 연결 실패 | 내장 재시도(3회) 대기, Scraping Browser Zone 활성 여부, `brd.superproxy.io:9222` 아웃바운드 허용 |
| DB 저장 안 됨 (inserted: 0) | `.env`의 `MYSQL*` 5개 값, Railway MySQL 서비스 running 상태 |

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
# (참고) 테이블명은 DB_TABLE로 덮어쓸 수 있지만 크롤러만 이 값을 사용하고
#        API는 products를 하드코딩하므로, 기본값 products에서 변경하지 마세요.

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
# 0 또는 음수면 해당 실행의 전체 상품 카드를 업로드
S3_UPLOAD_MAX_PER_RUN=0
ENABLE_CARD_RENDER=true
# S3_PUBLIC_BASE_URL=https://cdn.example.com  # CloudFront 사용 시
# S3_ENDPOINT_URL=https://s3.ap-northeast-2.amazonaws.com  # S3 호환 스토리지 사용 시
```

`ENABLE_CARD_RENDER=true`이면 크롤링 시 상품 썸네일을 기반으로 증빙 카드 PNG를 생성한 뒤 S3에 업로드합니다.
카드에는 생성 시각(KST), 단가, 총가격, 수량, 판매처, 링크가 포함됩니다.
Railway에서 카드 렌더를 사용하려면 Linux 런타임 라이브러리가 필요하며, 본 저장소의 `nixpacks.toml`로 자동 설치됩니다.

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

- 크롤링은 매일 03:00, 06:00, 09:00, 15:00, 18:00, 21:00 KST에 자동 실행됩니다
  (네이버 = Railway Cron Job, 쿠팡 = 회사 서버 crontab)
- Railway Cron Job의 Schedule은 **UTC 기준**이며, 스케줄 시간에 컨테이너를 시작하고 작업 완료 후 종료합니다
- 앱 내장 스케줄러(`api/scheduler.py`)는 `ENABLE_SCHEDULER` 기본값이 `false`라 비활성 상태입니다.
  켤 경우 구버전 쿠팡 크롤러(`scripts/crawl_coupang_urls.py`)까지 함께 돌므로 중복 수집에 주의하세요.
- 데이터베이스 스키마는 API 서버 시작 시 자동으로 생성됩니다 (`init_db()`)
