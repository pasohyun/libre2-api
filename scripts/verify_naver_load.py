"""네이버 크롤링 적재 검증 (읽기 전용, DB 변경 없음) — 과업 1-7 수동/자동 테스트용.

무엇을 확인하는가
  1) 스케줄: 기간 내 각 날짜의 예정 슬롯(CRAWL_TIMES_KST)마다 스냅샷이 실제로 들어왔는지
  2) 스냅샷 품질: 직전 스냅샷들 중앙값 대비 행 수·판매처 수 급감, calc_valid=0 비율
  3) 중복: 짧은 간격(기본 10분)으로 스냅샷이 두 번 들어간 경우 (수동+자동 겹침, Cron 중복)
  4) (선택) API /crawl/status 의 running / last_error

사용법:
    python -m scripts.verify_naver_load                       # 최근 1일
    python -m scripts.verify_naver_load --days 3
    python -m scripts.verify_naver_load --since "2026-10-16 14:00"   # 수동 실행 직후 확인
    python -m scripts.verify_naver_load --api-url https://<railway-web>/  # /crawl/status 함께 확인

종료 코드: 문제 없으면 0, 경고가 하나라도 있으면 1 (Cron/CI 에서 실패 감지용).
"""
import argparse
import os
import statistics
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

KST = ZoneInfo("Asia/Seoul")

CRAWL_TIMES_KST = [
    t.strip()
    for t in os.getenv("CRAWL_TIMES_KST", "03:00,06:00,09:00,15:00,18:00,21:00").split(",")
    if t.strip()
]
SLOT_TOLERANCE_MIN = int(os.getenv("VERIFY_SLOT_TOLERANCE_MIN", "30"))
DUP_WINDOW_MIN = int(os.getenv("VERIFY_DUP_WINDOW_MIN", "10"))
DROP_RATIO = float(os.getenv("VERIFY_DROP_RATIO", "0.7"))       # 중앙값의 70% 미만이면 급감
INVALID_RATIO = float(os.getenv("VERIFY_INVALID_RATIO", "0.2"))  # calc_valid=0 이 20% 넘으면 경고
BASELINE_N = 6  # 비교 기준: 직전 스냅샷 6개(하루치)


# ------------------------------------------------------------------ 순수 로직
def expected_slots(start: datetime, end: datetime, times=CRAWL_TIMES_KST):
    """[start, end] 범위에 들어가는 예정 슬롯(naive KST datetime) 목록."""
    slots = []
    day = start.date()
    while day <= end.date():
        for t in times:
            h, m = map(int, t.split(":"))
            s = datetime(day.year, day.month, day.day, h, m)
            if start <= s <= end:
                slots.append(s)
        day += timedelta(days=1)
    return slots


def match_slots(slots, snapshot_times, tolerance_min=SLOT_TOLERANCE_MIN):
    """슬롯별로 허용 오차 안에 들어온 스냅샷이 있는지. 반환: (matched, missing)"""
    tol = timedelta(minutes=tolerance_min)
    matched, missing = [], []
    for s in slots:
        hit = [t for t in snapshot_times if s <= t <= s + tol]
        (matched if hit else missing).append(s)
    return matched, missing


def find_duplicates(snapshot_times, window_min=DUP_WINDOW_MIN):
    """간격이 window_min 이하인 연속 스냅샷 쌍."""
    ts = sorted(snapshot_times)
    w = timedelta(minutes=window_min)
    return [(a, b) for a, b in zip(ts, ts[1:]) if b - a <= w]


def quality_warnings(snapshots, baseline_n=BASELINE_N,
                     drop_ratio=DROP_RATIO, invalid_ratio=INVALID_RATIO):
    """snapshots: snapshot_at 오름차순 dict 목록
    (keys: snapshot_id, snapshot_at, rows, malls, invalid, below_target)

    각 스냅샷을 '직전 baseline_n개 중앙값'과 비교한다.
    """
    warns = []
    for i, s in enumerate(snapshots):
        prev = snapshots[max(0, i - baseline_n):i]
        label = f"{s['snapshot_at']:%m-%d %H:%M} ({s['snapshot_id']})"
        if prev:
            med_rows = statistics.median(p["rows"] for p in prev)
            med_malls = statistics.median(p["malls"] for p in prev)
            if med_rows and s["rows"] < med_rows * drop_ratio:
                warns.append(f"{label}: 행 수 급감 {s['rows']} (직전 중앙값 {med_rows:g})")
            if med_malls and s["malls"] < med_malls * drop_ratio:
                warns.append(f"{label}: 판매처 수 급감 {s['malls']} (직전 중앙값 {med_malls:g})")
        if s["rows"] and s["invalid"] / s["rows"] > invalid_ratio:
            warns.append(f"{label}: calc_valid=0 비율 {s['invalid']}/{s['rows']}")
    return warns


