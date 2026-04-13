const TOKEN_KEY = "libre_dashboard_token";

export function getDashboardToken(): string {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setDashboardToken(t: string): void {
  if (typeof localStorage === "undefined") return;
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

export function clearDashboardToken(): void {
  if (typeof localStorage === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders(): Record<string, string> {
  const t = getDashboardToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function authFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers ?? undefined);
  const ah = authHeaders();
  if (ah.Authorization) headers.set("Authorization", ah.Authorization);
  const res = await fetch(input, { ...init, headers });
  if (res.status === 401) {
    clearDashboardToken();
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("dashboard-auth-expired"));
    }
  }
  return res;
}
