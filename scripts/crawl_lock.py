"""네이버 크롤링 동시 실행 방지 락 (프로세스·컨테이너 간 공유).

배경 (10/13 운영 이슈):
    main 반영 직후 Railway Cron 여러 개가 동시에 크롤링을 시작하고, 실패 시 자동 재시작까지
    겹쳐 짧은 시간에 요청이 몰려 네이버가 502로 일시 차단했다.
    web 의 /crawl/run 은 프로세스 내부 락만 있어서 Cron 컨테이너와의 겹침은 막지 못한다.

방식:
    Cron·web 이 모두 같은 Railway MySQL 을 쓰므로 MySQL GET_LOCK 을 쓴다.
      - 연결(세션)이 살아 있는 동안만 락이 유지되고, 프로세스가 죽으면 MySQL 이 자동 해제한다.
        → 비정상 종료 후 락이 남는(stale lock) 문제가 없다.
      - 테이블 생성이 필요 없다.
    DB 설정이 없는 로컬 점검(--dry-run 등)에서는 락 없이 진행한다.

사용:
    with naver_crawl_lock():      # 이미 실행 중이면 CrawlAlreadyRunning
        ...
"""
import os
from contextlib import contextmanager

LOCK_NAME = os.getenv("NAVER_CRAWL_LOCK_NAME", "libre2_naver_crawl")
LOCK_WAIT_SEC = int(os.getenv("NAVER_CRAWL_LOCK_WAIT_SEC", "0"))  # 0 = 기다리지 않고 바로 포기


class CrawlAlreadyRunning(RuntimeError):
    """다른 프로세스(Cron/web)가 이미 네이버 크롤링 중."""


def _db_params():
    host = os.getenv("MYSQLHOST") or os.getenv("DB_HOST")
    if not host:
        return None
    return dict(
        host=host,
        port=int(os.getenv("MYSQLPORT") or os.getenv("DB_PORT", 3306)),
        user=os.getenv("MYSQLUSER") or os.getenv("DB_USER"),
        password=os.getenv("MYSQLPASSWORD") or os.getenv("DB_PASSWORD"),
        database=os.getenv("MYSQLDATABASE") or os.getenv("DB_NAME"),
        charset="utf8mb4",
        connection_timeout=10,
    )


def _default_connect():
    params = _db_params()
    if params is None:
        return None
    import mysql.connector

    return mysql.connector.connect(**params)


@contextmanager
def naver_crawl_lock(*, connect=_default_connect, log=print):
    """GET_LOCK 으로 크롤링 구간을 감싼다.

    connect: 테스트용 주입 지점. None 을 반환하면 락 없이 진행.
    """
    try:
        conn = connect()
    except Exception as e:
        # 락 DB 연결 실패 시 크롤링 자체를 막지는 않는다 (저장 단계에서 어차피 다시 실패를 잡는다).
        log(f"[LOCK] DB 연결 실패 — 락 없이 진행: {type(e).__name__}: {e}")
        yield
        return

    if conn is None:
        log("[LOCK] DB 설정 없음 — 동시 실행 방지 락 없이 진행")
        yield
        return

    cur = conn.cursor()
    try:
        cur.execute("SELECT GET_LOCK(%s, %s)", (LOCK_NAME, LOCK_WAIT_SEC))
        got = cur.fetchone()[0]
        if got != 1:
            raise CrawlAlreadyRunning(
                f"다른 네이버 크롤링이 실행 중이라 이번 실행은 건너뜁니다 (lock={LOCK_NAME})"
            )
        log(f"[LOCK] 획득: {LOCK_NAME}")
        try:
            yield
        finally:
            try:
                cur.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))
                cur.fetchone()
                log(f"[LOCK] 해제: {LOCK_NAME}")
            except Exception as e:
                log(f"[LOCK] 해제 실패(연결 종료 시 자동 해제됨): {e}")
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
