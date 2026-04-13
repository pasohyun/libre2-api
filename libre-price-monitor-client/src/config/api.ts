// src/config/api.ts
// 환경변수 우선순위:
// 1) Vite: VITE_API_BASE_URL
// 2) CRA: REACT_APP_API_BASE_URL
// 3) Next.js: NEXT_PUBLIC_API_BASE_URL
// 4) default: http://127.0.0.1:8000

const fromVite =
  typeof import.meta !== "undefined" &&
  (import.meta as any).env &&
  (import.meta as any).env.VITE_API_BASE_URL
    ? String((import.meta as any).env.VITE_API_BASE_URL)
    : "";

const fromCra =
  (typeof process !== "undefined" && process.env?.REACT_APP_API_BASE_URL) || "";

const fromNext =
  (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_BASE_URL) ||
  "";

export const API_BASE_URL = (
  fromVite ||
  fromCra ||
  fromNext ||
  "http://127.0.0.1:8000"
).replace(/\/$/, "");