# ------------------------------------------------------------------ I/O
def _connect():
    import mysql.connector

    host = os.getenv("MYSQLHOST") or os.getenv("DB_HOST")
    if not host:
        sys.exit("DB 연결 정보 없음: MYSQLHOST 또는 DB_HOST 를 설정하세요 (.env)")
    return mysql.connector.connect(
        host=host,
        port=int(os.getenv("MYSQLPORT") or os.getenv("DB_PORT", 3306)),
        user=os.getenv("MYSQLUSER") or os.getenv("DB_USER"),
        password=os.getenv("MYSQLPASSWORD") or os.getenv("DB_PASSWORD"),
        database=os.getenv("MYSQLDATABASE") or os.getenv("DB_NAME"),
        charset="utf8mb4",
        connection_timeout=10,
    )


def load_snapshots(conn, since: datetime, baseline_n=BASELINE_N):
    """since 이후 스냅샷 + 비교 기준용 직전 스냅샷 baseline_n개."""
    table = os.getenv("DB_TABLE", "products")
    target = int(os.getenv("TARGET_PRICE", 90000))
    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"""
        SELECT snapshot_id, snapshot_at,
               COUNT(*)                      AS `rows`,
               COUNT(DISTINCT mall_name)     AS malls,
               SUM(calc_valid = 0)           AS invalid,
               SUM(unit_price <= %s)         AS below_target
          FROM {table}
         WHERE channel = 'naver' AND snapshot_id IS NOT NULL
           AND snapshot_at >= (
                 SELECT COALESCE(MIN(t.snapshot_at), %s) FROM (
                   SELECT DISTINCT snapshot_at FROM {table}
                    WHERE channel = 'naver' AND snapshot_at < %s
                    ORDER BY snapshot_at DESC LIMIT %s
                 ) t)
         GROUP BY snapshot_id, snapshot_at
         ORDER BY snapshot_at
        """,
        (target, since, since, baseline_n),
    )
    rows = cur.fetchall()
    cur.close()
    for r in rows:
        r["invalid"] = int(r["invalid"] or 0)
        r["below_target"] = int(r["below_target"] or 0)
    return rows


def check_api(api_url: str):
    import requests

    url = api_url.rstrip("/") + "/crawl/status"
    try:
        d = requests.get(url, timeout=15).json()
    except Exception as e:
        return [f"/crawl/status 호출 실패: {type(e).__name__}: {e}"], None
    warns = []
    if d.get("last_error"):
        warns.append(f"/crawl/status last_error: {d['last_error']}")
    return warns, d


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="네이버 크롤링 적재 검증 (읽기 전용)")
    ap.add_argument("--days", type=float, default=1, help="최근 N일 (기본 1)")
    ap.add_argument("--since", help='시작 시각 KST, 예: "2026-10-16 14:00"')
    ap.add_argument("--api-url", help="Railway web 주소 (/crawl/status 확인)")
    ap.add_argument("--no-schedule", action="store_true",
                    help="스케줄 슬롯 점검 생략 (수동 실행만 확인할 때)")
    args = ap.parse_args()

    now = datetime.now(KST).replace(tzinfo=None, microsecond=0)
    since = (datetime.strptime(args.since, "%Y-%m-%d %H:%M") if args.since
             else now - timedelta(days=args.days))

    conn = _connect()
    allsnaps = load_snapshots(conn, since)
    conn.close()
    window = [s for s in allsnaps if s["snapshot_at"] >= since]

    print(f"\n네이버 적재 검증  {since:%Y-%m-%d %H:%M} ~ {now:%Y-%m-%d %H:%M} KST\n")
    print(f"{'snapshot_at':<17}{'rows':>6}{'malls':>7}{'≤기준가':>8}{'invalid':>9}  snapshot_id")
    for s in window:
        print(f"{s['snapshot_at']:%Y-%m-%d %H:%M}  {s['rows']:>5}{s['malls']:>7}"
              f"{s['below_target']:>8}{s['invalid']:>9}  {s['snapshot_id']}")
    if not window:
        print("  (해당 기간 스냅샷 없음)")
    print()

    warns = []
    times = [s["snapshot_at"] for s in window]

    if not args.no_schedule:
        # 아직 허용 오차가 끝나지 않은 슬롯은 판정에서 뺀다
        slots = expected_slots(since, now - timedelta(minutes=SLOT_TOLERANCE_MIN))
        matched, missing = match_slots(slots, times)
        print(f"[스케줄] 예정 {len(slots)}회 / 적재 {len(matched)}회 "
              f"(허용 오차 +{SLOT_TOLERANCE_MIN}분)")
        warns += [f"스케줄 누락: {m:%m-%d %H:%M}" for m in missing]

    warns += [f"중복 의심: {a:%m-%d %H:%M} / {b:%H:%M} ({DUP_WINDOW_MIN}분 이내)"
              for a, b in find_duplicates(times)]

    idx = len(allsnaps) - len(window)
    warns += [w for w in quality_warnings(allsnaps)
              if any(s["snapshot_id"] in w for s in allsnaps[idx:])]

    if args.api_url:
        api_warns, status = check_api(args.api_url)
        if status:
            print(f"[API] running={status.get('running')} "
                  f"last_started={status.get('last_started_at')} "
                  f"last_finished={status.get('last_finished_at')}")
        warns += api_warns

    print()
    if warns:
        print(f"⚠️ 경고 {len(warns)}건")
        for w in warns:
            print(f"  - {w}")
        sys.exit(1)
    print("✅ 이상 없음")


if __name__ == "__main__":
    main()
