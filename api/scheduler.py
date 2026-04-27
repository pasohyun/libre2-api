# api/scheduler.py
import logging
import os
import threading
import time
import traceback

import schedule

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop_event = threading.Event()

# 크롤링 시각 (KST 기준, 환경변수로 덮어쓰기 가능)
# 기본: 06:00 / 12:00 / 18:00 / 00:00
CRAWL_TIMES_KST = [
    t.strip()
    for t in os.getenv("CRAWL_TIMES_KST", "06:00,12:00,18:00,00:00").split(",")
    if t.strip()
]
ALERT_SEND_TIME_KST = os.getenv("ALERT_SEND_TIME_KST", "09:00").strip() or "09:00"

# gunicorn multi-worker 환경에서 중복 실행 방지
SCHEDULER_ENABLED = os.getenv("ENABLE_SCHEDULER", "false").lower() == "true"


def _run_coupang_crawl():
    """쿠팡 URL 스냅샷 크롤링 실행"""
    logger.info("[scheduler] 쿠팡 크롤링 시작")
    try:
        from scripts.crawl_coupang_urls import run_crawling
        run_crawling()
        logger.info("[scheduler] 쿠팡 크롤링 완료")
    except Exception:
        logger.error("[scheduler] 쿠팡 크롤링 실패\n%s", traceback.format_exc())


def _run_daily_alert():
    """전일 셋팅가 미만 거래처 메일 발송"""
    logger.info("[scheduler] 일일 알람 메일 발송 시작")
    try:
        from api.services.daily_alerts import run_daily_alert_job

        result = run_daily_alert_job()
        logger.info("[scheduler] 일일 알람 결과: %s", result)
    except Exception:
        logger.error("[scheduler] 일일 알람 메일 발송 실패\n%s", traceback.format_exc())


def _kst_to_utc(hhmm: str) -> str:
    """HH:MM (KST) → HH:MM (UTC) 변환 (KST = UTC+9)"""
    h, m = map(int, hhmm.split(":"))
    utc_h = (h - 9) % 24
    return f"{utc_h:02d}:{m:02d}"


def _scheduler_loop():
    for t_kst in CRAWL_TIMES_KST:
        t_utc = _kst_to_utc(t_kst)
        schedule.every().day.at(t_utc).do(_run_coupang_crawl)
        logger.info("[scheduler] 등록: 매일 %s KST (%s UTC)", t_kst, t_utc)

    alert_utc = _kst_to_utc(ALERT_SEND_TIME_KST)
    schedule.every().day.at(alert_utc).do(_run_daily_alert)
    logger.info(
        "[scheduler] 등록: 매일 %s KST (%s UTC) - 일일 알람 메일",
        ALERT_SEND_TIME_KST,
        alert_utc,
    )

    while not _stop_event.is_set():
        schedule.run_pending()
        time.sleep(30)


def start():
    global _thread
    if not SCHEDULER_ENABLED:
        logger.info("[scheduler] ENABLE_SCHEDULER=false → 스케줄러 비활성")
        return
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_scheduler_loop, daemon=True, name="coupang-scheduler")
    _thread.start()
    logger.info("[scheduler] 백그라운드 스케줄러 시작 (times=%s)", CRAWL_TIMES_KST)


def stop():
    _stop_event.set()
    schedule.clear()
    logger.info("[scheduler] 스케줄러 중지")


def run_now():
    """수동 즉시 실행 (API endpoint에서 호출)"""
    t = threading.Thread(target=_run_coupang_crawl, daemon=True, name="coupang-manual")
    t.start()
    return t
