// src/Report.jsx
import { useEffect, useMemo, useState } from "react";
import { authFetch } from "./api/authFetch";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function fetchTrackedMallsSummary() {
  const res = await authFetch(`${API_BASE}/products/tracked-malls/summary`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

async function fetchMallsTop(limit = 10) {
  const res = await authFetch(`${API_BASE}/products/malls/top?limit=${limit}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

const formatKRW = (n) =>
  typeof n === "number" && !Number.isNaN(n)
    ? n.toLocaleString("ko-KR") + "원"
    : "-";

const normalizeMallName = (name) => {
  const v = String(name || "").trim();
  return v === "네이버" ? "최저가비교" : v || "-";
};

function Table({ columns, rows, emptyText = "데이터가 없습니다." }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-200">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className="px-4 py-3 text-left font-medium">
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="px-4 py-6 text-slate-500" colSpan={columns.length}>
                {emptyText}
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr key={r.__rowKey} className="border-t border-slate-100">
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className="px-4 py-3 align-top text-slate-800"
                  >
                    {c.render ? c.render(r) : r[c.key]}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function Card({ title, children }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      {title && (
        <div className="px-5 py-4 border-b border-slate-100 font-semibold text-slate-900">
          {title}
        </div>
      )}
      <div className="p-5">{children}</div>
    </div>
  );
}

export default function Report() {
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState({
    target_price: 90000,
    tracked_malls: [],
    data: [],
  });
  const [top, setTop] = useState({ count: 0, data: [] });
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setLoading(true);
        setError("");
        const [s, t] = await Promise.all([
          fetchTrackedMallsSummary(),
          fetchMallsTop(10),
        ]);
        if (!alive) return;
        setSummary(s);
        setTop(t);
      } catch (e) {
        if (!alive) return;
        setError(e?.message || "리포트 데이터를 불러오지 못했습니다.");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const summaryRows = useMemo(
    () => (summary.data || []).map((x, i) => ({ ...x, __rowKey: `sum-${i}` })),
    [summary],
  );
  const topRows = useMemo(
    () => (top.data || []).map((x, i) => ({ ...x, __rowKey: `top-${i}` })),
    [top],
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm text-slate-500">리포트</div>
          <div className="text-2xl font-semibold text-slate-900">
            Tracked Malls Report
          </div>
        </div>
      </div>

      {loading ? (
        <div className="text-sm text-slate-500">불러오는 중...</div>
      ) : error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : (
        <>
          <Card title="Tracked Malls Summary">
            <Table
              columns={[
                {
                  key: "mall_name",
                  header: "몰",
                  render: (r) => normalizeMallName(r.mall_name),
                },
                {
                  key: "current_price",
                  header: "현재가",
                  render: (r) => formatKRW(r.current_price),
                },
                {
                  key: "min_price_7d",
                  header: "7일 최저",
                  render: (r) =>
                    r.min_price_7d ? formatKRW(r.min_price_7d) : "-",
                },
                {
                  key: "max_price_7d",
                  header: "7일 최고",
                  render: (r) =>
                    r.max_price_7d ? formatKRW(r.max_price_7d) : "-",
                },
                { key: "below_target_count", header: "기준가 이하(회)" },
              ]}
              rows={summaryRows}
              emptyText="summary 데이터가 없습니다."
            />
          </Card>

          <Card title="Top Malls">
            <Table
              columns={[
                {
                  key: "mall_name",
                  header: "몰",
                  render: (r) => normalizeMallName(r.mall_name),
                },
                {
                  key: "min_price",
                  header: "최저가",
                  render: (r) => (r.min_price ? formatKRW(r.min_price) : "-"),
                },
                { key: "count", header: "표본수" },
              ]}
              rows={topRows}
              emptyText="top 데이터가 없습니다."
            />
          </Card>
        </>
      )}
    </div>
  );
}
