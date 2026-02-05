# Daewoong 프로젝트 기술 보고서

## 프리스타일 리브레2 가격 모니터링 시스템

---

## 1. 프로젝트 개요

### 1.1 목적
프리스타일 리브레2(연속혈당측정기) 상품의 가격을 자동으로 수집하고, 최저가 정보를 제공하는 가격 모니터링 시스템

### 1.2 주요 기능
- 네이버 쇼핑 API를 통한 자동 가격 크롤링
- 상품 단가 자동 계산 (세트/묶음 상품 분석)
- REST API를 통한 가격 데이터 제공
- 매일 2회 자동 크롤링 (00:00 KST, 12:00 KST)

---

## 2. 파일 구조

```
daewoong/
├── api/                          # FastAPI 애플리케이션
│   ├── __init__.py              # 패키지 초기화
│   ├── main.py                  # FastAPI 앱 진입점, CORS 설정
│   ├── database.py              # DB 연결 및 테이블 초기화
│   ├── schemas.py               # Pydantic 데이터 모델
│   └── routers/                 # API 라우터 모듈
│       ├── __init__.py
│       ├── health.py            # 헬스 체크 엔드포인트
│       └── products.py          # 상품 데이터 API
│
├── scripts/                      # 크롤링 및 유틸리티 스크립트
│   ├── crawl_naver.py           # 네이버 쇼핑 API 크롤링 (메인)
│   ├── no.py                    # 상품 카드 이미지 생성 (부가 기능)
│   ├── add_columns.py           # DB 컬럼 추가 스크립트
│   ├── update_db_schema.py      # DB 스키마 업데이트
│   ├── update_railway_db.py     # Railway DB 업데이트
│   └── test_api.py              # API 테스트 스크립트
│
├── config.py                     # 환경 변수 및 설정 관리
├── Procfile                      # Railway 배포 설정
├── requirements.txt              # Python 패키지 의존성
├── runtime.txt                   # Python 버전 지정
└── README.md                     # 프로젝트 문서
```

### 2.1 파일별 역할 상세

| 파일 | 역할 | 비고 |
|------|------|------|
| `config.py` | 모든 설정값 중앙 관리 | 환경 변수 기반 |
| `api/main.py` | FastAPI 앱 생성, 라우터 등록 | 서버 진입점 |
| `api/database.py` | SQLAlchemy 엔진 생성, 테이블 초기화 | DB 연결 담당 |
| `api/schemas.py` | API 응답 스키마 정의 | Pydantic 모델 |
| `api/routers/products.py` | 상품 조회 API | `/products/*` 엔드포인트 |
| `scripts/crawl_naver.py` | 크롤링 메인 스크립트 | Cron Job에서 실행 |

---

## 3. 크롤링 시스템

### 3.1 크롤링 흐름도

```
┌─────────────────┐
│  Railway Cron   │  ← 매일 00:00, 12:00 KST 실행
│      Job        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ crawl_naver.py  │  ← python -m scripts.crawl_naver
│  run_crawling() │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│              get_naver_data_all(query)              │
│  ┌────────────────────────────────────────────┐    │
│  │  1. 네이버 쇼핑 API 호출                    │    │
│  │     URL: openapi.naver.com/v1/search/shop  │    │
│  │     - 한 번에 100개씩 조회 (display=100)    │    │
│  │     - 최대 1000개까지 페이징 (start=1~1000) │    │
│  │     - 요청 간 0.2초 딜레이                  │    │
│  └────────────────────────────────────────────┘    │
│                        │                            │
│                        ▼                            │
│  ┌────────────────────────────────────────────┐    │
│  │  2. 상품별 분석 (analyze_product)           │    │
│  │     - 상품명에서 수량 추출                  │    │
│  │     - 단가 계산                             │    │
│  │     - 단가 50,000원 미만 제외               │    │
│  └────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│   save_to_db()  │  ← MySQL에 데이터 저장
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  MySQL (Railway)│  ← products 테이블
└─────────────────┘
```

### 3.2 네이버 쇼핑 API 호출

