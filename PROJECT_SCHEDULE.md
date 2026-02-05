# 프로젝트 일정 및 진행 상황

## 1월 2주차

**주간 목표**: 백엔드 API 개발 및 크롤링 방안 수립

| 날짜 | 작업 | 상세 내용 | 완료도 |
|------|------|-----------|--------|
| 1/12 | 백엔드 API 명세 작성 | FastAPI 기반 REST API 설계, 엔드포인트 정의 (`/products/latest`, `/products/lowest`) | 100 |
| 1/12 | 크롤링 방안 모색 | 네이버 쇼핑 API 활용 방안 검토, 쿠팡 크롤링 차단 이슈로 네이버 API 선택 | 100 |
| 1/14 | 데이터베이스 스키마 설계 | MySQL 테이블 구조 설계 (products 테이블), channel/market 필드 추가 계획 | 100 |
| 1/14 | 환경 변수 통합 | `config.py`에서 모든 설정을 `import config`로 통일, 환경 변수 기반 설정 구조 구축 | 100 |

---

## 1월 3주차

**주간 목표**: 크롤링 구현 및 Railway 배포 준비

| 날짜 | 작업 | 상세 내용 | 완료도 |
|------|------|-----------|--------|
| 1/21 | 크롤링 코드 구현 | 네이버 쇼핑 API를 활용한 크롤링 스크립트 작성 (`crawl_naver.py`), 상품 분석 로직 구현 | 100 |
| 1/21 | 데이터베이스 연결 | SQLAlchemy를 사용한 MySQL 연결, `init_db()` 함수로 테이블 자동 생성 구현 | 100 |
| 1/21 | Railway 배포 설정 | Railway 프로젝트 생성, GitHub 연동, `Procfile` 작성 (web 서비스) | 100 |
| 1/21 | MySQL 서비스 연동 | Railway MySQL 서비스 추가, 환경 변수 자동 연결 설정 | 100 |
| 1/23 | DB 스키마 업데이트 | `channel`, `market` 필드 추가, 크롤링 스크립트에 해당 필드 저장 로직 추가 | 100 |
| 1/23 | API 엔드포인트 구현 | `/products/latest`, `/products/lowest` 엔드포인트 완성, CORS 설정 추가 | 100 |

---

## 1월 4주차

**주간 목표**: 자동 크롤링 설정 및 프론트엔드 연동

| 날짜 | 작업 | 상세 내용 | 완료도 |
|------|------|-----------|--------|
| 1/26 | Railway Cron Job 설정 | 매일 00:00 KST, 12:00 KST 자동 크롤링 스케줄 설정 | 100 |
| 1/26 | Cron Job 환경 변수 연결 | MySQL 서비스와 Cron Job 서비스 간 환경 변수 연결 (`MYSQLHOST`, `MYSQLUSER` 등) | 100 |
| 1/26 | 크롤링 테스트 및 디버깅 | Railway에서 크롤링 실행 테스트, 환경 변수 문제 해결, DB 연결 확인 | 100 |
| 1/28 | 프론트엔드 연동 | Vercel에 배포된 프론트엔드와 백엔드 API 연동, 실제 데이터 표시 확인 | 100 |
| 1/28 | 자동 크롤링 검증 | 스케줄된 시간에 크롤링 정상 실행 확인, 567개 상품 데이터 수집 및 저장 성공 | 100 |
| 1/28 | 문서화 및 협업 준비 | README 업데이트, 프로젝트 구조 설명, 협업 가이드 작성 | 100 |

---

## 주요 성과

- ✅ **백엔드 API**: FastAPI 기반 REST API 완성, Railway에 배포 완료
- ✅ **크롤링 시스템**: 네이버 쇼핑 API를 활용한 자동 크롤링 구현
- ✅ **데이터베이스**: MySQL 기반 데이터 저장, 자동 스키마 생성
- ✅ **자동화**: Railway Cron Job을 활용한 매일 2회 자동 크롤링 설정
- ✅ **프론트엔드 연동**: Vercel 배포 프론트엔드와 백엔드 API 연동 완료
- ✅ **배포 인프라**: Railway를 활용한 완전 자동화된 배포 시스템 구축

---

## 기술 스택

- **Backend**: FastAPI, SQLAlchemy, MySQL
- **Crawling**: 네이버 쇼핑 API
- **Deployment**: Railway (Web Service + Cron Job)
- **Frontend**: React (Vercel 배포)
- **Database**: MySQL (Railway Managed)
