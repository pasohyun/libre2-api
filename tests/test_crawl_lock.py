"""동시 실행 방지 락 · 재시도 백오프 단위 테스트 (네트워크/DB 없음).

    python -m pytest tests/test_crawl_lock.py -q
"""
import pytest

import scripts.crawl_lock as lock
import scripts.crawl_naver_brightdata as m


class FakeDB:
    """GET_LOCK/RELEASE_LOCK 만 흉내 내는 공유 락 저장소."""
    def __init__(self):
        self.held = set()
        self.closed = 0

    def connect(self):
        db = self

        class Cur:
            def execute(self, sql, args):
                name = args[0]
                if sql.startswith("SELECT GET_LOCK"):
                    self._r = 0 if name in db.held else 1
                    db.held.add(name)
                else:
                    db.held.discard(name)
                    self._r = 1

            def fetchone(self):
                return (self._r,)

            def close(self):
                pass

        class Conn:
            def cursor(self):
                return Cur()

            def close(self):
                db.closed += 1
        return Conn()


def test_lock_acquire_and_release():
    db = FakeDB()
    with lock.naver_crawl_lock(connect=db.connect, log=lambda *_: None):
        assert lock.LOCK_NAME in db.held
    assert lock.LOCK_NAME not in db.held
    assert db.closed == 1


def test_second_run_blocked_while_first_running():
    db = FakeDB()
    with lock.naver_crawl_lock(connect=db.connect, log=lambda *_: None):
        with pytest.raises(lock.CrawlAlreadyRunning):
            with lock.naver_crawl_lock(connect=db.connect, log=lambda *_: None):
                pass
        assert lock.LOCK_NAME in db.held  # 두 번째 시도가 첫 번째 락을 풀면 안 된다
    assert lock.LOCK_NAME not in db.held


def test_lock_released_on_exception():
    db = FakeDB()
    with pytest.raises(ValueError):
        with lock.naver_crawl_lock(connect=db.connect, log=lambda *_: None):
            raise ValueError("crawl failed")
    assert lock.LOCK_NAME not in db.held


def test_no_db_runs_without_lock():
    ran = []
    with lock.naver_crawl_lock(connect=lambda: None, log=lambda *_: None):
        ran.append(1)
    assert ran == [1]


def test_db_connect_error_does_not_block_crawl():
    def boom():
        raise OSError("db down")
    ran = []
    with lock.naver_crawl_lock(connect=boom, log=lambda *_: None):
        ran.append(1)
    assert ran == [1]


def test_main_exits_zero_when_already_running(monkeypatch):
    def busy(**_):
        raise lock.CrawlAlreadyRunning("busy")
    monkeypatch.setattr(m, "run_crawling", busy)
    monkeypatch.setattr("sys.argv", ["crawl_naver_brightdata"])
    m.main()  # SystemExit 가 나면 실패


def test_retry_delay_exponential_with_cap(monkeypatch):
    monkeypatch.setattr(m.random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(m, "RETRY_BASE_SEC", 5)
    monkeypatch.setattr(m, "RETRY_MAX_SEC", 60)
    assert [m.retry_delay(a) for a in (1, 2, 3, 4, 5)] == [5, 10, 20, 40, 60]


def test_backend_switch_waits(monkeypatch):
    sleeps = []
    monkeypatch.setattr(m, "PAGE_SLEEP_SEC", 0)
    monkeypatch.setattr(m, "BACKEND_SWITCH_SLEEP_SEC", 10)
    monkeypatch.setattr(m.time, "sleep", lambda s: sleeps.append(s))

    def bad(kw, cursor):
        raise m.BlockedError("502")

    def good(kw, cursor):
        return [{"id": 1}], None, False, 1

    items, meta = m.fetch_all_products("k", backends=[("a", bad), ("b", good)])
    assert len(items) == 1 and meta["backends_used"] == ["b"]
    assert 10 in sleeps