```python
# 파일: scripts/crawl_naver.py

def get_naver_data_all(query):
    """네이버 쇼핑 API로 상품 데이터 전체 수집"""
    
    # API 엔드포인트
    url = f"https://openapi.naver.com/v1/search/shop.json?query={enc}&display=100&start={start}&sort=sim"
    
    # 인증 헤더
    request.add_header("X-Naver-Client-Id", CLIENT_ID)
    request.add_header("X-Naver-Client-Secret", CLIENT_SECRET)
```

### 3.3 API 응답 데이터 구조

```json
{
  "items": [
    {
      "title": "<b>프리스타일</b> <b>리브레</b><b>2</b> 센서 3개입",
      "lprice": "270000",
      "image": "https://...",
      "mallName": "스마트스토어명",
      "link": "https://..."
    }
  ]
}
```

### 3.4 수집 데이터 필드

| 필드 | 타입 | 설명 | 소스 |
|------|------|------|------|
| `keyword` | VARCHAR(255) | 검색 키워드 | config.SEARCH_KEYWORD |
| `product_name` | TEXT | 상품명 (HTML 태그 제거) | API title |
| `unit_price` | INT | **계산된 개당 단가** | 계산값 |
| `quantity` | INT | 추출된 수량 | 분석값 |
| `total_price` | INT | 판매가격 | API lprice |
| `mall_name` | VARCHAR(255) | 판매처 | API mallName |
| `calc_method` | VARCHAR(50) | 계산 방법 | 분석 결과 |
| `link` | TEXT | 상품 URL | API link |
| `image_url` | TEXT | 이미지 URL | API image |
| `channel` | VARCHAR(50) | 채널 (naver) | 고정값 |
| `market` | VARCHAR(100) | 마켓 (스마트스토어) | 고정값 |
| `created_at` | TIMESTAMP | 크롤링 시간 | NOW() |

---

## 4. 단가 계산 로직

### 4.1 계산 흐름

```
┌──────────────────────────────────────────────────────────────┐
│                    analyze_product(title, total_price)       │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 1: 블랙리스트 패턴 제거                                 │
│  - "아메리카노 10개", "커피 5잔", "패치 30매" 등 제거          │
│  - 사은품/증정품 표기가 수량 계산에 영향주지 않도록 처리        │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 2: 수량 추출 (정규표현식)                               │
│  - 패턴 1: "3개", "2세트", "4팩", "5박스", "10ea", "3set"     │
│  - 패턴 2: "x3", "X5", "*2" 형태                              │
│  - 마지막으로 매칭된 수량 사용                                 │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 3: 단가 계산 및 검증                                    │
│                                                              │
│  calc_unit_price = total_price ÷ extracted_qty               │
│                                                              │
│  if 65,000 ≤ calc_unit_price ≤ 130,000:                      │
│      → return (qty, unit_price, "텍스트분석")  ✓ 정상        │
│  else:                                                       │
│      → 가격 역산 보정 시도                                    │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 4: 가격 역산 보정 (텍스트 분석 실패 시)                  │
│                                                              │
│  estimated_qty = round(total_price ÷ 90,000)                 │
│  recalc_price = total_price ÷ estimated_qty                  │
│                                                              │
│  if 65,000 ≤ recalc_price ≤ 130,000:                         │
│      → return (estimated_qty, recalc_price, "가격역산(보정)") │
│  else:                                                       │
│      → return (extracted_qty, calc_unit_price, "확인필요")   │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 계산 로직 코드

```python
# 파일: scripts/crawl_naver.py

def analyze_product(title, total_price):
    """상품명과 총 가격에서 수량과 단가를 분석"""
    
    # 1. 블랙리스트 패턴 제거 (사은품 등)
    black_list = [
        r"아메리카노\s*\d+개", r"커피\s*\d+잔", r"커피\s*\d+개",
        r"패치\s*\d+매", r"패치\s*\d+개", r"알콜솜\s*\d+매",
        r"방수필름\s*\d+매", r"멤버십\s*\d+일", r"유효기간\s*\d+일",
        r"\d+일\s*체험", r"\d+일\s*멤버십"
    ]
    for pattern in black_list:
        clean_title = re.sub(pattern, " ", clean_title)
    
    # 2. 수량 추출
    qty_candidates = []
    matches = re.findall(r"[\sxX](\d+)\s*(개|세트|팩|박스|ea|set)", clean_title)
    for m in matches:
        qty_candidates.append(int(m[0]))
    
    extracted_qty = qty_candidates[-1] if qty_candidates else 1
    
    # 3. 단가 계산 및 검증
    MIN_PRICE, MAX_PRICE = 65000, 130000
    calc_unit_price = total_price // extracted_qty
    
    if MIN_PRICE <= calc_unit_price <= MAX_PRICE:
        return extracted_qty, calc_unit_price, "텍스트분석"
    
    # 4. 가격 역산 보정
    estimated_qty = round(total_price / 90000) or 1
    recalc_price = total_price // estimated_qty
    
    if MIN_PRICE <= recalc_price <= MAX_PRICE:
        return estimated_qty, recalc_price, "가격역산(보정)"
    else:
        return extracted_qty, calc_unit_price, "확인필요"
