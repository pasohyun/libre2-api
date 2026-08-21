# Libre2 Price Monitoring API

프리스타일 리브레2(FreeStyle Libre 2) **온라인 판매가 모니터링 백엔드**입니다.
네이버 쇼핑 / 쿠팡 브랜드스토어를 정기 크롤링해 판매처별 **단가(센서 1개당 가격)** 를 산출·저장하고,
대시보드용 조회 API·리포트·기준가 미준수 알림 메일을 제공합니다.

> **프론트엔드는 별도 저장소입니다** → `libre-price-monitor-client` (React 19 + Vite, Vercel 배포)
> 이 저장소는 API 서버 + 크롤러 + 배치 스크립트만 포함합니다.

---

## 목차

1. [시스템 구성](#1-시스템-구성)
2. [기술 스택](#2-기술-스택)
3. [저장소 · 배포 토폴로지](#3-저장소--배포-토폴로지)
4. [디렉토리 구조 (파일별 역할)](#4-디렉토리-구조-파일별-역할)
5. [데이터 흐름](#5-데이터-흐름)
6. [데이터베이스 스키마](#6-데이터베이스-스키마)
7. [API 엔드포인트](#7-api-엔드포인트)
8. [환경 변수](#8-환경-변수)
9. [로컬 개발](#9-로컬-개발)
10. [Railway 배포 (web · 네이버 크롤러)](#10-railway-배포-web--네이버-크롤러)
11. [쿠팡 크롤러 운영 (회사 서버)](#11-쿠팡-크롤러-운영-회사-서버)
12. [운영 가이드 · 트러블슈팅](#12-운영-가이드--트러블슈팅)
13. [인수인계 체크리스트](#13-인수인계-체크리스트)

---

## 1. 시스템 구성

```
                                  ┌────────────────────────┐
   네이버 쇼핑 오픈API  ──────────▶│  scripts/crawl_naver   │
   (Railway Cron)                 └───────────┬────────────┘
                                              │  analyze_product() → 단가 산출
                                              │  save_to_db()      → 스냅샷 저장
   쿠팡 브랜드스토어(21곳)         ┌───────────▼────────────┐
   Playwright + Bright Data ─────▶│  MySQL (products 외 5) │
   (회사 서버 crontab)             └───────────┬────────────┘
   scripts/crawl_coupang_brand                │
                                  ┌───────────▼────────────┐        ┌──────────────┐
                                  │  FastAPI (api/)        │◀──────▶│  React 대시보드│
                                  │  JWT 인증 · 조회/리포트 │  CORS  │   (Vercel)   │
                                  └───────────┬────────────┘        └──────────────┘
                                              │
                          ┌───────────────────┼───────────────────┐
                          ▼                   ▼                   ▼
                    S3 (증빙 카드)      SMTP (일일 알림)     OpenAI (리포트 요약, 선택)
```

**핵심 개념 — 스냅샷(snapshot)**
크롤링 1회 = 스냅샷 1개. 모든 행에 `snapshot_id`(UUID) + `snapshot_at`이 찍힙니다.
"최신 데이터"란 곧 "가장 최근 snapshot_id의 행 집합"이며, 네이버와 쿠팡은 **채널별로 각각 최신 스냅샷**을 잡아 합칩니다.

**핵심 개념 — 단가**
판매처마다 구성(1/2/3/7개입)이 달라 총가격 비교가 무의미하므로, 상품명에서 수량을 파싱해
`단가 = 총가격 ÷ 수량`으로 정규화합니다. 이 로직이 `scripts/crawl_naver.py`의 `analyze_product()`이며,
쿠팡 크롤러도 저장 시 동일 함수를 재사용합니다. **모니터링 지표는 전부 단가 기준입니다.**

**크롤링 주기**: 매일 **03:00 / 06:00 / 09:00 / 15:00 / 18:00 / 21:00 KST (하루 6회)**
네이버는 Railway Cron Job, 쿠팡은 회사 서버 crontab에서 각각 같은 시각에 실행됩니다.

---

## 2. 기술 스택

| 구분 | 사용 기술 |
|------|-----------|
| 언어 / 런타임 | Python 3.11 (`runtime.txt`) |
| 웹 프레임워크 | FastAPI + Uvicorn (gunicorn UvicornWorker로 서빙) |
| DB | MySQL 8.x, SQLAlchemy(Core 위주 raw SQL) + PyMySQL / mysql-connector |
| 크롤링 | 네이버 쇼핑 **오픈 API**(HTTP), 쿠팡 **Playwright + Bright Data Scraping Browser** |
| 인증 | 공유 비밀번호 → JWT(HS256, 만료 1일) |
| 저장소/알림 | AWS S3(증빙 카드 PNG), SMTP(일일 알림 메일), OpenAI Responses API(리포트 요약, 선택) |
| 분석 | numpy · statsmodels (MAD 이상탐지, Holt/OLS 단기예측) |
| 배포 | Railway(web · 네이버 크롤러) / 회사 서버 crontab(쿠팡 크롤러) |

> ⚠️ `requirements.txt`에는 **버전이 고정되어 있지 않습니다.** 재설치 시점에 따라 FastAPI·Pydantic 메이저 버전이
> 바뀔 수 있으므로, 운영 서버에서 `pip freeze > requirements.lock.txt`로 현재 버전을 남겨두길 권장합니다.

---

## 3. 저장소 · 배포 토폴로지

인수인계 시 **가장 혼동되는 부분**이므로 먼저 읽어주세요.

### Git 리모트 3종

| 리모트 | 주소 | 역할 |
|--------|------|------|
| `origin` / `github` | github.com/pasohyun/libre2-api | **실질 소스. `main`이 항상 최신** |
| `gitlab` | gitlab.daewoong.co.kr/…/libre-2-price-monitor | 사내 보안 스캔용. **`main`은 빈 basic-template**이라 실제 코드 없음. protected라 직접 push 불가(MR 필요) |
| `gitlab` 브랜치 `feat/server-test` | — | **회사 서버에 실제로 체크아웃되어 있는 브랜치** |

### 실행 주체

| 실행 대상 | 위치 | 방식 |
|-----------|------|------|
| API 서버 (`web`) | Railway | `Procfile` → `gunicorn api.main:app -k UvicornWorker --workers 1` |
| 네이버 크롤러 | Railway Cron Job | `python -m scripts.crawl_naver` (하루 6회) |
| **쿠팡 브랜드 크롤러** | **회사 서버 crontab** | `0 3,6,9,15,18,21` KST → `.venv/bin/python -m scripts.crawl_coupang_brand` |
| DB (MySQL) | Railway MySQL | 네이버·쿠팡 공용 |
| 프론트엔드 | Vercel | 별도 저장소 |

> ⚠️ **회사 서버는 사내 GitLab을 바라보는 클론이고, cron이 working-tree 파일을 직접 실행합니다(브랜치 무관).**
> GitHub `main`에 올린 수정은 서버에 자동 반영되지 않습니다. 반영하려면 `feat/server-test`에서
> 서버 로컬 수정을 먼저 커밋한 뒤 `git fetch origin && git cherry-pick <main 커밋>` 순서로 진행하세요.
> **`git pull`로 덮어쓰면 서버 전용 수정이 사라집니다.**

> ⚠️ **크롤러 공용 로직 주의**: `scripts/crawl_coupang_brand.py`는 `scripts/crawl_naver.py`의
> `analyze_product`, `save_to_db`, `NON_LIBRE_CGM_EXCLUDE_PATTERNS`, `load_confirmed_qty_by_link_map`을
> 그대로 import해 씁니다. 즉 **단가 계산·수량 추론·제외 키워드는 네이버와 쿠팡 공용**이며,
> 한쪽에만 반영하면 채널 간 단가가 어긋납니다.

---

## 4. 디렉토리 구조 (파일별 역할)

```
libre2-api/
├── api/            # FastAPI 애플리케이션
├── scripts/        # 크롤러 및 배치 CLI
├── config.py       # 환경변수 로딩 단일 창구
└── (배포/문서 파일)
```

### 4.1 `api/` — FastAPI 애플리케이션

| 파일 | 역할 |
|------|------|
| `main.py` | 앱 진입점. `lifespan`에서 `init_db()` + `scheduler.start()` 실행, CORS 설정(localhost·`*.vercel.app` 허용), 라우터 등록. **`health`·`auth_dashboard`를 제외한 전 라우터에 JWT 의존성을 일괄 부착**한다. `POST /crawl/trigger`도 여기에 정의. |
| `database.py` | SQLAlchemy 엔진·`SessionLocal` 생성. `init_db()`가 테이블 6개를 `CREATE TABLE IF NOT EXISTS`로 자동 생성하고, `_safe_alter()`로 컬럼/인덱스 추가를 **멱등하게** 처리(이미 있으면 무시). 기동 시 판매처명 일괄 정규화(`_normalize_mall_names`)와 월간 집계 판매처명 병합(`_merge_monthly_metrics_seller_rename`)도 수행. **마이그레이션 도구 없이 이 파일이 스키마 관리 역할**을 한다. |
| `auth_dashboard.py` | 대시보드 공유 비밀번호 검증 + JWT(HS256, 유효기간 1일) 발급/검증. `require_dashboard_auth`가 전 라우터의 의존성. `DASHBOARD_AUTH_ENABLED=false`로 인증 우회 가능(로컬 전용). |
| `scheduler.py` | 앱 내장 스케줄러. **기본 비활성(`ENABLE_SCHEDULER=false`)** — gunicorn 멀티 워커에서 중복 실행을 막기 위함. 활성 시 `CRAWL_TIMES_KST`(기본 03/06/09/15/18/21시) 크롤링과 `ALERT_SEND_TIME_KST`(기본 09:00) 알림 메일을 등록한다. KST→UTC 변환 후 등록하는 점 주의. ⚠️ 켜면 **구버전 쿠팡 크롤러(`crawl_coupang_urls.py`)까지 함께 돌아 중복 수집**이 발생한다. |
| `schemas.py` | Pydantic 요청/응답 모델 전체. |

#### `api/routers/`

| 파일 | 역할 |
|------|------|
| `health.py` | `GET /health`(서버 시각), `GET /health/db`(DB 도달 여부·products 행 수·snapshot_id 보유 행 수). **인증 불필요** — 데이터가 안 보일 때 1차 진단용. |
| `auth_dashboard.py` | `POST /auth/dashboard/login` — 공유 비밀번호를 받아 JWT 발급. |
| `products.py` | ★ **가장 큰 파일(약 1,380줄)**. 대시보드가 쓰는 거의 모든 조회 API. 최신/당일 스냅샷 조회, 최저가, 판매처 통계·랭킹, 기준가 미만 조회, 주요 판매처 요약·추이, 판매처 타임라인, 가격 인사이트(이상탐지/예측), 크롤링 수동 실행·상태, 증빙 카드 생성, 수동 확정, 행 삭제, 원본 엑셀 Export. 판매처명 표준화 헬퍼도 이 파일에 포함. |
| `reports.py` | 월간 리포트(`/reports/monthly/{month}`) · 기간 리포트(`/reports/range`)를 JSON과 Markdown 두 형태로 제공. |
| `memos.py` | 운영 메모(global) / 업체별 메모(vendor) CRUD + 이미지 업로드(S3). 업체별 메모 집계 조회 포함. 사용법은 `MEMO_FEATURE_USER_GUIDE.md` 참고. |
| `alerts.py` | 알림 설정 조회/수정(`GET·PUT /alerts/config`)과 수동 발송 트리거(`POST /alerts/trigger`). 실제 로직은 `services/daily_alerts.py`에 위임. |

#### `api/services/`

| 파일 | 역할 |
|------|------|
| `daily_alerts.py` | ★ **일일 알림 전체 파이프라인**(약 26KB). 설정 로드 → 전일 기준가 미만 판매처 집계 → 메일 본문 HTML + 리포트 이미지(PNG) 생성 → SMTP 발송 → `alert_delivery_logs`에 기록. |
| `price_analytics.py` | 판매처별 최저 단가 시계열에 대해 **MAD 기반 modified z-score 이상탐지** + **Holt 지수평활/OLS 단기예측**. `products.py`의 `/mall/price-insights`가 사용. 임계값은 `PRICE_ANALYTICS_*` 환경변수로 조정. |
| `monthly_metrics.py` | 월간 판매처 집계 계산 · `monthly_seller_metrics` upsert · 조회. |
| `monthly_report_builder.py` | 월간 리포트 데이터 조립 + Markdown 렌더. |
| `range_metrics.py` | 임의 기간 집계(요약 / 미준수 상세 / 차트 데이터). |
| `range_report_builder.py` | 기간 리포트 조립 + Markdown 렌더. |
| `card_renderer.py` | Playwright로 HTML 카드를 PNG로 렌더(증빙 캡처). 카드에는 생성시각(KST)·단가·총가격·수량·판매처·링크가 들어간다. |
| `s3_storage.py` | S3 업로드, object key 추출, presigned URL 생성. `ENABLE_S3_UPLOAD=false`면 전 기능 no-op. |
| `coupang_remote.py` | paramiko SSH로 **회사 서버의 쿠팡 크롤러를 fire-and-forget 실행**. 대시보드 수동 크롤링 버튼용. 로그는 `coupang_manual.log`로 분리되며, `COUPANG_SSH_HOST`/`USER`/`PASSWORD`가 모두 설정되어 있지 않으면 에러 없이 `skipped`를 반환한다. |
| `openai_reports.py` | OpenAI Responses API 호출로 리포트 요약문 생성. **`OPENAI_API_KEY`가 없으면 `None`을 반환하고 조용히 스킵** — 키 없이도 리포트는 정상 동작. |

### 4.2 `scripts/` — 크롤러 및 배치 CLI

| 파일 | 상태 | 역할 |
|------|------|------|
| `crawl_naver.py` | ★**핵심·현행** | 네이버 쇼핑 오픈 API 크롤링. 리브레2 상품 판별(포함/제외 정규식), `analyze_product()`로 수량 파싱·**단가 산출**, `save_to_db()`로 스냅샷 저장, 증빙 카드 렌더 + S3 업로드 후처리. **여러 함수를 쿠팡 크롤러가 import해 쓰는 공용 모듈**이므로 수정 시 양쪽 영향 확인 필수. 판매처명 정규화 맵(`MALL_NAME_NORMALIZE_MAP`)도 여기 있다. |
| `crawl_coupang_brand.py` | ★**현행** | 쿠팡 브랜드스토어 크롤러. Playwright + Bright Data(프록시 또는 Scraping Browser WSS)로 `BRAND_STORES`에 정의된 **브랜드스토어 21곳**을 배치 순회. 스토어별 `min_price`·`name_filter` 지정 가능. 봇 차단(Access Denied)·navigation 에러 시 **스토어당 최대 3회 재시도**, 전멸 시 브라우저를 새 IP로 재연결 후 재시도. 시작 시 `.env`와 `proxy.env`를 모두 로드. |
| `crawl_coupang_urls.py` | 구버전(일부 사용) | URL 목록(`COUPANG_URLS_FILE`) 기반 쿠팡 크롤러. **내장 스케줄러(`api/scheduler.py`)가 아직 이 스크립트를 호출**하므로 완전 사용중지 상태는 아니다. |
| `crawl_coupang.py` | 구버전(미사용) | 검색어 기반 쿠팡 크롤러. 현재 호출처 없음. |
| `cleanup_non_libre_products.py` | 유지보수 | 리브레2가 아닌 상품이 섞여 들어온 경우 DB에서 정리. |
| `generate_monthly_report.py` | CLI | 월간 리포트 생성(스케줄 외 수동 실행용). |
| `render_evidence_card.py` | CLI | 증빙 카드 단독 렌더(Playwright). 카드 디자인 확인·디버깅용. |
| `add_columns.py` | 일회성 | 과거 스키마 보정 스크립트. 현재는 `database.py`의 `_safe_alter()`가 대체. |
| `update_db_schema.py` | 일회성 | 상동. |
| `update_railway_db.py` | 일회성 | Railway DB 대상 스키마 보정. |
| `test_api.py` | 테스트 | API 스모크 테스트(정식 테스트 스위트 아님). |

### 4.3 루트 파일

| 파일 | 역할 |
|------|------|
| `config.py` | **모든 환경변수를 읽는 단일 창구.** DB 접속정보는 Railway 변수(`MYSQLHOST` 등) → 일반 변수(`DB_HOST` 등) 순으로 fallback. 기능 토글(`ENABLE_*`), S3/네이버/쿠팡 설정, `TARGET_PRICE`(기준가, 기본 90,000), `TRACKED_MALLS` 등. 값 검증은 사용 시점에 수행. |
| `Procfile` | Railway web 프로세스: `gunicorn api.main:app --workers 1 -k uvicorn.workers.UvicornWorker`. **워커 1개 고정**(내장 스케줄러/크롤 락이 프로세스 내 전역 상태를 쓰기 때문). |
| `nixpacks.toml` | Railway 빌드 시 Playwright/Chromium 실행에 필요한 apt 패키지(폰트 포함) 설치 + `playwright install chromium`. 증빙 카드 렌더가 Railway에서 동작하려면 필수. |
| `runtime.txt` | `python-3.11` |
| `requirements.txt` | 의존성 목록(버전 미고정). 섹션별 주석으로 용도 구분. |
| `Dockerfile.coupang` | 쿠팡 크롤러 전용 이미지(`mcr.microsoft.com/playwright/python`). 기본 CMD가 `scripts.crawl_coupang_brand`. |
| `.env.example` | 환경변수 템플릿(키만, 값 없음). `cp .env.example .env` 후 채워 사용. |
| `.gitlab-ci.yml` | gitleaks 시크릿 스캔 파이프라인. **실패 시 머지 차단.** |
| `.gitleaks.toml` | 시크릿 스캔 예외 규칙. |
| `.env`, `proxy.env` | 실제 시크릿. **`.gitignore`의 `*.env` 패턴으로 커밋 차단됨.** `proxy.env`에는 Bright Data 크리덴셜이 들어간다. |
| `test_browser.py` | Playwright/프록시 연결이 되는지 확인하는 단발 점검 스크립트. |
| `scheduler.log`, `scheduler_output.log` | 과거 내장 스케줄러 실행 로그(저장소에 커밋된 상태). 참고용이며 최신 운영 로그가 아님. |

### 4.4 문서

| 파일 | 내용 |
|------|------|
| `README.md` | 본 문서. 구조·배포·운영 전반. |
| `TECHNICAL_REPORT.md` | 기술 보고서. |
| `MEMO_FEATURE_USER_GUIDE.md` | 메모 기능 현업 사용 가이드. |
| `RESULT_REPORT_MAIN_DASHBOARD_NAVER.md` | 네이버 대시보드 결과 보고서. |
| `PROJECT_SCHEDULE.md` | 프로젝트 일정. |
| `README_gitlab_template.md` | 사내 GitLab 시크릿 관리 템플릿 원문(이 프로젝트 고유 내용 아님). |

---

## 5. 데이터 흐름

**① 수집** — 크롤러가 채널별로 상품을 수집
→ 리브레2 여부 판별(포함 패턴 / 비-리브레2 CGM 제외 패턴 / 차단 키워드)
→ `analyze_product()`가 상품명에서 수량을 파싱해 **단가** 계산
→ `save_to_db()`가 `snapshot_id` + `snapshot_at`을 부여해 `products`에 INSERT

**② 후처리** — `ENABLE_CARD_RENDER=true`면 증빙 카드 PNG 렌더 → `ENABLE_S3_UPLOAD=true`면 S3 업로드, 경로를 행에 기록

**③ 조회** — 대시보드가 JWT를 붙여 `/products/*` 호출
→ 네이버(`market != 쿠팡`)와 쿠팡(`market = 쿠팡`)의 **최신 스냅샷을 각각** 잡아 합쳐서 응답

**④ 알림** — 매일 지정 시각에 전일 기준 `단가 < TARGET_PRICE` 판매처를 집계 → 메일 발송 → 발송 로그 기록

---

## 6. 데이터베이스 스키마

`init_db()`(`api/database.py`)가 기동 시 자동 생성합니다. 별도 마이그레이션 도구를 쓰지 않습니다.

| 테이블 | 용도 |
|--------|------|
| `products` | 크롤링 원본 스냅샷. 상품명·판매처·총가격·수량·**단가**·링크·이미지·`snapshot_id`·`snapshot_at`·`calc_valid`·`channel`·`market` |
| `monthly_seller_metrics` | 월간 판매처 집계(리포트용, upsert) |
| `dashboard_memos` | 운영/업체 메모 + 이미지 경로(`image_path`, `image_paths` JSON) |
| `monthly_reports` | 생성된 월간 리포트 저장 |
| `alert_settings` | 알림 on/off·수신자 목록·임계 가격 |
| `alert_delivery_logs` | 알림 발송 이력 |

주요 인덱스: `idx_snapshot_at`, `idx_snapshot_id` (둘 다 `products`).

> 컬럼 추가가 필요하면 `init_db()` 안에 `_safe_alter(conn, "ALTER TABLE ... ADD COLUMN ...")` 한 줄을 추가하면 됩니다.
> 이미 존재하는 경우 예외를 삼키므로 재기동해도 안전합니다.

> ⚠️ 테이블명은 `DB_TABLE` 환경변수로 덮어쓸 수 있지만 **크롤러 스크립트만 이 값을 사용하고 API는 `products`를
> 하드코딩**합니다. 기본값에서 변경하지 마세요.

---

## 7. API 엔드포인트

`GET /docs`(Swagger UI)에서 전체 스펙을 확인할 수 있습니다.
**`/health*`와 `/auth/dashboard/login`을 제외한 모든 엔드포인트는 `Authorization: Bearer <JWT>` 필요.**

### 인증 · 헬스

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/` | API 정보 |
| GET | `/health` | 서버 상태 (인증 불필요) |
| GET | `/health/db` | DB 연결 · 데이터 적재 상태 진단 (인증 불필요) |
| POST | `/auth/dashboard/login` | 공유 비밀번호 → JWT 발급 |
| POST | `/crawl/trigger` | 내장 스케줄러 크롤링 즉시 실행 |

### 상품 (`/products`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/latest` | 최신 스냅샷(네이버·쿠팡 각각 최신을 합침) — **대시보드 메인이 사용** |
| GET | `/today` | 당일 데이터 |
| GET | `/lowest` | 최저가 상품 |
| GET | `/below-target` | 기준가 이하 목록 ⚠️ 채널 구분 없이 전체 최신 스냅샷 1개만 잡음(아래 주의사항 참고) |
| GET | `/malls/stats` · `/malls/top` | 판매처 통계 · 상위 판매처 |
| GET | `/tracked-malls/summary` · `/tracked-malls/trends` | 주요 판매처 요약 · 추이 |
| GET | `/mall/timeline` | 판매처별 수집 타임라인(증빙 포함) |
| GET | `/mall/price-insights` | 이상탐지 + 단기 예측 |
| GET | `/config` | 기준가 등 프론트 노출용 설정 |
| GET | `/export/raw` | 원본 데이터 엑셀 다운로드 |
| POST | `/crawl/run` · GET `/crawl/status` | 수동 크롤링 실행 / 상태 조회 |
| POST | `/card/generate` | 증빙 카드 단건 생성 |
| POST | `/manual-confirm` | 수동 확정 처리 |
| POST | `/delete` | 행 삭제 |

### 리포트 · 메모 · 알림

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/reports/monthly/{month}` · `/reports/monthly/{month}/markdown` | 월간 리포트 |
| GET | `/reports/range` · `/reports/range/markdown` | 기간 리포트 |
| GET/POST | `/memos/global` · `/memos/vendor` | 운영/업체 메모 조회·작성 |
| GET | `/memos/vendors/aggregate` | 업체별 메모 집계 |
| PATCH/DELETE | `/memos/{memo_id}` | 메모 수정·삭제 |
| POST | `/memos/upload-image` | 메모 이미지 업로드(S3) |
| GET/PUT | `/alerts/config` | 알림 설정 조회·수정 |
| POST | `/alerts/trigger` | 알림 메일 수동 발송 |

---

## 8. 환경 변수

전체 목록은 `.env.example`과 `config.py`를 참고하세요. 아래는 **동작에 반드시 필요한 것** 위주입니다.

### 필수

```bash
# DB (Railway는 MYSQL* 변수가 자동 주입되며 이쪽이 우선)
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=daewoong

# 네이버 오픈 API
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=

# 대시보드 인증
DASHBOARD_PASSWORD=          # 미설정 시 기본값 사용 — 운영에서는 반드시 설정
JWT_SECRET=                  # 미설정 시 개발용 기본키로 동작하며 경고 발생 — 운영 필수
```

> ⚠️ **`ENABLE_DB_SAVE`는 무효한 변수입니다.** `config.py`에 정의만 되어 있고 이를 읽는 코드가 없으므로
> 설정해도 아무 효과가 없습니다. DB 저장은 `MYSQL*`(또는 `DB_*`) 접속 정보만 있으면 동작합니다.

### 기능 토글 (실제로 동작하는 것)

| 변수 | 기본 | 설명 |
|------|------|------|
| `ENABLE_CARD_RENDER` | false | 증빙 카드 PNG 렌더. false면 `/products/card/generate`도 400 반환 |
| `ENABLE_AUTO_CARD_RENDER` | true | false면 크롤링 중 자동 카드 생성만 건너뛰고 API 단건 생성은 허용 |
| `ENABLE_S3_UPLOAD` | false | S3 업로드. false면 `s3_storage` 전 기능 no-op |
| `ENABLE_SCHEDULER` | false | 앱 내장 스케줄러. ⚠️ 켜면 구버전 쿠팡 크롤러까지 돌아 중복 수집 주의 |
| `DASHBOARD_AUTH_ENABLED` | true | false면 인증 우회(로컬 전용) |

### 그 외 주요 그룹

| 그룹 | 변수 |
|------|------|
| 기준가·대상 | `TARGET_PRICE`(기본 90000), `TRACKED_MALLS`(쉼표 구분), `SEARCH_KEYWORD` |
| S3 | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`, `S3_PREFIX`, `S3_PUBLIC_BASE_URL`, `S3_ENDPOINT_URL`, `S3_UPLOAD_MAX_PER_RUN`(0 이하면 전량) |
| 알림 메일 | `ALERT_SMTP_HOST/PORT/USER/PASSWORD/USE_TLS`, `ALERT_SEND_TIME_KST`, `ALERT_DASHBOARD_URL`, `ALERT_REPORT_FONT_PATH` |
| 스케줄 | `CRAWL_TIMES_KST`(기본 `03:00,06:00,09:00,15:00,18:00,21:00`) |
| 쿠팡 프록시 | `BRIGHT_DATA_PROXY`, `BRIGHT_DATA_USERNAME`, `BRIGHT_DATA_PASSWORD`, `BRIGHT_DATA_BROWSER_WSS` (→ `proxy.env`) |
| 쿠팡 SSH 트리거 | `COUPANG_SSH_HOST/PORT/USER/PASSWORD/WORKDIR/PYTHON/MODULE` |
| 분석 튜닝 | `PRICE_ANALYTICS_*` (베이스라인 일수, modified z 임계값, ETS/OLS 구간 등) |
| OpenAI(선택) | `OPENAI_API_KEY`, `OPENAI_MODEL` — 없으면 요약만 생략되고 리포트는 정상 |

> 🔒 `.env`·`proxy.env`는 절대 커밋하지 마세요. GitLab CI의 gitleaks가 검출 시 머지를 차단합니다.

---

## 9. 로컬 개발

```bash
# 1) 가상환경
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2) 의존성
pip install -r requirements.txt
python -m playwright install chromium   # 카드 렌더 / 쿠팡 크롤러를 쓸 때만

# 3) 환경변수
cp .env.example .env                    # 값 채우기

# 4) API 서버
uvicorn api.main:app --reload           # http://127.0.0.1:8000/docs

# 5) 크롤링 수동 실행
python -m scripts.crawl_naver
python -m scripts.crawl_coupang_brand   # Bright Data 크리덴셜(proxy.env) 필요
```

**동작 확인 순서**: `GET /health` → `GET /health/db`(products_rows·rows_with_snapshot_id 확인)
→ `POST /auth/dashboard/login`으로 토큰 발급 → `GET /products/latest`.

프론트엔드를 함께 띄우려면 `libre-price-monitor-client`에서 `npm install && npm run dev`(Vite, 5173 포트).
5173과 3000은 `main.py`의 CORS 허용 목록에 이미 포함되어 있습니다.

---

## 10. Railway 배포 (web · 네이버 크롤러)

Railway에는 **3개 서비스**가 있습니다. 쿠팡 크롤러는 여기 없습니다([11장](#11-쿠팡-크롤러-운영-회사-서버) 참고).

- **`web`**: FastAPI 서버 (24/7 실행)
- **`Cron Job (네이버)`**: 하루 6회 네이버 자동 크롤링
- **`MySQL`**: 데이터베이스 서비스

### 10.1 MySQL 서비스

Railway 프로젝트 → **+ New** → **Database** → **MySQL**. 생성되면 `MYSQL*` 변수가 자동 제공됩니다.

### 10.2 Web 서비스

1. GitHub 저장소 연결 → Railway가 `Procfile`의 `web` 명령으로 자동 배포
2. **Variables** 탭에서 환경 변수 설정 ([8장](#8-환경-변수) 참고)

### 10.3 네이버 Cron Job 서비스

1. **+ New** → **Cron Job**
2. **Schedule**: `0 0,6,9,12,18,21 * * *`
   - ⚠️ Railway Cron은 **UTC 기준**입니다. 위 식은 KST 03:00 / 06:00 / 09:00 / 15:00 / 18:00 / 21:00에 해당합니다 (KST = UTC + 9).
3. **Command**: `python -m scripts.crawl_naver`
4. **Variables**:
   - `MYSQLHOST = ${{ MySQL.MYSQLHOST }}`
   - `MYSQLUSER = ${{ MySQL.MYSQLUSER }}`
   - `MYSQLPASSWORD = ${{ MySQL.MYSQLPASSWORD }}`
   - `MYSQLDATABASE = ${{ MySQL.MYSQLDATABASE }}`
   - `MYSQLPORT = ${{ MySQL.MYSQLPORT }}`
   - `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `SEARCH_KEYWORD`

> **참고**: Variables에서 MySQL 서비스를 참조하는 변수를 추가하면 Architecture 탭에 자동으로 연결선이 생깁니다.
> Railway Cron Job은 스케줄 시각에 컨테이너를 시작하고 작업 완료 후 종료합니다.

---

## 11. 쿠팡 크롤러 운영 (회사 서버)

쿠팡은 Cloudflare/Akamai 계열 anti-bot 때문에 Bright Data Scraping Browser(원격 Chrome + 한국 주거용 프록시)를
경유해야 해서, Railway가 아닌 **회사 서버 crontab**에서 실행합니다. 수집 결과는 네이버와 동일한 Railway MySQL에 저장됩니다.

서버의 클론은 사내 GitLab을 바라보므로, 코드 수정 시 GitHub와 GitLab **양쪽에 반영**해야 합니다
(절차는 [3장](#3-저장소--배포-토폴로지) 참고).

### 11.1 환경 구성

```bash
cd /home/develop/daewoong/libre2-monitor/libre2-api
python3 -m venv .venv
. .venv/bin/activate   # 서버 기본 셸이 sh이므로 source 대신 . 사용
pip install -r requirements.txt
playwright install chromium
```

### 11.2 환경변수 파일 (git 제외 — `.gitignore`의 `*.env` 패턴)

- `.env`: `MYSQLHOST` / `MYSQLPORT` / `MYSQLUSER` / `MYSQLPASSWORD` / `MYSQLDATABASE`, `SEARCH_KEYWORD`
- `proxy.env`: `BRIGHT_DATA_PROXY` / `BRIGHT_DATA_USERNAME` / `BRIGHT_DATA_PASSWORD` / `BRIGHT_DATA_BROWSER_WSS`

`crawl_coupang_brand.py`는 시작 시 `.env`와 `proxy.env`를 모두 로드합니다.
(AWS·S3 키는 쿠팡 크롤러에서 사용하지 않으므로 서버에 둘 필요가 없습니다.)

### 11.3 실행 및 스케줄

```bash
python -m scripts.crawl_coupang_brand
```

crontab (하루 6회, 서버 시간대 KST 기준):

```
0 3,6,9,15,18,21 * * * cd /home/develop/daewoong/libre2-monitor/libre2-api && .venv/bin/python -m scripts.crawl_coupang_brand >> coupang_cron.log 2>&1
```

로그 확인: `tail -f coupang_cron.log` (성공 시 `DB inserted: N개` 출력)

### 11.4 대시보드 수동 크롤링 버튼

`POST /products/crawl/run`으로 들어와, 쿠팡의 경우 `api/services/coupang_remote.py`가 `COUPANG_SSH_*`
환경변수로 이 서버에 SSH 접속해 같은 명령을 백그라운드 실행합니다(로그는 `coupang_manual.log`로 분리).
`COUPANG_SSH_HOST` / `USER` / `PASSWORD`가 모두 설정되어 있지 않으면 에러 없이 `skipped`로 넘어갑니다.
사내망 전용이므로 호출자가 회사 와이파이/VPN에 연결되어 있어야 합니다.

### 11.5 크롤링 대상 브랜드 스토어

`scripts/crawl_coupang_brand.py`의 `BRAND_STORES` 리스트(현재 **21곳**)에 스토어별 URL, 최소가 필터(`min_price`),
상품명 필터(`name_filter`)가 정의되어 있습니다. 신규 브랜드는 이 리스트에 항목만 추가하면 됩니다.

### 11.6 트러블슈팅

| 증상 | 확인 사항 |
| --- | --- |
| Access Denied | `proxy.env` 크리덴셜, Bright Data Zone 활성 상태 및 잔여 크레딧 |
| WSS 연결 실패 | 내장 재시도(3회) 대기, Scraping Browser Zone 활성 여부, `brd.superproxy.io:9222` 아웃바운드 허용 |
| DB 저장 안 됨 (inserted: 0) | `.env`의 `MYSQL*` 5개 값, Railway MySQL 서비스 running 상태 |

---

## 12. 운영 가이드 · 트러블슈팅

### 데이터가 안 보일 때

1. `GET /health/db` 호출 — `products_rows=0`이면 크롤 데이터가 없거나 다른 DB를 보고 있는 것.
2. `rows_with_snapshot_id=0`이면 `/latest`가 빈 값을 반환합니다(최신 스냅샷 기준이므로).
3. DB 접속 정보(`MYSQL*` 또는 `DB_*`)가 올바른지 확인.

### 쿠팡 데이터가 들쭉날쭉할 때 (알려진 이슈)

쿠팡 봇 차단(Access Denied 인터스티셜 + 자동 리로드) 때문에 **실행마다 어느 스토어가 성공하는지 랜덤**입니다.
추출 중 페이지가 navigation 하면 `Page.evaluate: Execution context was destroyed`로 그 스토어가 통째로 누락되어,
스냅샷마다 판매처 구성이 달라집니다(비싼 셀러만 잡히면 "기준가 이하"가 0건이 되기도 함).

현재 완화 조치: 스토어당 최대 3회 재시도, 추출 직전 `networkidle` 대기, goto 타임아웃 40초, 전멸 시 새 IP로 브라우저 재연결.
**완전 해결은 아니므로 한 스냅샷만 보고 판단하지 말고 여러 스냅샷을 함께 확인**하세요.

### 회사 서버 cron이 조용히 멈췄을 때 (재발 이슈)

계정 **비밀번호 aging 만료**가 원인인 경우가 있었습니다.
증상은 "코드 변경 없이 어느 날 갑자기 크롤링이 멈추고, cron 로그조차 남지 않음"이며,
SSH는 인증까지 되지만 모든 명령이 `WARNING: Your password has expired...`로 거부됩니다.

- 조치: TTY로 SSH 접속하면 비밀번호 변경 프롬프트가 뜨므로 직접 갱신 → `.env`의 `COUPANG_SSH_PASSWORD`도 새 값으로 교체.
- 재발 방지: 관리자 권한으로 `chage -M -1 <계정>`.
- ⚠️ 쿠팡은 현재가만 노출하므로 **중단된 기간의 데이터는 소급 복구가 불가능**합니다.

### 알아둘 엔드포인트 동작 차이

`/products/latest`는 네이버와 쿠팡의 최신 스냅샷을 **각각** 잡아 합치지만,
`/products/below-target`은 **채널 구분 없이 전체 최신 스냅샷 1개**만 잡습니다.
→ 늦게 끝난 채널의 데이터만 남을 수 있습니다. 현재 이 백엔드에서 호출처가 없는 사실상 미사용 엔드포인트이지만,
프론트에서 사용하게 되면 `/latest`와 동일한 채널별 최신 방식으로 수정해야 합니다.

### 배포 시 주의

- `Procfile`의 `--workers 1`을 늘리지 마세요. 내장 스케줄러와 크롤 실행 락이 프로세스 내 전역 상태를 사용합니다.
- 회사 서버 반영은 [3장](#3-저장소--배포-토폴로지)의 cherry-pick 절차를 따르세요.
- Railway에서 카드 렌더를 쓰려면 `nixpacks.toml`이 적용되어야 합니다(Chromium 시스템 라이브러리 + 한글 폰트).

---

## 13. 인수인계 체크리스트

- [ ] GitHub `pasohyun/libre2-api` 접근 권한 (**실질 소스**)
- [ ] 사내 GitLab 프로젝트 접근 권한 (시크릿 스캔 CI + 서버 클론이 바라보는 곳)
- [ ] 회사 서버 SSH 계정 — 쿠팡 크롤러 cron이 도는 곳. 비밀번호 만료 정책 확인(`chage -l`)
- [ ] Railway 프로젝트(web · Cron Job · MySQL) 권한
- [ ] Vercel 프로젝트 권한 (프론트엔드)
- [ ] 시크릿 인수: 네이버 오픈 API 키, Bright Data 크리덴셜, AWS S3 키, SMTP 계정, `DASHBOARD_PASSWORD`, `JWT_SECRET`, (선택) OpenAI 키
- [ ] 운영 서버 `pip freeze` 결과 확보 — `requirements.txt`에 버전이 고정되어 있지 않음
- [ ] `TARGET_PRICE`(기준가)·`TRACKED_MALLS`(주요 판매처) 현재 값과 결정 배경 확인
- [ ] `crawl_coupang_brand.py`의 `BRAND_STORES` 목록 최신 여부 확인(판매처 추가/제외는 이 배열 수정)
