import React, { useEffect, useState } from "react";
import {
  getAlertConfig,
  putAlertConfig,
  triggerAlertNow,
} from "../api/alerts";

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: 10,
  borderRadius: 10,
  border: "1px solid #d1d5db",
};

export default function AlertSettingsPage() {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [enabled, setEnabled] = useState(false);
  const [recipientEmail, setRecipientEmail] = useState("");
  const [thresholdPrice, setThresholdPrice] = useState(85000);
  const [sourceTime00, setSourceTime00] = useState(true);
  const [sourceTime12, setSourceTime12] = useState(true);
  const [sendTimeKst, setSendTimeKst] = useState("09:00");

  const loadConfig = async () => {
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const conf = await getAlertConfig();
      setEnabled(Boolean(conf.enabled));
      setRecipientEmail(conf.recipient_email || "");
      setThresholdPrice(Number(conf.threshold_price || 85000));
      const times = Array.isArray(conf.source_times_kst) ? conf.source_times_kst : [];
      setSourceTime00(times.includes("00:00"));
      setSourceTime12(times.includes("12:00"));
      setSendTimeKst(conf.send_time_kst || "09:00");
    } catch (e: any) {
      setError(e?.message ?? "설정 로드 실패");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConfig();
  }, []);

  const onSave = async () => {
    setError(null);
    setMessage(null);
    const email = recipientEmail.trim();
    if (!email) {
      setError("수신 이메일을 입력해주세요.");
      return;
    }
    if (!sourceTime00 && !sourceTime12) {
      setError("전일 기준 시각(00:00, 12:00) 중 최소 1개를 선택해주세요.");
      return;
    }
    setSaving(true);
    try {
      const sourceTimes = [sourceTime00 ? "00:00" : "", sourceTime12 ? "12:00" : ""].filter(Boolean);
      await putAlertConfig({
        enabled,
        recipient_email: email,
        threshold_price: thresholdPrice,
        source_times_kst: sourceTimes,
      });
      setMessage("알람 설정이 저장되었습니다.");
    } catch (e: any) {
      setError(e?.message ?? "설정 저장 실패");
    } finally {
      setSaving(false);
    }
  };

  const onTriggerNow = async () => {
    setError(null);
    setMessage(null);
    setTriggering(true);
    try {
      const res = await triggerAlertNow();
      if (res?.status === "sent") {
        setMessage(
          `테스트 발송 완료: ${res.target_date} 기준 ${res.mall_count}개 거래처`,
        );
      } else {
        setMessage(
          `테스트 발송 스킵: ${res?.reason || "unknown"}${res?.target_date ? ` (${res.target_date})` : ""}`,
        );
      }
    } catch (e: any) {
      setError(e?.message ?? "테스트 발송 실패");
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
      <h2 style={{ marginBottom: 16 }}>알람 설정</h2>

      <div
        style={{
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          padding: 16,
          marginBottom: 16,
          background: "#fafafa",
        }}
      >
        <div style={{ fontWeight: 700, marginBottom: 8 }}>동작 방식</div>
        <div style={{ lineHeight: 1.6, fontSize: 14, color: "#334155" }}>
          전일 00:00/12:00 데이터 중 셋팅가 미만 거래처를 집계해서, 다음날 {sendTimeKst} (KST)에 이메일 발송합니다.
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: 12,
          alignItems: "end",
          padding: 16,
          border: "1px solid #e5e7eb",
          borderRadius: 12,
        }}
      >
        <label style={{ display: "flex", gap: 8, alignItems: "center", gridColumn: "span 2" }}>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            disabled={loading}
          />
          매일 알람 받기(활성화)
        </label>

        <div style={{ gridColumn: "span 2" }}>
          <label style={{ fontSize: 12 }}>수신 이메일</label>
          <input
            type="email"
            value={recipientEmail}
            onChange={(e) => setRecipientEmail(e.target.value)}
            placeholder="you@example.com"
            style={inputStyle}
            disabled={loading}
          />
        </div>

        <div>
          <label style={{ fontSize: 12 }}>셋팅가 (원)</label>
          <input
            type="number"
            value={thresholdPrice}
            onChange={(e) => setThresholdPrice(Number(e.target.value || 0))}
            min={1}
            style={inputStyle}
            disabled={loading}
          />
        </div>

        <div>
          <label style={{ fontSize: 12 }}>자동 발송 시각 (KST)</label>
          <input value={sendTimeKst} readOnly style={{ ...inputStyle, background: "#f8fafc" }} />
        </div>

        <div style={{ gridColumn: "span 2" }}>
          <label style={{ fontSize: 12, display: "block", marginBottom: 6 }}>전일 기준 데이터 시각 (KST)</label>
          <div style={{ display: "flex", gap: 12 }}>
            <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={sourceTime00}
                onChange={(e) => setSourceTime00(e.target.checked)}
                disabled={loading}
              />
              00:00
            </label>
            <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={sourceTime12}
                onChange={(e) => setSourceTime12(e.target.checked)}
                disabled={loading}
              />
              12:00
            </label>
          </div>
        </div>

        <div style={{ gridColumn: "span 2", display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button
            onClick={loadConfig}
            disabled={loading || saving || triggering}
            style={{
              padding: "10px 14px",
              borderRadius: 10,
              border: "1px solid #d1d5db",
              background: "#fff",
              cursor: "pointer",
            }}
          >
            새로고침
          </button>
          <button
            onClick={onTriggerNow}
            disabled={loading || saving || triggering}
            style={{
              padding: "10px 14px",
              borderRadius: 10,
              border: "1px solid #1d4ed8",
              background: "#eff6ff",
              color: "#1d4ed8",
              cursor: "pointer",
            }}
          >
            {triggering ? "테스트 발송 중..." : "지금 테스트 발송"}
          </button>
          <button
            onClick={onSave}
            disabled={loading || saving || triggering}
            style={{
              padding: "10px 14px",
              borderRadius: 10,
              border: "1px solid #111827",
              background: "#111827",
              color: "#fff",
              cursor: "pointer",
              opacity: loading || saving || triggering ? 0.7 : 1,
            }}
          >
            {saving ? "저장 중..." : "설정 저장"}
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            marginTop: 12,
            padding: 12,
            borderRadius: 12,
            border: "1px solid #fecaca",
            background: "#fef2f2",
            color: "#991b1b",
          }}
        >
          {error}
        </div>
      )}

      {message && (
        <div
          style={{
            marginTop: 12,
            padding: 12,
            borderRadius: 12,
            border: "1px solid #bbf7d0",
            background: "#f0fdf4",
            color: "#166534",
          }}
        >
          {message}
        </div>
      )}
    </div>
  );
}