```

### 4.3 계산 예시

| 상품명 | 판매가 | 추출 수량 | 계산 단가 | 방법 |
|--------|--------|-----------|-----------|------|
| 리브레2 센서 3개입 | 270,000원 | 3 | 90,000원 | 텍스트분석 |
| 리브레2 x5 | 450,000원 | 5 | 90,000원 | 텍스트분석 |
| 리브레2 센서 세트 | 180,000원 | 2* | 90,000원 | 가격역산(보정) |
| 리브레2 특가 | 85,000원 | 1 | 85,000원 | 텍스트분석 |

*수량 정보 없어서 가격 기준으로 2개 추정

### 4.4 필터링 조건

```python
# 단가 50,000원 미만 상품 제외 (리브레가 아닌 상품 필터링)
if unit_price < 50000:
    continue
```

---

## 5. 데이터베이스 구조

### 5.1 테이블 스키마

```sql
CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    keyword VARCHAR(255),           -- 검색 키워드
    product_name TEXT,              -- 상품명
    unit_price INT,                 -- 개당 단가
    quantity INT,                   -- 수량
    total_price INT,                -- 판매가
    mall_name VARCHAR(255),         -- 판매처
    calc_method VARCHAR(50),        -- 계산 방법
    link TEXT,                      -- 상품 URL
    image_url TEXT,                 -- 이미지 URL
    card_image_path TEXT,           -- 카드 이미지 경로 (미사용)
    channel VARCHAR(50),            -- 채널 (naver)
    market VARCHAR(100),            -- 마켓 (스마트스토어)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_unit_price (unit_price),   -- 단가 정렬용
    INDEX idx_created_at (created_at),   -- 최신 데이터 조회용
    INDEX idx_channel (channel)          -- 채널별 필터링용
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 5.2 인덱스 전략

| 인덱스 | 컬럼 | 용도 |
|--------|------|------|
| `PRIMARY KEY` | id | 기본 키 |
| `idx_unit_price` | unit_price | 최저가 정렬 쿼리 최적화 |
| `idx_created_at` | created_at | 최신 스냅샷 조회 최적화 |
| `idx_channel` | channel | 채널별 필터링 (확장성) |

### 5.3 데이터베이스 연결 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    환경 변수 우선순위                        │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│   Railway     │     │   일반 환경   │     │    로컬       │
│   환경 변수   │     │   환경 변수   │     │   기본값      │
│               │     │               │     │               │
│  MYSQLHOST    │     │  DB_HOST      │     │  localhost    │
│  MYSQLUSER    │     │  DB_USER      │     │  daewoong_user│
│  MYSQLPASSWORD│     │  DB_PASSWORD  │     │  (하드코딩)   │
│  MYSQLDATABASE│     │  DB_NAME      │     │  daewoong     │
│  MYSQLPORT    │     │  DB_PORT      │     │  3306         │
└───────────────┘     └───────────────┘     └───────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              SQLAlchemy DATABASE_URL 생성                    │
│   mysql+pymysql://{user}:{password}@{host}:{port}/{db}      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     MySQL Database                           │
│                   (Railway Managed)                          │
└─────────────────────────────────────────────────────────────┘
```

### 5.4 연결 코드

```python
# 파일: api/database.py

# Railway 환경 감지
IS_RAILWAY = (
    os.getenv("RAILWAY_ENVIRONMENT") is not None 
    or os.getenv("RAILWAY") is not None
    or os.getenv("PORT") is not None
)

