"""
판매처별 최저가 시계열에 대한 통계 분석.

- 이상치: 지연 롤링 중앙값 대비 잔차의 MAD 기반 modified z-score (Iglewicz & Hoaglin).
- 단기 예측: statsmodels Holt 가법 지수평활(추세 가산) 1스텝; 실패·관측 부족 시 OLS 폴백.

스냅샷 밀도: api/scheduler.py 기본과 같이 하루 4회(06/12/18/00 KST)를 가정한다.
롤링·적합 최대 길이는 `SNAPSHOTS_PER_DAY`를 곱해 ‘일’ 단위로 맞춘다.
"""

from __future__ import annotations

import os
import warnings
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session


MODIFIED_Z_THRESHOLD = 3.5

# 하루 스냅샷 수 (스케줄 변경 시 PRICE_ANALYTICS_SNAPSHOTS_PER_DAY 로 맞출 것)
SNAPSHOTS_PER_DAY = int(os.getenv("PRICE_ANALYTICS_SNAPSHOTS_PER_DAY", "4"))

# 베이스라인: 약 7일치 스냅샷 (4회/일 → 28개)
ROLL_BASELINE_DAYS = int(os.getenv("PRICE_ANALYTICS_BASELINE_DAYS", "7"))
ROLL_BASELINE = SNAPSHOTS_PER_DAY * ROLL_BASELINE_DAYS

# 롤링 중앙값을 쓰기 위한 최소 스냅샷 수 (기본 2일치)
ROLL_MIN_PERIOD_DAYS = int(os.getenv("PRICE_ANALYTICS_BASELINE_MIN_DAYS", "2"))
ROLL_MIN_PERIODS = max(3, SNAPSHOTS_PER_DAY * ROLL_MIN_PERIOD_DAYS)

# OLS 폴백: 최근 며칠치만 직선 적합 (기본 7일)
FORECAST_OLS_DAYS = int(os.getenv("PRICE_ANALYTICS_OLS_FIT_DAYS", "7"))
FORECAST_MAX_POINTS = max(5, SNAPSHOTS_PER_DAY * FORECAST_OLS_DAYS)

# Holt: 최소·최대 적합 길이를 ‘일’로 환산 (기본 최소 3일, 최대 30일)
ETS_MIN_DAYS = int(os.getenv("PRICE_ANALYTICS_ETS_MIN_DAYS", "3"))
ETS_MAX_DAYS = int(os.getenv("PRICE_ANALYTICS_ETS_MAX_DAYS", "30"))
ETS_MIN_LEN = max(5, SNAPSHOTS_PER_DAY * ETS_MIN_DAYS)
ETS_MAX_LEN = SNAPSHOTS_PER_DAY * ETS_MAX_DAYS


def _schedule_meta() -> dict[str, Any]:
    """API algorithm 필드에 붙이는 스케줄·창 설명."""
    return {
        "snapshots_per_day_assumed": SNAPSHOTS_PER_DAY,
        "rolling_median_days": ROLL_BASELINE_DAYS,
        "rolling_median_snapshots": ROLL_BASELINE,
        "rolling_min_days": ROLL_MIN_PERIOD_DAYS,
        "ets_fit_max_days": ETS_MAX_DAYS,
        "ets_fit_min_days": ETS_MIN_DAYS,
    }


def _channel_filter_sql(channel: str | None) -> tuple[str, dict[str, Any]]:
    if not channel:
        return "", {}
    sql = (
        " AND (p.channel = :channel "
        "OR (:channel = 'naver' AND (p.channel IS NULL OR TRIM(p.channel) = '')))"
    )
    return sql, {"channel": channel}


