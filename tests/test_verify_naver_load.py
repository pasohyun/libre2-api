"""verify_naver_load 순수 로직 단위 테스트 (DB/네트워크 없음).

    python -m pytest tests/test_verify_naver_load.py -q
"""
from datetime import datetime as dt

import scripts.verify_naver_load as v

TIMES = ["03:00", "06:00", "09:00", "15:00", "18:00", "21:00"]


def test_expected_slots_one_day():
    s = v.expected_slots(dt(2026, 10, 16, 0, 0), dt(2026, 10, 16, 23, 59), TIMES)
    assert [x.hour for x in s] == [3, 6, 9, 15, 18, 21]


def test_expected_slots_partial_range():
    s = v.expected_slots(dt(2026, 10, 15, 20, 0), dt(2026, 10, 16, 7, 0), TIMES)
    assert s == [dt(2026, 10, 15, 21), dt(2026, 10, 16, 3), dt(2026, 10, 16, 6)]


def test_match_slots_tolerance_and_missing():
    slots = [dt(2026, 10, 16, 3), dt(2026, 10, 16, 6), dt(2026, 10, 16, 9)]
    snaps = [dt(2026, 10, 16, 3, 2), dt(2026, 10, 16, 6, 45)]  # 06시는 45분 지연 → 누락
    matched, missing = v.match_slots(slots, snaps, tolerance_min=30)
    assert matched == [dt(2026, 10, 16, 3)]
    assert missing == [dt(2026, 10, 16, 6), dt(2026, 10, 16, 9)]


def test_find_duplicates():
    ts = [dt(2026, 10, 16, 15, 0), dt(2026, 10, 16, 15, 5), dt(2026, 10, 16, 18, 0)]
    assert v.find_duplicates(ts, window_min=10) == [(ts[0], ts[1])]


def _snap(i, rows, malls, invalid=0):
    return {"snapshot_id": f"s{i}", "snapshot_at": dt(2026, 10, 16, i),
            "rows": rows, "malls": malls, "invalid": invalid, "below_target": 0}


def test_quality_normal_no_warning():
    snaps = [_snap(i, 160 + i, 40) for i in range(7)]
    assert v.quality_warnings(snaps) == []


def test_quality_drop_and_invalid():
    snaps = [_snap(i, 160, 40) for i in range(6)] + [_snap(7, 60, 12, invalid=30)]
    w = v.quality_warnings(snaps)
    assert any("행 수 급감" in x for x in w)
    assert any("판매처 수 급감" in x for x in w)
    assert any("calc_valid=0" in x for x in w)