# Railway 환경: MYSQL* 환경 변수 사용
if IS_RAILWAY:
    DB_HOST = os.getenv("MYSQLHOST") or os.getenv("MYSQL_HOST") or config.DB_HOST
    DB_USER = os.getenv("MYSQLUSER") or os.getenv("MYSQL_USER") or config.DB_USER
    # ... 생략

# 로컬 환경: 기본값 사용
else:
    DB_HOST = config.DB_HOST or "localhost"
    # ... 생략

# SQLAlchemy 엔진 생성
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
engine = create_engine(DATABASE_URL, pool_recycle=3600)
```

---

## 6. API 서버

### 6.1 엔드포인트 목록

| 메서드 | 경로 | 설명 | 응답 |
|--------|------|------|------|
| GET | `/` | API 정보 | JSON |
| GET | `/docs` | Swagger UI | HTML |
| GET | `/health` | 헬스 체크 | JSON |
| GET | `/products/latest` | 최신 크롤링 데이터 | ProductListResponse |
| GET | `/products/lowest?limit=N` | 최저가 TOP N | JSON |

### 6.2 API 응답 스키마

```python
# 파일: api/schemas.py

class Product(BaseModel):
    product_name: str      # 상품명
    unit_price: int        # 단가
    quantity: int          # 수량
    total_price: int       # 판매가
    mall_name: str         # 판매처
    calc_method: str       # 계산 방법
    link: str              # 상품 URL
    image_url: str         # 이미지 URL
    channel: str | None    # 채널
    market: str | None     # 마켓

class ProductListResponse(BaseModel):
    snapshot_time: datetime | None  # 크롤링 시간
    count: int                      # 상품 수
    data: List[Product]             # 상품 목록
```

### 6.3 `/products/latest` 응답 예시

```json
{
  "snapshot_time": "2026-01-28T15:00:00",
  "count": 567,
  "data": [
    {
      "product_name": "프리스타일 리브레2 센서",
      "unit_price": 78000,
      "quantity": 1,
      "total_price": 78000,
      "mall_name": "의료기기전문몰",
      "calc_method": "텍스트분석",
      "link": "https://smartstore.naver.com/...",
      "image_url": "https://shopping-phinf.pstatic.net/...",
      "channel": "naver",
      "market": "스마트스토어"
    },
    // ... 단가 오름차순 정렬
  ]
}
```

### 6.4 CORS 설정

```python
# 파일: api/main.py

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",                           # 로컬 React
        "http://localhost:5173",                           # 로컬 Vite
        "https://libre-price-monitor-client.vercel.app",   # Production
        "https://*.vercel.app",                            # Preview
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 7. 배포 구조

### 7.1 Railway 서비스 구성

