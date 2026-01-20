# Libre2 Price Monitoring API

프리스타일 리브레2 가격 모니터링 API 서버

## Railway 배포 가이드

### 1. 필수 환경 변수 설정

Railway 대시보드의 Variables 탭에서 다음 환경 변수를 설정하세요:

```
DB_HOST=your_database_host
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_NAME=your_database_name
NAVER_CLIENT_ID=your_naver_client_id
NAVER_CLIENT_SECRET=your_naver_client_secret
```

### 2. 선택적 환경 변수

```
ENABLE_DB_SAVE=true
SEARCH_KEYWORD=프리스타일 리브레2
DB_PORT=3306
DB_TABLE=products
```

### 3. API 엔드포인트

- `GET /` - API 정보
- `GET /docs` - Swagger UI 문서
- `GET /health` - 헬스 체크
- `GET /products/latest` - 최신 상품 데이터
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
