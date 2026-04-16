// src/api/reports.ts
import { API_BASE_URL } from "../config/api";
import { authFetch } from "./authFetch";

export type MonthlyReportParams = {
  month: string; // "YYYY-MM"
  threshold_price: number; // 85000
  channel: "naver" | "coupang" | "all";
  crawl_schedule?: string; // "00/12"
  top_cards?: number; // 10
  use_llm?: boolean; // true/false
  store?: boolean; // true/false
};

export async function getMonthlyReport(params: MonthlyReportParams) {
  const {
    month,
    threshold_price,
    channel,
    crawl_schedule = "00/12",
    top_cards = 10,
    use_llm = true,
    store = false,
  } = params;

  const qs = new URLSearchParams({
    threshold_price: String(threshold_price),
    channel,
    crawl_schedule,
    top_cards: String(top_cards),
    use_llm: String(use_llm),
    store: String(store),
  });

  const url = `${API_BASE_URL}/reports/monthly/${encodeURIComponent(month)}?${qs.toString()}`;

  const res = await fetch(url, {
    method: "GET",
    headers: { accept: "application/json" },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Monthly report failed: ${res.status} ${res.statusText} ${text}`,
    );
  }

  return res.json(); // 백엔드 응답 스키마 그대로 반환
}

// ── Date-Range Report ──────────────────────────────────────

export type RangeReportParams = {
  start_date: string; // "YYYY-MM-DD"
  end_date: string; // "YYYY-MM-DD"
  threshold_price: number;
  channel: "naver" | "coupang" | "all";
};

export async function getRangeReport(params: RangeReportParams) {
  const { start_date, end_date, threshold_price, channel } = params;

  const qs = new URLSearchParams({
    start_date,
    end_date,
    threshold_price: String(threshold_price),
    channel,
  });

  const url = `${API_BASE_URL}/reports/range?${qs.toString()}`;

  const res = await authFetch(url, {
    method: "GET",
    headers: { accept: "application/json" },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Range report failed: ${res.status} ${res.statusText} ${text}`,
    );
  }

  return res.json();
}
