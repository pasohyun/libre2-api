// src/pages/RangeReportPage.tsx
import React, { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { getRangeReport } from "../api/reports";
import { API_BASE_URL } from "../config/api";

type ReportData = any;

const todayStr = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const thirtyDaysAgoStr = () => {
  const d = new Date();
  d.setDate(d.getDate() - 30);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const fmtMoney = (v: any) => {
  if (v === null || v === undefined || v === "") return "-";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return `${n.toLocaleString("ko-KR")}원`;
};

const fmtTime = (v: any) => {
  if (!v) return "-";
  try {
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return String(v);
    return d.toLocaleString("ko-KR", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return String(v);
  }
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: 10,
  borderRadius: 10,
  border: "1px solid #d1d5db",
};

const sectionCard: React.CSSProperties = {
  border: "1px solid #e5e7eb",
  borderRadius: 12,
  padding: 16,
  marginBottom: 16,
  overflow: "hidden",
};

const printStyles = `
@media print {
  body * { visibility: hidden !important; }
  #range-report-printable, #range-report-printable * { visibility: visible !important; }
  #range-report-printable {
    position: absolute; left: 0; top: 0; width: 100%;
    padding: 16px;
  }
  #range-report-printable .print-header { display: block !important; }
  .no-print { display: none !important; }
  /* 차트 툴팁/커서 숨김 + 컨테이너 overflow 방지 */
  .recharts-tooltip-wrapper,
  .recharts-active-dot,
  .recharts-tooltip-cursor { display: none !important; }
  .recharts-responsive-container { overflow: hidden !important; }
  @page { margin: 10mm; }
}
`;

export default function RangeReportPage() {
  const [startDate, setStartDate] = useState(thirtyDaysAgoStr());
  const [endDate, setEndDate] = useState(todayStr());
  const [thresholdPrice, setThresholdPrice] = useState(85000);
  const [priceMin, setPriceMin] = useState<number | "">("");
  const [priceMax, setPriceMax] = useState<number | "">("");
  const [channel, setChannel] = useState<"naver" | "coupang" | "all">("naver");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ReportData | null>(null);
  const [modalItem, setModalItem] = useState<any | null>(null);

  // 기준가 이하 리스트 필터
  const [filterQuantity, setFilterQuantity] = useState<number | "">("");
  const [filterDate, setFilterDate] = useState("");
  const [filterHour, setFilterHour] = useState("");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [expandedSellers, setExpandedSellers] = useState<Set<number>>(new Set());

  // 셀러 카드 필터 (선택된 셀러만 표시, 빈 Set = 전체)
  const [selectedCardSellers, setSelectedCardSellers] = useState<Set<string>>(new Set());


  const onFetch = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getRangeReport({
        start_date: startDate,
        end_date: endDate,
        threshold_price: thresholdPrice,
        channel,
      });
      setData(res);
    } catch (e: any) {
      setError(e?.message ?? "Unknown error");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const summary = data?.summary || {};
  const belowListRaw: any[] = Array.isArray(data?.below_threshold_list)
    ? data.below_threshold_list
    : [];

  // 날짜/시간으로 스냅샷 필터링 헬퍼
  const matchesDateTime = (timeVal: any) => {
    if (!filterDate && !filterHour) return true;
    if (!timeVal) return false;
    const d = new Date(timeVal);
    if (Number.isNaN(d.getTime())) return false;
    const kst = new Date(d.toLocaleString("en-US", { timeZone: "Asia/Seoul" }));
    if (filterDate) {
      const dateStr = `${kst.getFullYear()}-${String(kst.getMonth() + 1).padStart(2, "0")}-${String(kst.getDate()).padStart(2, "0")}`;
      if (dateStr !== filterDate) return false;
    }
    if (filterHour) {
      if (String(kst.getHours()).padStart(2, "0") !== filterHour) return false;
    }
    return true;
  };

  // 필터 + 정렬 적용
  const hasDateTimeFilter = filterDate !== "" || filterHour !== "";
  const hasSnapshotFilter = hasDateTimeFilter || filterQuantity !== "" || priceMin !== "" || priceMax !== "";
  const hasChartFilter = hasDateTimeFilter || filterQuantity !== ""; // 차트용: 단가 필터 제외
  // 리스트 기본 상한: 사용자가 단가 이하 필터를 안 걸었으면 API 기준가 적용
  const effectivePriceMax = priceMax !== "" ? priceMax : thresholdPrice;

  const belowList = belowListRaw
    .map((r: any) => {
      const snaps: any[] = Array.isArray(r?.snapshots) ? r.snapshots : [];
      // 스냅샷 레벨에서 날짜/시간/수량/단가 필터 적용 (기준가 기본 상한 항상 적용)
      const filtered = snaps.filter((s: any) => {
        if (!matchesDateTime(s?.time)) return false;
        if (filterQuantity !== "" && (s?.quantity ?? 0) !== filterQuantity) return false;
        if (priceMin !== "" && (s?.unit_price ?? 0) < priceMin) return false;
        if ((s?.unit_price ?? 0) > effectivePriceMax) return false;
        return true;
      });
      if (filtered.length === 0) return null;
      const minSnap = filtered.reduce((a: any, b: any) => (a.unit_price <= b.unit_price ? a : b));
      return { ...r, ...minSnap, snapshots: filtered };
    })
    .filter((r: any) => {
      if (!r) return false;
      return true;
    })
    .sort((a: any, b: any) =>
      sortOrder === "asc"
        ? (a?.unit_price ?? 0) - (b?.unit_price ?? 0)
        : (b?.unit_price ?? 0) - (a?.unit_price ?? 0),
    );

  // 날짜 목록 (필터 드롭다운용)
  const availableDates = React.useMemo(() => {
    const dates = new Set<string>();
    for (const r of belowListRaw) {
      for (const s of (r?.snapshots || [])) {
        if (!s?.time) continue;
        const d = new Date(s.time);
        if (Number.isNaN(d.getTime())) continue;
        const kst = new Date(d.toLocaleString("en-US", { timeZone: "Asia/Seoul" }));
        dates.add(`${kst.getFullYear()}-${String(kst.getMonth() + 1).padStart(2, "0")}-${String(kst.getDate()).padStart(2, "0")}`);
      }
    }
    return [...dates].sort();
  }, [belowListRaw]);

  const availableHours = React.useMemo(() => {
    const hours = new Set<string>();
    for (const r of belowListRaw) {
      for (const s of (r?.snapshots || [])) {
        if (!s?.time) continue;
        const d = new Date(s.time);
        if (Number.isNaN(d.getTime())) continue;
        const kst = new Date(d.toLocaleString("en-US", { timeZone: "Asia/Seoul" }));
        hours.add(String(kst.getHours()).padStart(2, "0"));
      }
    }
    return [...hours].sort();
  }, [belowListRaw]);

  const sellerCardsRaw: any[] = Array.isArray(data?.seller_cards)
    ? data.seller_cards
    : [];

  // 차트용 스냅샷: 날짜/시간/수량 필터만 적용 (단가 필터 제외)
  const chartSnapsBySellerRaw = React.useMemo(() => {
    if (!hasChartFilter) return null; // null이면 서버 원본 사용
    const map = new Map<string, any[]>();
    for (const r of belowListRaw) {
      const snaps: any[] = Array.isArray(r?.snapshots) ? r.snapshots : [];
      const key = `${r.seller_name}||${r.platform}`;
      const filtered = snaps.filter((s: any) => {
        if (!matchesDateTime(s?.time)) return false;
        if (filterQuantity !== "" && (s?.quantity ?? 0) !== filterQuantity) return false;
        return true;
      });
      const prev = map.get(key) || [];
      map.set(key, [...prev, ...filtered]);
    }
    return map;
  }, [belowListRaw, hasChartFilter, filterDate, filterHour, filterQuantity]);

  // 필터링된 belowList에 존재하는 셀러만 카드에 표시 + 차트는 단가 필터 제외
  const filteredSellerCards = React.useMemo(() => {
    // belowList에서 셀러별 최저가 정보 구성
    const sellerInfoMap = new Map<string, any>();
    for (const r of belowList) {
      const key = `${r.seller_name}||${r.platform}`;
      const existing = sellerInfoMap.get(key);
      if (!existing || r.unit_price < existing.unit_price) {
        sellerInfoMap.set(key, r);
      }
    }

    // 스냅샷 → chart_data 포맷 변환
    const buildChartFromSnaps = (snaps: any[]) => {
      const bucketMap = new Map<string, number>();
      for (const s of snaps) {
        if (!s?.time || !s?.unit_price) continue;
        const d = new Date(s.time);
        if (Number.isNaN(d.getTime())) continue;
        const kst = new Date(d.toLocaleString("en-US", { timeZone: "Asia/Seoul" }));
        const dateStr = `${kst.getFullYear()}-${String(kst.getMonth() + 1).padStart(2, "0")}-${String(kst.getDate()).padStart(2, "0")}`;
        const timeStr = `${String(kst.getHours()).padStart(2, "0")}:${String(kst.getMinutes()).padStart(2, "0")}`;
        const bucketKey = `${dateStr}||${timeStr}`;
        const prev = bucketMap.get(bucketKey);
        if (prev === undefined || s.unit_price < prev) {
          bucketMap.set(bucketKey, s.unit_price);
        }
      }
      return Array.from(bucketMap.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, minPrice]) => {
          const [date, time] = k.split("||");
          return { date, time, min_price: minPrice };
        });
    };

    return sellerCardsRaw
      .filter((c: any) => sellerInfoMap.has(`${c.seller_name}||${c.platform}`))
      .filter((c: any) =>
        selectedCardSellers.size === 0 || selectedCardSellers.has(`${c.seller_name}||${c.platform}`),
      )
      .map((c: any) => {
        const key = `${c.seller_name}||${c.platform}`;
        const info = sellerInfoMap.get(key);
        const updated = {
          ...c,
          min_unit_price: info?.unit_price ?? c.min_unit_price,
          quantity: info?.quantity ?? c.quantity,
          total_price: info?.total_price ?? c.total_price,
          min_time: info?.time ?? c.min_time,
        };
        // 차트 필터(날짜/시간/수량) 없으면 서버 원본 chart_data 사용
        if (!chartSnapsBySellerRaw) return updated;
        // 차트 필터 있으면 단가 제외한 필터로 차트 재구성
        const snaps = chartSnapsBySellerRaw.get(key) || [];
        const chartData = buildChartFromSnaps(snaps);
        return { ...updated, chart_data: chartData };
      })
      .filter(Boolean);
  }, [sellerCardsRaw, belowList, chartSnapsBySellerRaw, selectedCardSellers]);

  // 셀러 카드 필터에 표시할 셀러 목록 (belowList 기준 필터 적용 후 남은 셀러들)
  const availableCardSellers = React.useMemo(() => {
    const visibleSellers = new Set(
      belowList.map((r: any) => `${r.seller_name}||${r.platform}`),
    );
    return sellerCardsRaw
      .filter((c: any) => visibleSellers.has(`${c.seller_name}||${c.platform}`))
      .map((c: any) => ({
        key: `${c.seller_name}||${c.platform}`,
        label: `${c.seller_name} (${c.platform})`,
      }));
  }, [sellerCardsRaw, belowList]);

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <style dangerouslySetInnerHTML={{ __html: printStyles }} />
      <h2 style={{ marginBottom: 16 }}>기간별 리포트</h2>

      {/* 입력 폼 */}
      <div
        className="no-print"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
          gap: 12,
          alignItems: "end",
          padding: 16,
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          marginBottom: 16,
        }}
      >
        <div>
          <label style={{ fontSize: 12 }}>시작일</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            style={inputStyle}
          />
        </div>

        <div>
          <label style={{ fontSize: 12 }}>종료일</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            style={inputStyle}
          />
        </div>

        <div>
          <label style={{ fontSize: 12 }}>기준가 (API 조회용)</label>
          <input
            type="number"
            value={thresholdPrice}
            onChange={(e) => setThresholdPrice(Number(e.target.value))}
            style={inputStyle}
          />
        </div>

        <div>
          <label style={{ fontSize: 12 }}>채널</label>
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as any)}
            style={inputStyle}
          >
            <option value="naver">naver</option>
            <option value="coupang">coupang</option>
            <option value="all">all (naver + coupang)</option>
          </select>
        </div>

        <div>
          <button
            onClick={onFetch}
            disabled={loading}
            style={{
              width: "100%",
              padding: "10px 14px",
              borderRadius: 10,
              border: "1px solid #111827",
              background: "#111827",
              color: "white",
              cursor: "pointer",
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? "불러오는 중..." : "리포트 조회"}
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            padding: 12,
            borderRadius: 12,
            border: "1px solid #fecaca",
            background: "#fef2f2",
            color: "#991b1b",
            marginBottom: 16,
          }}
        >
          {error}
        </div>
      )}

      {!data && !loading && (
        <div style={{ opacity: 0.7 }}>
          리포트 조회를 눌러 데이터를 불러오세요.
        </div>
      )}

      {data && (
        <div>
          {/* 인쇄/PDF 버튼 */}
          <div className="no-print" style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
            <button
              onClick={() => window.print()}
              style={{
                padding: "8px 18px",
                borderRadius: 10,
                border: "1px solid #d1d5db",
                background: "#fff",
                cursor: "pointer",
                fontSize: 13,
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              PDF 다운로드 / 인쇄
            </button>
          </div>
          <div id="range-report-printable">
            {/* 인쇄용 헤더 */}
            <div style={{ display: "none" }} className="print-header">
              <h2>기간별 리포트</h2>
              <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 12 }}>
                {startDate} ~ {endDate} | 기준가: {fmtMoney(thresholdPrice)} | 채널: {channel}
              </div>
            </div>
            {/* ① Summary */}
            <div style={sectionCard}>
              <h3 style={{ marginTop: 0 }}>① 요약 (Summary)</h3>

              <div
                style={{
                  border: "1px solid #e5e7eb",
                  borderRadius: 12,
                  padding: 12,
                  background: "#fafafa",
                }}
              >
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  <li>
                    기준가 이하 셀러 수:{" "}
                    <b>{summary?.below_threshold_seller_count ?? 0}곳</b>
                  </li>
                  <li>
                    최저 단가:{" "}
                    <b>{fmtMoney(summary?.global_min_price)}</b>
                    {summary?.global_min_seller && (
                      <> ({summary.global_min_seller})</>
                    )}
                    {summary?.global_min_time && (
                      <> / {fmtTime(summary.global_min_time)}</>
                    )}
                  </li>
                </ul>

                {Array.isArray(summary?.top5_lowest) &&
                  summary.top5_lowest.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <div style={{ fontWeight: 700, marginBottom: 6 }}>
                        최저가격 상위 5개 거래처
                      </div>
                      <table
                        style={{ width: "100%", borderCollapse: "collapse" }}
                      >
                        <thead>
                          <tr>
                            {["거래처명", "최저 단가", "시점", "플랫폼"].map((h) => (
                              <th
                                key={h}
                                style={{
                                  textAlign: "left",
                                  fontSize: 12,
                                  padding: "6px 6px",
                                  borderBottom: "1px solid #e5e7eb",
                                }}
                              >
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {summary.top5_lowest.map((item: any, i: number) => (
                            <tr key={i}>
                              <td
                                style={{
                                  padding: "6px",
                                  borderBottom: "1px solid #f3f4f6",
                                }}
                              >
                                {item?.seller_name ?? item?.seller ?? "-"}
                              </td>
                              <td
                                style={{
                                  padding: "6px",
                                  borderBottom: "1px solid #f3f4f6",
                                }}
                              >
                                {fmtMoney(
                                  item?.min_unit_price ?? item?.min_price,
                                )}
                              </td>
                              <td
                                style={{
                                  padding: "6px",
                                  borderBottom: "1px solid #f3f4f6",
                                  fontSize: 12,
                                  whiteSpace: "nowrap",
                                }}
                              >
                                {fmtTime(item?.min_time)}
                              </td>
                              <td
                                style={{
                                  padding: "6px",
                                  borderBottom: "1px solid #f3f4f6",
                                }}
                              >
                                {item?.platform ?? "-"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
              </div>
            </div>

            {/* ② 기준가 이하 리스트 */}
            <div style={sectionCard}>
              <h3 style={{ marginTop: 0 }}>② 기준가 이하 리스트</h3>

              {/* 필터 바 */}
              <div
                style={{
                  display: "flex",
                  gap: 12,
                  alignItems: "end",
                  marginBottom: 12,
                  flexWrap: "wrap",
                }}
              >
                <div>
                  <label style={{ fontSize: 11, color: "#6b7280" }}>단가 이상</label>
                  <input
                    type="number"
                    placeholder="최소"
                    value={priceMin}
                    onChange={(e) => setPriceMin(e.target.value === "" ? "" : Number(e.target.value))}
                    style={{ ...inputStyle, width: 100, padding: 6, fontSize: 13 }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, color: "#6b7280" }}>단가 이하</label>
                  <input
                    type="number"
                    placeholder="최대"
                    value={priceMax}
                    onChange={(e) => setPriceMax(e.target.value === "" ? "" : Number(e.target.value))}
                    style={{ ...inputStyle, width: 100, padding: 6, fontSize: 13 }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, color: "#6b7280" }}>수량</label>
                  <select
                    value={filterQuantity}
                    onChange={(e) => setFilterQuantity(e.target.value === "" ? "" : Number(e.target.value))}
                    style={{ ...inputStyle, width: 80, padding: 6, fontSize: 13 }}
                  >
                    <option value="">전체</option>
                    {[1, 2, 3, 4, 5, 6, 7].map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: 11, color: "#6b7280" }}>날짜</label>
                  <select
                    value={filterDate}
                    onChange={(e) => setFilterDate(e.target.value)}
                    style={{ ...inputStyle, width: 140, padding: 6, fontSize: 13 }}
                  >
                    <option value="">전체</option>
                    {availableDates.map((d) => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: 11, color: "#6b7280" }}>시간</label>
                  <select
                    value={filterHour}
                    onChange={(e) => setFilterHour(e.target.value)}
                    style={{ ...inputStyle, width: 80, padding: 6, fontSize: 13 }}
                  >
                    <option value="">전체</option>
                    {availableHours.map((h) => (
                      <option key={h} value={h}>{h}시</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: 11, color: "#6b7280" }}>단가 정렬</label>
                  <select
                    value={sortOrder}
                    onChange={(e) => setSortOrder(e.target.value as "asc" | "desc")}
                    style={{ ...inputStyle, width: 100, padding: 6, fontSize: 13 }}
                  >
                    <option value="asc">오름차순</option>
                    <option value="desc">내림차순</option>
                  </select>
                </div>
                <div style={{ fontSize: 12, color: "#6b7280", paddingBottom: 4 }}>
                  {belowList.length}건 / {belowListRaw.length}건
                </div>
              </div>

              {belowList.length === 0 ? (
                <div>(기준가 이하 셀러 없음)</div>
              ) : (
                <div style={{ overflow: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr>
                        {["", "판매처", "채널", "최저 단가", "총 금액", "수량", "시점", "카드"].map((h) => (
                          <th
                            key={h}
                            style={{
                              textAlign: "left",
                              fontSize: 12,
                              padding: "8px 6px",
                              borderBottom: "1px solid #e5e7eb",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {belowList.map((r: any, i: number) => {
                        const isExpanded = expandedSellers.has(i);
                        const snapshots: any[] = Array.isArray(r?.snapshots) ? r.snapshots : [];
                        const hasSnapshots = snapshots.length > 0;
                        const toggleExpand = () => {
                          setExpandedSellers((prev) => {
                            const next = new Set(prev);
                            if (next.has(i)) next.delete(i);
                            else next.add(i);
                            return next;
                          });
                        };

                        const renderCardCell = (item: any, key: string) => {
                          const thumb = item?.image_url || item?.card_image_path;
                          const hasData = item?.product_name || item?.unit_price;
                          return (
                            <td style={{ padding: "8px 6px", borderBottom: "1px solid #f3f4f6" }}>
                              {(thumb || hasData) ? (
                                <button
                                  type="button"
                                  onClick={(e) => { e.stopPropagation(); setModalItem(item); }}
                                  style={{
                                    display: "inline-flex",
                                    border: "1px solid #e5e7eb",
                                    borderRadius: 6,
                                    padding: 2,
                                    background: "white",
                                    cursor: "pointer",
                                  }}
                                >
                                  <img
                                    src={thumb || "/placeholder.png"}
                                    alt="evidence"
                                    style={{ width: 80, height: 48, objectFit: "cover", borderRadius: 4 }}
                                  />
                                </button>
                              ) : item?.link ? (
                                <a href={item.link} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>링크</a>
                              ) : (
                                "-"
                              )}
                            </td>
                          );
                        };

                        return (
                          <React.Fragment key={i}>
                            {/* 셀러 요약 행 */}
                            <tr
                              style={{ background: isExpanded ? "#f8fafc" : undefined, cursor: hasSnapshots ? "pointer" : undefined }}
                              onClick={hasSnapshots ? toggleExpand : undefined}
                            >
                              <td style={{ padding: "8px 6px", borderBottom: "1px solid #f3f4f6", width: 28 }}>
                                {hasSnapshots && (
                                  <span style={{ fontSize: 12, color: "#6b7280" }}>
                                    {isExpanded ? "▼" : "▶"}
                                  </span>
                                )}
                              </td>
                              <td style={{ padding: "8px 6px", borderBottom: "1px solid #f3f4f6", fontWeight: 600 }}>
                                {r?.seller_name ?? "-"}
                                {hasSnapshots && (
                                  <span style={{ fontSize: 11, color: "#9ca3af", marginLeft: 4 }}>
                                    ({snapshots.length})
                                  </span>
                                )}
                              </td>
                              <td style={{ padding: "8px 6px", borderBottom: "1px solid #f3f4f6" }}>
                                {r?.platform ?? "-"}
                              </td>
                              <td style={{ padding: "8px 6px", borderBottom: "1px solid #f3f4f6", whiteSpace: "nowrap", fontWeight: 700 }}>
                                {fmtMoney(r?.unit_price)}
                              </td>
                              <td style={{ padding: "8px 6px", borderBottom: "1px solid #f3f4f6", whiteSpace: "nowrap" }}>
                                {fmtMoney(r?.total_price)}
                              </td>
                              <td style={{ padding: "8px 6px", borderBottom: "1px solid #f3f4f6" }}>
                                {r?.quantity ?? "-"}
                              </td>
                              <td style={{ padding: "8px 6px", borderBottom: "1px solid #f3f4f6", whiteSpace: "nowrap", fontSize: 12 }}>
                                {fmtTime(r?.time)}
                              </td>
                              {renderCardCell(r, `summary-${i}`)}
                            </tr>

                            {/* 스냅샷 행들 (토글 열렸을 때) */}
                            {isExpanded && snapshots.map((s: any, si: number) => (
                              <tr
                                key={`${i}-${si}`}
                                style={{ background: "#f1f5f9" }}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <td style={{ padding: "6px 6px", borderBottom: "1px solid #e2e8f0" }} />
                                <td style={{ padding: "6px 6px", borderBottom: "1px solid #e2e8f0", fontSize: 12, color: "#64748b", paddingLeft: 20 }}>
                                  {s?.product_name || s?.seller_name || "-"}
                                </td>
                                <td style={{ padding: "6px 6px", borderBottom: "1px solid #e2e8f0", fontSize: 12 }}>
                                  {s?.platform ?? "-"}
                                </td>
                                <td style={{ padding: "6px 6px", borderBottom: "1px solid #e2e8f0", fontSize: 12, whiteSpace: "nowrap" }}>
                                  {fmtMoney(s?.unit_price)}
                                </td>
                                <td style={{ padding: "6px 6px", borderBottom: "1px solid #e2e8f0", fontSize: 12, whiteSpace: "nowrap" }}>
                                  {fmtMoney(s?.total_price)}
                                </td>
                                <td style={{ padding: "6px 6px", borderBottom: "1px solid #e2e8f0", fontSize: 12 }}>
                                  {s?.quantity ?? "-"}
                                </td>
                                <td style={{ padding: "6px 6px", borderBottom: "1px solid #e2e8f0", fontSize: 11, whiteSpace: "nowrap", color: "#64748b" }}>
                                  {fmtTime(s?.time)}
                                </td>
                                {renderCardCell(s, `snap-${i}-${si}`)}
                              </tr>
                            ))}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* ③ 셀러별 상세 카드 */}
            <div style={sectionCard}>
              <h3 style={{ marginTop: 0 }}>③ 셀러별 상세 카드</h3>

              {/* 셀러 선택 필터 */}
              {availableCardSellers.length > 0 && (
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 6,
                    marginBottom: 14,
                    alignItems: "center",
                  }}
                >
                  <span style={{ fontSize: 13, fontWeight: 600, marginRight: 4 }}>
                    셀러 필터:
                  </span>
                  <button
                    onClick={() => setSelectedCardSellers(new Set())}
                    style={{
                      padding: "4px 10px",
                      fontSize: 12,
                      borderRadius: 16,
                      border: "1px solid #d1d5db",
                      background: selectedCardSellers.size === 0 ? "#2563eb" : "#fff",
                      color: selectedCardSellers.size === 0 ? "#fff" : "#374151",
                      cursor: "pointer",
                      fontWeight: 600,
                    }}
                  >
                    전체
                  </button>
                  {availableCardSellers.map((s) => {
                    const active = selectedCardSellers.has(s.key);
                    return (
                      <button
                        key={s.key}
                        onClick={() => {
                          setSelectedCardSellers((prev) => {
                            const next = new Set(prev);
                            if (active) {
                              next.delete(s.key);
                            } else {
                              next.add(s.key);
                            }
                            return next;
                          });
                        }}
                        style={{
                          padding: "4px 10px",
                          fontSize: 12,
                          borderRadius: 16,
                          border: "1px solid #d1d5db",
                          background: active ? "#2563eb" : "#fff",
                          color: active ? "#fff" : "#374151",
                          cursor: "pointer",
                        }}
                      >
                        {s.label}
                      </button>
                    );
                  })}
                </div>
              )}

              {filteredSellerCards.length === 0 ? (
                <div>(셀러 카드 없음)</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                  {filteredSellerCards.map((c: any, i: number) => (
                    <div
                      key={i}
                      style={{
                        border: "1px solid #e5e7eb",
                        borderRadius: 12,
                        padding: 16,
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          marginBottom: 12,
                        }}
                      >
                        <div style={{ fontWeight: 800, fontSize: 15 }}>
                          {c?.seller_name ?? `seller ${i + 1}`}{" "}
                          <span style={{ fontWeight: 500, opacity: 0.7 }}>
                            ({c?.platform ?? "-"})
                          </span>
                        </div>
                        <div style={{ fontSize: 13, opacity: 0.8 }}>
                          최저 {fmtMoney(c?.min_unit_price)}
                          {c?.min_time && <> / {fmtTime(c.min_time)}</>}
                        </div>
                      </div>

                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "1fr 1fr 1fr",
                          gap: 8,
                          fontSize: 13,
                          marginBottom: 12,
                        }}
                      >
                        <div>
                          금액: <b>{fmtMoney(c?.total_price)}</b>
                        </div>
                        <div>
                          수량: <b>{c?.quantity ?? "-"}</b>
                        </div>
                        <div>
                          {c?.link ? (
                            <a
                              href={c.link}
                              target="_blank"
                              rel="noreferrer"
                            >
                              상품 링크
                            </a>
                          ) : c?.card_image_path ? (
                            <a
                              href={`${API_BASE_URL}/${c.card_image_path}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              캡쳐본
                            </a>
                          ) : (
                            <span style={{ opacity: 0.5 }}>링크 없음</span>
                          )}
                        </div>
                      </div>

                      {/* 일별 최저가 차트 */}
                      {Array.isArray(c?.chart_data) &&
                        c.chart_data.length > 0 && (
                          <div>
                            <div
                              style={{
                                fontWeight: 700,
                                fontSize: 13,
                                marginBottom: 8,
                              }}
                            >
                              일별 최저가 추이
                            </div>
                            <ResponsiveContainer width="100%" height={200}>
                              <LineChart
                                data={c.chart_data.map((p: any, idx: number) => ({
                                  ...p,
                                  _index: idx,
                                }))}
                              >
                                <CartesianGrid
                                  strokeDasharray="3 3"
                                  stroke="#e5e7eb"
                                />
                                <XAxis
                                  dataKey="_index"
                                  tick={{ fontSize: 11 }}
                                  tickFormatter={(idx: number) => {
                                    const point = c.chart_data[idx];
                                    if (!point) return "";
                                    const prev = idx > 0 ? c.chart_data[idx - 1] : null;
                                    if (!prev || prev.date !== point.date) return point.date.replace(/^\d{2}/, "");
                                    return "";
                                  }}
                                  interval={0}
                                />
                                <YAxis
                                  tick={{ fontSize: 11 }}
                                  tickFormatter={(v: number) =>
                                    `${(v / 1000).toFixed(0)}k`
                                  }
                                  domain={["dataMin - 1000", "dataMax + 1000"]}
                                />
                                <Tooltip
                                  labelFormatter={(idx: number) => {
                                    const point = c.chart_data[idx];
                                    return point ? (point.time ? `${point.date} ${point.time}` : point.date) : "";
                                  }}
                                  formatter={(v: number) => [
                                    fmtMoney(v),
                                    "최저 단가",
                                  ]}
                                />
                                <Line
                                  type="monotone"
                                  dataKey="min_price"
                                  stroke="#2563eb"
                                  strokeWidth={2}
                                  dot={{ r: 2 }}
                                  activeDot={{ r: 4 }}
                                />
                              </LineChart>
                            </ResponsiveContainer>

                            {/* 기준가 라인 표시 */}
                            <div
                              style={{
                                fontSize: 11,
                                color: "#6b7280",
                                textAlign: "right",
                                marginTop: 4,
                              }}
                            >
                              기준가: {fmtMoney(thresholdPrice)}
                            </div>
                          </div>
                        )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {/* Evidence 카드 모달 — 메인 HtmlCardModal과 동일한 UI */}
      {modalItem && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
          style={{ overflowY: "scroll" }}
          onClick={() => setModalItem(null)}
        >
          <div
            className="w-full max-w-5xl rounded-2xl bg-white p-4 shadow-2xl md:p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <div className="text-base font-semibold text-slate-900">HTML 카드 보기</div>
              <button
                type="button"
                onClick={() => setModalItem(null)}
                className="rounded-lg border border-slate-200 px-3 py-1 text-sm text-slate-700 hover:bg-slate-50"
              >
                닫기
              </button>
            </div>

            <div className="grid gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-[300px_1fr]">
              <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                <img
                  src={modalItem.image_url || modalItem.card_image_path || "/placeholder.png"}
                  alt="evidence"
                  className="h-full w-full object-contain"
                />
              </div>
              <div className="space-y-3">
                <div className="text-xl font-bold leading-snug text-slate-900">
                  {modalItem.product_name || "-"}
                </div>
                <div className="text-sm text-slate-600">
                  판매처: {modalItem.seller_name || "-"}
                </div>
                <div className="flex items-end gap-2">
                  <span className="text-3xl font-extrabold text-slate-900">
                    {Number(modalItem.unit_price || 0).toLocaleString("ko-KR")}
                  </span>
                  <span className="pb-1 text-base font-semibold text-slate-500">원/개</span>
                </div>
                <div className="grid grid-cols-[110px_1fr] gap-y-2 text-sm">
                  <div className="text-slate-500">총 가격</div>
                  <div className="font-semibold text-slate-900">
                    {fmtMoney(modalItem.total_price)}
                  </div>
                  <div className="text-slate-500">수량</div>
                  <div className="font-semibold text-slate-900">{modalItem.quantity || 0}개</div>
                  <div className="text-slate-500">계산 방식</div>
                  <div className="font-semibold text-slate-900">{modalItem.calc_method || "-"}</div>
                  <div className="text-slate-500">생성 시각</div>
                  <div className="font-semibold text-slate-900">{fmtTime(modalItem.time)}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2 pt-2">
                  {modalItem.link && (
                    <a
                      href={modalItem.link}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white no-underline hover:bg-slate-700"
                    >
                      원문 바로가기
                    </a>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
