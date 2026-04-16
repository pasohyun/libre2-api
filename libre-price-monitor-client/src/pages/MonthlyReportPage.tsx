// src/pages/MonthlyReportPage.tsx
import React, { useMemo, useState } from "react";
import { getMonthlyReport } from "../api/reports";

type ReportData = any;

const nowYYYYMM = () => {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
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
    // KST로 보기 좋게
    return d.toLocaleString("ko-KR", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(v);
  }
};

export default function MonthlyReportPage() {
  const [month, setMonth] = useState(nowYYYYMM());
  const [thresholdPrice, setThresholdPrice] = useState(85000);
  const [channel, setChannel] = useState<"naver" | "coupang" | "all">("naver");
  const [crawlSchedule, setCrawlSchedule] = useState("00/12");
  const [topCards, setTopCards] = useState(10);
  const [useLlm, setUseLlm] = useState(true);
  const [store, setStore] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ReportData | null>(null);

  const prettyJson = useMemo(
    () => (data ? JSON.stringify(data, null, 2) : ""),
    [data],
  );

  const onFetch = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getMonthlyReport({
        month,
        threshold_price: thresholdPrice,
        channel,
        crawl_schedule: crawlSchedule,
        top_cards: topCards,
        use_llm: useLlm,
        store,
      });
      setData(res);
    } catch (e: any) {
      setError(e?.message ?? "Unknown error");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const conclusion = data?.conclusion || {};
  const priorityList = Array.isArray(data?.priority_list)
    ? data.priority_list
    : [];
  const sellerCards = Array.isArray(data?.seller_cards)
    ? data.seller_cards
    : [];
  const patterns = Array.isArray(data?.patterns) ? data.patterns : [];
  const dataQuality = data?.data_quality || {};
  const execSummary =
    data?.llm?.executive_summary ??
    data?.llm?.summary ?? // 혹시 예전 호환
    null;

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <h2 style={{ marginBottom: 16 }}>월간 LLM 리포트</h2>

      {/* 입력 폼 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(6, minmax(0, 1fr))",
          gap: 12,
          alignItems: "end",
          padding: 16,
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          marginBottom: 16,
        }}
      >
        <div style={{ gridColumn: "span 2" }}>
          <label style={{ fontSize: 12 }}>month (YYYY-MM)</label>
          <input
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            placeholder="2026-02"
            style={{
              width: "100%",
              padding: 10,
              borderRadius: 10,
              border: "1px solid #d1d5db",
            }}
          />
        </div>

        <div>
          <label style={{ fontSize: 12 }}>threshold_price</label>
          <input
            type="number"
            value={thresholdPrice}
            onChange={(e) => setThresholdPrice(Number(e.target.value))}
            style={{
              width: "100%",
              padding: 10,
              borderRadius: 10,
              border: "1px solid #d1d5db",
            }}
          />
        </div>

        <div>
          <label style={{ fontSize: 12 }}>channel</label>
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as any)}
            style={{
              width: "100%",
              padding: 10,
              borderRadius: 10,
              border: "1px solid #d1d5db",
            }}
          >
            <option value="naver">naver</option>
            <option value="coupang">coupang</option>
            <option value="all">all (naver + coupang)</option>
          </select>
        </div>

        <div>
          <label style={{ fontSize: 12 }}>crawl_schedule</label>
          <input
            value={crawlSchedule}
            onChange={(e) => setCrawlSchedule(e.target.value)}
            placeholder="00/12"
            style={{
              width: "100%",
              padding: 10,
              borderRadius: 10,
              border: "1px solid #d1d5db",
            }}
          />
        </div>

        <div>
          <label style={{ fontSize: 12 }}>top_cards</label>
          <input
            type="number"
            value={topCards}
            onChange={(e) => setTopCards(Number(e.target.value))}
            style={{
              width: "100%",
              padding: 10,
              borderRadius: 10,
              border: "1px solid #d1d5db",
            }}
          />
        </div>

        <div
          style={{
            gridColumn: "span 6",
            display: "flex",
            gap: 16,
            alignItems: "center",
          }}
        >
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={useLlm}
              onChange={(e) => setUseLlm(e.target.checked)}
            />
            use_llm
          </label>

          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={store}
              onChange={(e) => setStore(e.target.checked)}
            />
            store
          </label>

          <button
            onClick={onFetch}
            disabled={loading}
            style={{
              marginLeft: "auto",
              padding: "10px 14px",
              borderRadius: 10,
              border: "1px solid #111827",
              background: "#111827",
              color: "white",
              cursor: "pointer",
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? "불러오는 중..." : "리포트 생성/조회"}
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

      {!data && (
        <div style={{ opacity: 0.7 }}>
          리포트 생성/조회를 눌러 데이터를 불러오세요.
        </div>
      )}

      {data && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1.25fr 0.75fr",
            gap: 16,
          }}
        >
          {/* 왼쪽: 리포트(①~⑤) */}
          <div
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 12,
              padding: 16,
            }}
          >
            {/* ① 이번 달 결론 요약 */}
            <h3 style={{ marginTop: 0 }}>① 이번 달 결론 요약</h3>

            <div style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>LLM 요약</div>
              <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {execSummary ??
                  "(요약 없음 - OPENAI_API_KEY 또는 use_llm 확인)"}
              </pre>
            </div>

            <div
              style={{
                border: "1px solid #e5e7eb",
                borderRadius: 12,
                padding: 12,
                background: "#fafafa",
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: 8 }}>
                집계(확정 숫자)
              </div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                <li>
                  기준가 이하 셀러:{" "}
                  <b>
                    {conclusion?.has_below_threshold_seller ? "있음" : "없음"}
                  </b>
                </li>
                <li>
                  문제 셀러 총 <b>{conclusion?.problem_seller_count ?? 0}</b>곳
                </li>
                <li>
                  최저 단가 / 발생 시점:{" "}
                  <b>{fmtMoney(conclusion?.global_min_unit_price)}</b> /{" "}
                  {fmtTime(conclusion?.global_min_time)}
                </li>
                <li>
                  반복 패턴 여부(관측 범위 내):{" "}
                  <b>{conclusion?.repeat_pattern_observed ? "있음" : "없음"}</b>
                </li>
              </ul>
            </div>

            <hr style={{ margin: "16px 0" }} />

            {/* ② 우선순위 리스트 */}
            <h3 style={{ marginTop: 0 }}>② 기준가 이하 셀러 우선순위 리스트</h3>
            {priorityList.length === 0 ? (
              <div>(기준가 이하 셀러 없음)</div>
            ) : (
              <div style={{ overflow: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {[
                        "셀러명",
                        "플랫폼",
                        "미만/전체",
                        "최저 단가(시점)",
                        "최근 발생 시점",
                        "대표 링크",
                      ].map((h) => (
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
                    {priorityList.map((r: any, i: number) => (
                      <tr key={i}>
                        <td
                          style={{
                            padding: "8px 6px",
                            borderBottom: "1px solid #f3f4f6",
                          }}
                        >
                          {r?.seller_name_std ?? "-"}
                        </td>
                        <td
                          style={{
                            padding: "8px 6px",
                            borderBottom: "1px solid #f3f4f6",
                          }}
                        >
                          {r?.platform ?? "-"}
                        </td>
                        <td
                          style={{
                            padding: "8px 6px",
                            borderBottom: "1px solid #f3f4f6",
                          }}
                        >
                          <b>{r?.below_threshold_count ?? 0}</b> /{" "}
                          {r?.observations ?? 0}
                        </td>
                        <td
                          style={{
                            padding: "8px 6px",
                            borderBottom: "1px solid #f3f4f6",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {fmtMoney(r?.min_unit_price)} ({fmtTime(r?.min_time)})
                        </td>
                        <td
                          style={{
                            padding: "8px 6px",
                            borderBottom: "1px solid #f3f4f6",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {fmtTime(r?.last_below_time)}
                        </td>
                        <td
                          style={{
                            padding: "8px 6px",
                            borderBottom: "1px solid #f3f4f6",
                          }}
                        >
                          {r?.representative_link ? (
                            <a
                              href={r.representative_link}
                              target="_blank"
                              rel="noreferrer"
                            >
                              링크
                            </a>
                          ) : (
                            "-"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <hr style={{ margin: "16px 0" }} />

            {/* ③ 셀러별 상세 카드 */}
            <h3 style={{ marginTop: 0 }}>
              ③ 셀러별 상세 카드 (Top {topCards})
            </h3>
            {sellerCards.length === 0 ? (
              <div>(셀러 카드 없음)</div>
            ) : (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                  gap: 12,
                }}
              >
                {sellerCards.map((c: any, i: number) => (
                  <div
                    key={i}
                    style={{
                      border: "1px solid #e5e7eb",
                      borderRadius: 12,
                      padding: 12,
                    }}
                  >
                    <div style={{ fontWeight: 800 }}>
                      {c?.seller_name_std ?? `seller ${i + 1}`}{" "}
                      <span style={{ fontWeight: 500, opacity: 0.7 }}>
                        ({c?.platform ?? "-"})
                      </span>
                    </div>

                    <div style={{ marginTop: 8, fontSize: 13 }}>
                      <b>플랫폼별 가격 요약</b>
                      <div style={{ marginTop: 4, opacity: 0.85 }}>
                        상태: {c?.platform_price_summary?.status ?? "-"} /
                        변동성: {c?.platform_price_summary?.volatility ?? "-"}
                      </div>
                    </div>

                    <div style={{ marginTop: 10, fontSize: 13 }}>
                      <b>대표 사례</b>
                      {Array.isArray(c?.representative_cases) &&
                      c.representative_cases.length > 0 ? (
                        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                          {c.representative_cases
                            .slice(0, 3)
                            .map((rc: any, idx: number) => (
                              <li key={idx} style={{ marginBottom: 6 }}>
                                <span style={{ fontWeight: 700 }}>
                                  {rc?.label ?? "case"}
                                </span>
                                :{" "}
                                {rc?.unit_price
                                  ? fmtMoney(rc.unit_price)
                                  : "(가격 미기재)"}{" "}
                                / {fmtTime(rc?.time)}{" "}
                                {rc?.link ? (
                                  <>
                                    {" "}
                                    -{" "}
                                    <a
                                      href={rc.link}
                                      target="_blank"
                                      rel="noreferrer"
                                    >
                                      증빙
                                    </a>
                                  </>
                                ) : null}
                              </li>
                            ))}
                        </ul>
                      ) : (
                        <div style={{ marginTop: 6, opacity: 0.7 }}>
                          (사례 없음)
                        </div>
                      )}
                    </div>

                    <div style={{ marginTop: 10, fontSize: 13 }}>
                      <b>실무자 권고용 문장</b>
                      <pre
                        style={{ whiteSpace: "pre-wrap", margin: "6px 0 0" }}
                      >
                        {c?.recommendation ??
                          "(권고 문장 없음 - use_llm/OPENAI_API_KEY 확인)"}
                      </pre>
                    </div>

                    <div style={{ marginTop: 10, fontSize: 13 }}>
                      <b>증빙 링크</b>
                      <div
                        style={{
                          marginTop: 6,
                          display: "flex",
                          gap: 10,
                          flexWrap: "wrap",
                        }}
                      >
                        {c?.evidence_links?.min_case ? (
                          <a
                            href={c.evidence_links.min_case}
                            target="_blank"
                            rel="noreferrer"
                          >
                            최저가 케이스
                          </a>
                        ) : (
                          <span style={{ opacity: 0.7 }}>최저가 링크 없음</span>
                        )}
                        {c?.evidence_links?.last_below ? (
                          <a
                            href={c.evidence_links.last_below}
                            target="_blank"
                            rel="noreferrer"
                          >
                            최근 이탈
                          </a>
                        ) : (
                          <span style={{ opacity: 0.7 }}>
                            최근 이탈 링크 없음
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <hr style={{ margin: "16px 0" }} />

            {/* ④ 패턴 요약 */}
            <h3 style={{ marginTop: 0 }}>④ 패턴 요약 (관측 기반)</h3>
            {patterns.length === 0 ? (
              <div>(패턴 없음)</div>
            ) : (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {patterns.map((p: any, i: number) => (
                  <li key={i} style={{ marginBottom: 12 }}>
                    <b>{p?.title ?? `pattern ${i + 1}`}</b>
                    <div style={{ marginTop: 4 }}>{p?.description ?? ""}</div>

                    {Array.isArray(p?.evidence_sellers) &&
                      p.evidence_sellers.length > 0 && (
                        <div
                          style={{ marginTop: 6, fontSize: 12, opacity: 0.8 }}
                        >
                          <b>증빙 셀러:</b> {p.evidence_sellers.join(", ")}
                        </div>
                      )}

                    {/* 반드시 caution 노출 */}
                    {p?.caution && (
                      <div
                        style={{ marginTop: 6, fontSize: 12, color: "#92400e" }}
                      >
                        ⚠️ {p.caution}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <hr style={{ margin: "16px 0" }} />

            {/* ⑤ 데이터 품질 */}
            <h3 style={{ marginTop: 0 }}>⑤ 데이터 품질 / 주의 사항</h3>
            <div
              style={{
                border: "1px solid #e5e7eb",
                borderRadius: 12,
                padding: 12,
              }}
            >
              <div style={{ marginBottom: 8 }}>
                단가 계산 <b>확인필요</b> 비율:{" "}
                <b>
                  {(Number(dataQuality?.unclear_calc_ratio ?? 0) * 100).toFixed(
                    2,
                  )}
                  %
                </b>
              </div>

              {Array.isArray(dataQuality?.notes) &&
                dataQuality.notes.length > 0 && (
                  <>
                    <div style={{ fontWeight: 700, marginBottom: 6 }}>
                      주의 사항
                    </div>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {dataQuality.notes.map((n: string, i: number) => (
                        <li key={i}>{n}</li>
                      ))}
                    </ul>
                  </>
                )}

              {Array.isArray(dataQuality?.next_month_improvements) &&
                dataQuality.next_month_improvements.length > 0 && (
                  <>
                    <div
                      style={{
                        fontWeight: 700,
                        marginTop: 12,
                        marginBottom: 6,
                      }}
                    >
                      다음 달 로직 보완 포인트
                    </div>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {dataQuality.next_month_improvements.map(
                        (n: string, i: number) => (
                          <li key={i}>{n}</li>
                        ),
                      )}
                    </ul>
                  </>
                )}

              {Array.isArray(dataQuality?.llm_notes) &&
                dataQuality.llm_notes.length > 0 && (
                  <>
                    <div
                      style={{
                        fontWeight: 700,
                        marginTop: 12,
                        marginBottom: 6,
                      }}
                    >
                      (LLM) 품질 메모
                    </div>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {dataQuality.llm_notes.map((n: string, i: number) => (
                        <li key={i}>{n}</li>
                      ))}
                    </ul>
                  </>
                )}
            </div>
          </div>

          {/* 오른쪽: 원본 JSON */}
          <div
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 12,
              padding: 16,
            }}
          >
            <h3 style={{ marginTop: 0 }}>원본 JSON</h3>
            <pre
              style={{
                fontSize: 12,
                overflow: "auto",
                maxHeight: 780,
                margin: 0,
                background: "#0b1020",
                color: "#d1d5db",
                padding: 12,
                borderRadius: 12,
              }}
            >
              {prettyJson}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
