"""crawl_naver_brightdata fallback 로직 단위 테스트 (네트워크/DB 없음).

    python -m pytest tests/test_naver_fallback.py -q
"""
import pytest

import scripts.crawl_naver_brightdata as m


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(m, "PAGE_SLEEP_SEC", 0)
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)


def _pages(n_pages, per_page=100, total=None):
    """cursor 1..n 으로 이어지는 가짜 페이지 응답."""
    total = total if total is not None else n_pages * per_page

    def page(cursor):
        items = [{"id": f"{cursor}-{i}"} for i in range(per_page)]
        has_more = cursor < n_pages
        return items, (cursor + 1 if has_more else None), has_more, total
    return page


def _backend(page_fn, fail_from_cursor=None, calls=None):
    def fetch(keyword, cursor):
        if calls is not None:
            calls.append(cursor)
        if fail_from_cursor is not None and cursor >= fail_from_cursor:
            raise m.BlockedError(f"blocked at {cursor}")
        return page_fn(cursor)
    return fetch


def test_primary_ok_no_fallback():
    page = _pages(3)
    fb_calls = []
    items, meta = m.fetch_all_products(
        "kw", backends=[("a", _backend(page)), ("b", _backend(page, calls=fb_calls))]
    )
    assert len(items) == 300
    assert meta["backends_used"] == ["a"]
    assert fb_calls == []


def test_fallback_resumes_from_same_cursor_and_is_sticky():
    page = _pages(4)
    a_calls, b_calls = [], []
    items, meta = m.fetch_all_products(
        "kw",
        backends=[
            ("a", _backend(page, fail_from_cursor=3, calls=a_calls)),
            ("b", _backend(page, calls=b_calls)),
        ],
    )
    assert len(items) == 400
    assert len({it["id"] for it in items}) == 400  # 중복/누락 없음
    assert a_calls == [1, 2, 3]
    assert b_calls == [3, 4]  # 실패한 cursor 부터 이어서, a 로 복귀하지 않음
    assert meta["backends_used"] == ["a", "b"]


def test_all_backends_fail_raises_and_returns_nothing():
    page = _pages(3)
    with pytest.raises(m.NaverCrawlFailed) as ei:
        m.fetch_all_products(
            "kw",
            backends=[
                ("a", _backend(page, fail_from_cursor=2)),
                ("b", _backend(page, fail_from_cursor=1)),
            ],
        )
    assert "100건에서 중단" in str(ei.value)


def test_completeness_guard():
    m.check_completeness([0] * 448, 450)  # 실측 수준은 통과
    m.check_completeness([0] * 10, None)  # total 모르면 통과
    with pytest.raises(m.NaverCrawlFailed):
        m.check_completeness([0] * 200, 450)


def test_build_backends_respects_env(monkeypatch):
    monkeypatch.setattr(m, "PROXY_SERVER", "http://brd.superproxy.io:33335")
    for k in ("BRIGHT_DATA_PROXY", "BRIGHT_DATA_USERNAME", "BRIGHT_DATA_PASSWORD",
              "BRIGHT_DATA_FALLBACK_PROXY", "BRIGHT_DATA_FALLBACK_USERNAME",
              "BRIGHT_DATA_FALLBACK_PASSWORD", "NAVER_FETCH_BACKENDS", "NAVER_ALLOW_DIRECT"):
        monkeypatch.delenv(k, raising=False)

    with pytest.raises(m.NaverCrawlFailed):
        m.build_fetch_backends()  # 아무 크리덴셜도 없음

    monkeypatch.setenv("BRIGHT_DATA_PROXY", "http://brd.superproxy.io:33335")
    monkeypatch.setenv("BRIGHT_DATA_USERNAME", "u-res")
    monkeypatch.setenv("BRIGHT_DATA_PASSWORD", "p")
    assert [n for n, _ in m.build_fetch_backends()] == ["brightdata-residential-kr"]

    monkeypatch.setenv("BRIGHT_DATA_FALLBACK_USERNAME", "u-unl")
    monkeypatch.setenv("BRIGHT_DATA_FALLBACK_PASSWORD", "p2")
    monkeypatch.setenv("NAVER_ALLOW_DIRECT", "true")
    assert [n for n, _ in m.build_fetch_backends()] == [
        "brightdata-residential-kr", "brightdata-fallback-zone", "direct",
    ]

    monkeypatch.setenv("NAVER_FETCH_BACKENDS", "unlocker,residential")
    assert [n for n, _ in m.build_fetch_backends()] == [
        "brightdata-fallback-zone", "brightdata-residential-kr",
    ]
    assert [n for n, _ in m.build_fetch_backends(use_proxy=False)] == ["direct"]


def test_build_proxies_session_optional():
    p = m._build_proxies("abc", server="http://h:1", username="u", password="p@w")
    assert p["https"] == "http://u-session-abc:p%40w@h:1"
    p = m._build_proxies(None, server="http://h:1", username="u", password="p")
    assert p["https"] == "http://u:p@h:1"


class _Resp:
    def __init__(self, status=200, ctype="application/json", payload=None, url="https://x"):
        self.status_code = status
        self.headers = {"content-type": ctype}
        self._payload = payload or {}
        self.url = url
        self.text = str(self._payload)

    def json(self):
        return self._payload


