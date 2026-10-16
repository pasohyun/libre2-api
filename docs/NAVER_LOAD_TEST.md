# 네이버 크롤링 수동/자동 적재 테스트 (과업 1-7, 10/13~10/19)

전제: 1-5(Railway 운영 적용)·1-6(Cron 등록)이 끝난 상태. 모든 확인은 `scripts.verify_naver_load`(읽기 전용)로 한다.

## A. 수동 크롤링
| # | 절차 | 기대 결과 |
|---|---|---|
| A1 | 로컬 `python -m scripts.crawl_naver_brightdata --dry-run` | 수집률 ≥90%, 필터 통과 150~170건 수준, DB 미저장 |
| A2 | 대시보드 수동 실행 버튼 또는 `POST /crawl/run {"sources":["naver"]}` | `started: true` |
| A3 | 실행 중 재호출 | `status: running` (중복 실행 차단) |
| A4 | 종료 후 `GET /crawl/status` | `running: false`, `last_error: null` |
| A5 | `python -m scripts.verify_naver_load --since "<실행 시각>" --no-schedule --api-url <web 주소>` | 새 스냅샷 1건, 행·판매처 수 급감 경고 없음 |
| A6 | 대시보드에서 최신 시각·최저가 판매처 확인 | 새 스냅샷 반영, 기존 화면과 형식 동일 |

## B. 자동 크롤링 (Railway Cron, KST 03/06/09/15/18/21시)
| # | 절차 | 기대 결과 |
|---|---|---|
| B1 | Cron 등록 다음 날 `verify_naver_load --days 1` | 예정 6회 / 적재 6회, 경고 0건 (exit 0) |
| B2 | Railway Cron 실행 로그 | `START NAVER` ~ `DB inserted: N` ~ `END`, 백엔드 `brightdata-residential-kr` |
| B3 | 테스트 주간 마감 시 `verify_naver_load --days 3` | 누락·중복 없음 |

## C. 실패 시나리오 (운영 DB 영향 없이)
| # | 절차 | 기대 결과 |
|---|---|---|
| C1 | 로컬에서 `BRIGHT_DATA_PASSWORD` 틀리게 + fallback 존 설정 후 `--dry-run` | 407 즉시 감지 → 다음 백엔드로 전환 |
| C2 | 로컬에서 모든 백엔드 무효 + `--dry-run` | `NaverCrawlFailed`, exit 1, 저장 없음 |
| C3 | 로컬에서 DB 환경변수 틀리게 + 실제 실행 | `DB 적재 0건` 오류, exit 1 (이번 변경으로 추가) |

결과는 #, 일시, 결과(통과/실패), 비고(스냅샷 ID·로그 한 줄)로 기록해 주간 보고에 첨부한다.
