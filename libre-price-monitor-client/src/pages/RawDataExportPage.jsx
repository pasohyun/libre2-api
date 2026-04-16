// src/pages/RawDataExportPage.jsx
import { useMemo, useState } from "react";
import { authFetch } from "../api/authFetch";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const PRESET_KEY = "raw_export_presets_v1";

function kstTodayYmd() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const y = parts.find((p) => p.type === "year")?.value;
  const m = parts.find((p) => p.type === "month")?.value;
  const d = parts.find((p) => p.type === "day")?.value;
  if (y && m && d) return `${y}-${m}-${d}`;
  return new Date().toISOString().slice(0, 10);
}

function readPresets() {
  try {
    const raw = localStorage.getItem(PRESET_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writePresets(items) {
  localStorage.setItem(PRESET_KEY, JSON.stringify(items));
}

export default function RawDataExportPage() {
  const today = useMemo(() => kstTodayYmd(), []);
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(today);
  const [channel, setChannel] = useState("all");
  const [headerKr, setHeaderKr] = useState(true);
  const [presetName, setPresetName] = useState("");
  const [presets, setPresets] = useState(() => readPresets());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const isYmd = (v) => /^\d{4}-\d{2}-\d{2}$/.test(String(v || "").trim());

  const handleSavePreset = () => {
    const name = (presetName || "").trim();
    if (!name) {
      setError("프리셋 이름을 입력해 주세요.");
      return;
    }
    if (!isYmd(startDate) || !isYmd(endDate)) {
      setError("시작/종료 날짜 형식은 YYYY-MM-DD 입니다.");
      return;
    }
    const next = [
      { name, startDate, endDate, channel, headerKr },
      ...presets.filter((x) => x?.name !== name),
    ].slice(0, 20);
    setPresets(next);
    writePresets(next);
    setError("");
    setPresetName("");
  };

  const applyPreset = (item) => {
    if (!item) return;
    setStartDate(item.startDate || today);
    setEndDate(item.endDate || today);
    setChannel(item.channel || "all");
    setHeaderKr(Boolean(item.headerKr));
    setError("");
  };

  const deletePreset = (name) => {
    const next = presets.filter((x) => x?.name !== name);
    setPresets(next);
    writePresets(next);
  };

  const handleDownload = async () => {
    if (!isYmd(startDate) || !isYmd(endDate)) {
      setError("시작/종료 날짜 형식은 YYYY-MM-DD 입니다.");
      return;
    }
    if (startDate > endDate) {
      setError("종료일은 시작일보다 빠를 수 없습니다.");
      return;
    }

    setError("");
    setLoading(true);
    try {
      const qs = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        channel,
        header_kr: headerKr ? "true" : "false",
      });
      const res = await authFetch(`${API_BASE}/products/export/raw?${qs.toString()}`);
      if (!res.ok) {
        let msg = `요청 실패 (${res.status})`;
        try {
          const j = await res.json();
          if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
        } catch {
          /* ignore */
        }
        throw new Error(msg);
      }

      const blob = await res.blob();
      const autoName = `raw_${channel}_${startDate}_${endDate}_v1.xlsx`;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = autoName;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setError(e?.message || "다운로드에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <div className="text-sm text-slate-500">데이터 추출</div>
        <h1 className="text-2xl font-semibold text-slate-900">
          DB 원본 엑셀 (기간/프리셋)
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          프리셋 저장/재사용, 한글 헤더 변환, 파일명 자동 규칙을 지원합니다.
          파일명 예시:{" "}
          <code className="rounded bg-slate-100 px-1">
            raw_naver_2026-03-01_2026-03-31_v1.xlsx
          </code>
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">시작일 (KST)</span>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">종료일 (KST)</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">채널</span>
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
            >
              <option value="all">전체</option>
              <option value="naver">네이버</option>
              <option value="coupang">쿠팡</option>
              <option value="others">기타</option>
            </select>
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={headerKr}
              onChange={(e) => setHeaderKr(e.target.checked)}
            />
            컬럼 한글 라벨 변환
          </label>
        </div>

        <div className="flex flex-wrap items-end gap-2 border-t border-slate-100 pt-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-700">프리셋 이름</span>
            <input
              type="text"
              value={presetName}
              onChange={(e) => setPresetName(e.target.value)}
              placeholder="예: 월간 보고용"
              className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
            />
          </label>
          <button
            type="button"
            onClick={handleSavePreset}
            className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-900"
          >
            프리셋 저장
          </button>
          <button
            type="button"
            onClick={handleDownload}
            disabled={loading}
            className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {loading ? "생성 중…" : "엑셀 다운로드"}
          </button>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-2">
        <div className="text-sm font-medium text-slate-800">저장된 프리셋</div>
        {presets.length === 0 ? (
          <div className="text-sm text-slate-500">저장된 프리셋이 없습니다.</div>
        ) : (
          presets.map((p) => (
            <div key={p.name} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-100 p-3">
              <div className="text-sm text-slate-700">
                <span className="font-semibold">{p.name}</span>{" "}
                <span className="text-slate-500">
                  ({p.channel}, {p.startDate}~{p.endDate}, 헤더:{p.headerKr ? "한글" : "영문"})
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => applyPreset(p)}
                  className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-sm"
                >
                  적용
                </button>
                <button
                  type="button"
                  onClick={() => deletePreset(p.name)}
                  className="rounded-lg border border-red-200 bg-red-50 px-3 py-1 text-sm text-red-700"
                >
                  삭제
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : null}
    </div>
  );
}