def test_soft_block_empty_first_page_triggers_retry(monkeypatch):
    responses = iter([
        _Resp(payload={"data": {"data": [], "total": 0, "hasMore": False}}),
        _Resp(status=418, ctype="text/html"),
        _Resp(payload={"data": {"data": [{"id": 1}], "total": 1, "hasMore": False, "cursor": None}}),
    ])
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: next(responses))
    items, nxt, has_more, total = m._fetch_page_via_proxy("kw", 1, proxy_cfg=None)
    assert items == [{"id": 1}] and total == 1


def test_run_crawling_raises_on_failure_without_saving(monkeypatch):
    saved = []
    monkeypatch.setattr(m, "load_confirmed_qty_by_link_map", lambda: {})
    monkeypatch.setattr(m, "save_to_db", lambda *a, **k: saved.append(1))
    monkeypatch.setattr(m, "build_fetch_backends", lambda **k: [("a", None)])

    def boom(*a, **k):
        raise m.NaverCrawlFailed("모든 백엔드 실패")
    monkeypatch.setattr(m, "fetch_all_products", boom)
    with pytest.raises(m.NaverCrawlFailed):
        m.run_crawling()
    assert saved == []

    monkeypatch.setattr(m, "fetch_all_products",
                        lambda *a, **k: ([{"x": 1}] * 100, {"total": 450}))
    with pytest.raises(m.NaverCrawlFailed, match="수집 불완전"):
        m.run_crawling()
    assert saved == []


def test_proxy_auth_error_skips_retries(monkeypatch):
    calls = []

    def fake_get(*a, **k):
        calls.append(1)
        raise m.requests.exceptions.ProxyError(
            "Unable to connect to proxy: Tunnel connection failed: 407 Invalid Auth"
        )
    monkeypatch.setattr(m.requests, "get", fake_get)
    cfg = {"server": "http://h:1", "username": "u", "password": "p"}
    with pytest.raises(m.BlockedError, match="407"):
        m._fetch_page_via_proxy("kw", 1, proxy_cfg=cfg)
    assert len(calls) == 1  # 재시도 없이 즉시 포기


def test_other_proxy_error_still_retries(monkeypatch):
    calls = []

    def fake_get(*a, **k):
        calls.append(1)
        raise m.requests.exceptions.ProxyError("Tunnel connection failed: 502 Bad Gateway")
    monkeypatch.setattr(m.requests, "get", fake_get)
    cfg = {"server": "http://h:1", "username": "u", "password": "p"}
    with pytest.raises(m.BlockedError):
        m._fetch_page_via_proxy("kw", 1, proxy_cfg=cfg)
    assert len(calls) == m.MAX_RETRIES


def test_legacy_entrypoint_delegates_to_brightdata(monkeypatch):
    import scripts.crawl_naver as legacy

    calls = []
    monkeypatch.setattr(m, "run_crawling", lambda *a, **k: calls.append(1))
    legacy.run_crawling()
    assert calls == [1]


def test_db_insert_zero_raises(monkeypatch):
    """DB 연결 실패로 save_to_db 가 0을 반환하면 성공으로 넘기지 않는다."""
    monkeypatch.setattr(m, "load_confirmed_qty_by_link_map", lambda: {})
    monkeypatch.setattr(m, "build_fetch_backends", lambda **k: [("a", None)])
    monkeypatch.setattr(m, "fetch_all_products",
                        lambda *a, **k: ([{"x": 1}], {"total": 1}))
    monkeypatch.setattr(m, "build_rows", lambda items, kw, confirmed_qty_by_link=None: [
        {"unit_price": 90000}])
    monkeypatch.setattr(m, "save_to_db", lambda rows, **kw: 0)
    with pytest.raises(m.NaverCrawlFailed, match="DB 적재 0건"):
        m.run_crawling()


def test_round_retry_recovers_after_wait(monkeypatch):
    calls, waits = [], []
    monkeypatch.setattr(m.time, "sleep", lambda sec: waits.append(sec))
    monkeypatch.setattr(m, "ROUND_RETRIES", 2)
    monkeypatch.setattr(m, "ROUND_RETRY_WAIT_SEC", 300)

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise m.NaverCrawlFailed("502")
        return [{"id": 1}], {"total": 1}
    monkeypatch.setattr(m, "fetch_all_products", flaky)

    items, meta = m.fetch_with_round_retry("kw", backends=[("a", None)])
    assert items == [{"id": 1}]
    assert len(calls) == 3
    assert waits == [300, 300]


def test_round_retry_gives_up_after_last_round(monkeypatch):
    calls = []
    monkeypatch.setattr(m, "ROUND_RETRIES", 1)

    def always_fail(*a, **k):
        calls.append(1)
        raise m.NaverCrawlFailed("502")
    monkeypatch.setattr(m, "fetch_all_products", always_fail)

    with pytest.raises(m.NaverCrawlFailed):
        m.fetch_with_round_retry("kw", backends=[("a", None)])
    assert len(calls) == 2


@pytest.mark.filterwarnings("ignore:.*found in sys.modules:RuntimeWarning")
def test_legacy_main_skips_cleanly_when_already_running(monkeypatch):
    """python -m scripts.crawl_naver 로 실행돼도 겹친 실행은 exit 0 으로 끝난다."""
    import runpy
    import scripts.crawl_lock as lock

    def busy(**_):
        raise lock.CrawlAlreadyRunning("busy")
    monkeypatch.setattr(m, "run_crawling", busy)
    monkeypatch.setattr("sys.argv", ["crawl_naver"])
    runpy.run_module("scripts.crawl_naver", run_name="__main__")  # SystemExit 가 나면 실패