```
┌─────────────────────────────────────────────────────────────┐
│                      Railway Project                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐ │
│  │    Web      │      │  Cron Job A │      │  Cron Job B │ │
│  │   Service   │      │  (00:00 KST)│      │  (12:00 KST)│ │
│  │             │      │             │      │             │ │
│  │  FastAPI    │      │  crawl_     │      │  crawl_     │ │
│  │  + Gunicorn │      │  naver.py   │      │  naver.py   │ │
│  └──────┬──────┘      └──────┬──────┘      └──────┬──────┘ │
│         │                    │                    │        │
│         └────────────────────┼────────────────────┘        │
│                              │                             │
│                              ▼                             │
│                    ┌─────────────────┐                     │
│                    │     MySQL       │                     │
│                    │    Service      │                     │
│                    │                 │                     │
│                    │  products 테이블 │                     │
│                    └─────────────────┘                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Procfile

```procfile
web: gunicorn api.main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
```

### 7.3 환경 변수

#### Web Service
| 변수 | 값 | 설명 |
|------|------|------|
| `NAVER_CLIENT_ID` | (API Key) | 네이버 API 클라이언트 ID |
| `NAVER_CLIENT_SECRET` | (API Secret) | 네이버 API 시크릿 |
| `SEARCH_KEYWORD` | 프리스타일 리브레2 | 검색 키워드 |

#### Cron Job Service
| 변수 | 값 | 설명 |
|------|------|------|
| `MYSQLHOST` | ${{ MySQL.MYSQLHOST }} | MySQL 호스트 |
| `MYSQLUSER` | ${{ MySQL.MYSQLUSER }} | MySQL 사용자 |
| `MYSQLPASSWORD` | ${{ MySQL.MYSQLPASSWORD }} | MySQL 비밀번호 |
| `MYSQLDATABASE` | ${{ MySQL.MYSQLDATABASE }} | MySQL 데이터베이스 |
| `MYSQLPORT` | ${{ MySQL.MYSQLPORT }} | MySQL 포트 |
| `NAVER_CLIENT_ID` | (API Key) | 네이버 API 클라이언트 ID |
| `NAVER_CLIENT_SECRET` | (API Secret) | 네이버 API 시크릿 |
| `ENABLE_DB_SAVE` | true | DB 저장 활성화 |

---

## 8. 기술 스택

### 8.1 백엔드
| 기술 | 버전 | 용도 |
|------|------|------|
| Python | 3.10+ | 메인 언어 |
| FastAPI | latest | REST API 프레임워크 |
| SQLAlchemy | latest | ORM / 데이터베이스 연결 |
| Gunicorn | latest | WSGI 서버 |
| Uvicorn | latest | ASGI 서버 |

### 8.2 데이터베이스
| 기술 | 버전 | 용도 |
|------|------|------|
| MySQL | 8.0 | 메인 데이터베이스 |
| PyMySQL | latest | Python MySQL 드라이버 |
| mysql-connector-python | latest | 크롤링 스크립트용 드라이버 |

### 8.3 크롤링
| 기술 | 용도 |
|------|------|
| 네이버 쇼핑 API | 상품 데이터 수집 |
| urllib | HTTP 요청 |
| re (정규표현식) | 상품명 분석 |

### 8.4 배포
| 플랫폼 | 서비스 |
|--------|--------|
| Railway | 백엔드 API, Cron Job, MySQL |
| Vercel | 프론트엔드 |
| GitHub | 소스 코드 관리 |

---

## 9. 데이터 흐름 요약

```
┌──────────────────────────────────────────────────────────────────────┐
│                          전체 데이터 흐름                             │
└──────────────────────────────────────────────────────────────────────┘

  [Cron Job]              [네이버 API]              [MySQL]
      │                        │                       │
      │  1. API 호출           │                       │
      │ ─────────────────────> │                       │
      │                        │                       │
      │  2. 상품 데이터 응답    │                       │
      │ <───────────────────── │                       │
      │                        │                       │
      │  3. 단가 계산 & 필터링                         │
      │  ┌─────────────────────┐                       │
      │  │ analyze_product()   │                       │
      │  │ - 수량 추출         │                       │
      │  │ - 단가 계산         │                       │
      │  │ - 유효성 검증       │                       │
      │  └─────────────────────┘                       │
      │                                                │
      │  4. DB 저장                                    │
      │ ──────────────────────────────────────────────>│
      │                                                │

  [프론트엔드]            [FastAPI]                 [MySQL]
      │                        │                       │
      │  5. GET /products/latest                       │
      │ ─────────────────────> │                       │
      │                        │                       │
      │                        │  6. SELECT * FROM products
      │                        │ ─────────────────────>│
      │                        │                       │
      │                        │  7. 데이터 응답       │
      │                        │ <─────────────────────│
      │                        │                       │
      │  8. JSON 응답          │                       │
      │ <───────────────────── │                       │
      │                        │                       │
```

---

## 10. 결론

### 10.1 시스템 특징
- **자동화**: 매일 2회 자동 크롤링으로 최신 가격 유지
- **정확성**: 다단계 단가 계산 로직으로 정확한 개당 가격 제공
- **확장성**: 채널/마켓 필드 추가로 쿠팡 등 타 플랫폼 확장 가능
- **안정성**: Railway 기반 24/7 서비스 운영

### 10.2 향후 개선 사항
1. 쿠팡 크롤링 추가 (셀레니움 기반)
2. 가격 변동 알림 기능
3. 가격 추이 그래프 데이터 API
4. S3 연동 상품 카드 이미지 저장

---

*보고서 작성일: 2026년 2월 5일*
