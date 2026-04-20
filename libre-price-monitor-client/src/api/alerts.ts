import { API_BASE_URL } from "../config/api";
import { authFetch } from "./authFetch";

export type AlertConfig = {
  enabled: boolean;
  recipient_email: string;
  threshold_price: number;
  source_times_kst: string[];
  send_time_kst: string;
};

export async function getAlertConfig(): Promise<AlertConfig> {
  const res = await authFetch(`${API_BASE_URL}/alerts/config`, {
    method: "GET",
    headers: { accept: "application/json" },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Alert config fetch failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function putAlertConfig(payload: {
  enabled: boolean;
  recipient_email: string;
  threshold_price: number;
  source_times_kst: string[];
}): Promise<AlertConfig> {
  const res = await authFetch(`${API_BASE_URL}/alerts/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", accept: "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Alert config save failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function triggerAlertNow(): Promise<any> {
  const res = await authFetch(`${API_BASE_URL}/alerts/trigger`, {
    method: "POST",
    headers: { accept: "application/json" },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Alert trigger failed: ${res.status} ${text}`);
  }
  return res.json();
}