def fetch_mall_min_price_series(
    db: Session,
    *,
    mall_name_list: tuple[str, ...],
    days: int,
    channel: str | None,
) -> pd.DataFrame:
    """스냅샷 시각별 해당 판매처 최저 단가 시계열 (오름차순)."""
    ch_sql, ch_params = _channel_filter_sql(channel)
    rows = db.execute(
        text(
            f"""
            SELECT
                COALESCE(p.snapshot_at, p.created_at) AS ts,
                MIN(p.unit_price) AS min_price
            FROM products p
            WHERE p.mall_name IN :mall_name_list
              AND COALESCE(p.snapshot_at, p.created_at)
                  >= DATE_SUB(NOW(), INTERVAL :days DAY)
              {ch_sql}
            GROUP BY COALESCE(p.snapshot_at, p.created_at)
            ORDER BY ts ASC
            """
        ),
        {"mall_name_list": mall_name_list, "days": days, **ch_params},
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=["ts", "min_price"])

    df = pd.DataFrame([{"ts": r[0], "min_price": int(r[1])} for r in rows])
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def _modified_z_scores(values: np.ndarray) -> np.ndarray:
    med = np.median(values)
    mad = np.median(np.abs(values - med))
    if mad is None or mad < 1e-9:
        return np.zeros_like(values, dtype=float)
    return 0.6745 * (values - med) / mad


def detect_residual_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    baseline = lagged rolling median(가격).
    잔차에 대해 전역(해당 구간) robust z — 급락/급등 플래그.
    """
    if df.empty or len(df) < ROLL_MIN_PERIODS + 1:
        return pd.DataFrame(
            columns=[
                "ts",
                "min_price",
                "baseline",
                "residual",
                "modified_z",
                "kind",
            ]
        )

    x = df.sort_values("ts").reset_index(drop=True)
    baseline = (
        x["min_price"]
        .shift(1)
        .rolling(ROLL_BASELINE, min_periods=ROLL_MIN_PERIODS)
        .median()
    )
    resid = x["min_price"] - baseline
    valid_mask = resid.notna() & baseline.notna()
    if valid_mask.sum() < 5:
        return pd.DataFrame(
            columns=[
                "ts",
                "min_price",
                "baseline",
                "residual",
                "modified_z",
                "kind",
            ]
        )

    r = resid[valid_mask].to_numpy(dtype=float)
    mz = _modified_z_scores(r)
    mz_full = np.full(len(x), np.nan)
    mz_full[np.where(valid_mask)[0]] = mz

    out = x.assign(
        baseline=baseline,
        residual=resid,
        modified_z=mz_full,
    )
    strong = np.abs(mz_full) > MODIFIED_Z_THRESHOLD
    kinds = np.where(
        ~strong,
        "",
        np.where(mz_full < 0, "sharp_drop", "sharp_rise"),
    )
    out["kind"] = kinds
    flagged = out[out["kind"] != ""].copy()
    return flagged[
        ["ts", "min_price", "baseline", "residual", "modified_z", "kind"]
    ]


def _forecast_ols_fallback(y: np.ndarray) -> dict[str, Any] | None:
    """데이터 부족·ETS 실패 시: 최근 구간 OLS 직선 1스텝 외삽."""
    y = np.asarray(y, dtype=float)
    if len(y) < 5:
        return None
    n = min(FORECAST_MAX_POINTS, len(y))
    y_last = y[-n:]
    t = np.arange(n, dtype=float)
    a = np.vstack([t, np.ones(n)]).T
    slope, intercept = np.linalg.lstsq(a, y_last, rcond=None)[0]
    t_next = float(n)
    pred = slope * t_next + intercept
    fitted = slope * t + intercept
    rmse = float(np.sqrt(np.mean((y_last - fitted) ** 2)))
    margin = 1.96 * rmse if rmse > 1e-6 else float(np.std(y_last)) * 0.5
    pred = max(float(pred), 0.0)
    return {
        "predicted_min_price": pred,
        "pred_low": max(pred - margin, 0.0),
        "pred_high": max(pred + margin, 0.0),
        "horizon_steps": 1,
        "method": "ols_linear_trend_last_n",
        "window": int(n),
        "rmse": rmse,
    }


def forecast_next_min_price(y: np.ndarray) -> dict[str, Any] | None:
    """
    1스텝 앞 최저가 예측.

    우선 statsmodels Holt 가법 지수평활(추세 가산, 비계절).
    관측이 적거나 적합 실패 시 OLS 직선 폴백.
    """
    y = np.asarray(y, dtype=float)
    if len(y) < 5:
        return None

    y_fit = y[-min(len(y), ETS_MAX_LEN) :]

    if len(y_fit) >= ETS_MIN_LEN:
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = ExponentialSmoothing(
                    y_fit,
                    trend="add",
                    seasonal=None,
                )
                fit = model.fit(optimized=True)
                fc = fit.forecast(1)
                pred = float(np.squeeze(np.asarray(fc, dtype=float)))
                fitted = np.asarray(fit.fittedvalues, dtype=float)
                mask = np.isfinite(fitted) & np.isfinite(y_fit)
                if int(mask.sum()) >= 3:
                    rmse = float(
                        np.sqrt(np.mean((y_fit[mask] - fitted[mask]) ** 2))
                    )
                else:
                    rmse = float(np.std(y_fit))
                margin = 1.96 * rmse if rmse > 1e-6 else float(np.std(y_fit)) * 0.5
                pred = max(pred, 0.0)
                return {
                    "predicted_min_price": pred,
                    "pred_low": max(pred - margin, 0.0),
                    "pred_high": max(pred + margin, 0.0),
                    "horizon_steps": 1,
                    "method": "statsmodels_exponential_smoothing_holt_additive",
                    "window": int(len(y_fit)),
                    "rmse": rmse,
                }
        except Exception:
            pass

    return _forecast_ols_fallback(y)


def build_mall_price_insights(
    df: pd.DataFrame,
) -> dict[str, Any]:
    """시계열 DataFrame(ts, min_price) -> 이상치 목록 + 단기 예측 + 메타."""
    if df.empty:
        return {
            "observation_count": 0,
            "anomalies": [],
            "forecast": None,
            "algorithm": {
                "anomaly": (
                    f"lagged_rolling_median_{ROLL_BASELINE}snapshots_~{ROLL_BASELINE_DAYS}d_"
                    f"modified_z_mad_threshold_{MODIFIED_Z_THRESHOLD}"
                ),
                "forecast": "holt_ets_or_ols_fallback",
                **_schedule_meta(),
            },
        }

    x = df.sort_values("ts").reset_index(drop=True)
    anom_df = detect_residual_anomalies(x)
    anomalies: list[dict[str, Any]] = []
    for _, row in anom_df.iterrows():
        ts = row["ts"]
        if isinstance(ts, pd.Timestamp):
            ts_out = ts.to_pydatetime()
        else:
            ts_out = ts
        anomalies.append(
            {
                "ts": ts_out,
                "min_price": int(row["min_price"]),
                "baseline": float(row["baseline"])
                if pd.notna(row["baseline"])
                else None,
                "modified_z": float(row["modified_z"])
                if pd.notna(row["modified_z"])
                else None,
                "kind": str(row["kind"]),
            }
        )

    y = x["min_price"].to_numpy()
    fc = forecast_next_min_price(y)
    forecast_algo = (fc or {}).get("method", "none")

    return {
        "observation_count": int(len(x)),
        "anomalies": anomalies,
        "forecast": fc,
        "algorithm": {
            "anomaly": (
                f"lagged_rolling_median_{ROLL_BASELINE}snapshots_~{ROLL_BASELINE_DAYS}d_"
                f"modified_z_mad_threshold_{MODIFIED_Z_THRESHOLD}"
            ),
            "forecast": forecast_algo,
            "reference": "modified z-score (MAD): Iglewicz & Hoaglin (1993)",
            **_schedule_meta(),
        },
    }
