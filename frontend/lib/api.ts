/** Клиент API. Токен в localStorage, 401 → на вход. Запросы идут на тот же
 * домен (/api), дальше их проксирует Next в dev и nginx в проде. */

const TOKEN = "sc-token";
const USER = "sc-user";

export type Me = { id: number; name: string; role: string; role_name: string; login: string; phone?: string };
export type Company = { id: number; name: string; short_name: string; city: string };

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try { return localStorage.getItem(TOKEN); } catch { return null; }
}

export function saveSession(token: string, user: Me, company: Company) {
  try {
    localStorage.setItem(TOKEN, token);
    localStorage.setItem(USER, JSON.stringify({ user, company }));
  } catch {}
}

export function readSession(): { user: Me; company: Company } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(USER);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

export function clearSession() {
  try { localStorage.removeItem(TOKEN); localStorage.removeItem(USER); } catch {}
}

function headers(json = true): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  const t = getToken();
  if (t) h["Authorization"] = `Bearer ${t}`;
  return h;
}

function unauthorized() {
  clearSession();
  if (typeof window !== "undefined" && !location.pathname.startsWith("/login")) location.href = "/login";
}

async function detail(r: Response): Promise<string> {
  const body = await r.json().catch(() => ({}));
  if (typeof body?.detail === "string") return body.detail;
  if (Array.isArray(body?.detail)) return body.detail.map((d: any) => d.msg).join("; ");
  return `Ошибка ${r.status}`;
}

export class ApiError extends Error { status: number; constructor(s: number, m: string) { super(m); this.status = s; } }

export async function apiGet<T = any>(path: string): Promise<T> {
  const r = await fetch(path, { headers: headers(false), cache: "no-store" });
  if (r.status === 401) { unauthorized(); throw new ApiError(401, "Не авторизован"); }
  if (!r.ok) throw new ApiError(r.status, await detail(r));
  return r.json();
}

async function send<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: headers(true), body: body === undefined ? undefined : JSON.stringify(body) });
  if (r.status === 401) { unauthorized(); throw new ApiError(401, "Не авторизован"); }
  if (!r.ok) throw new ApiError(r.status, await detail(r));
  return r.json();
}

export const apiPost = <T = any>(path: string, body?: unknown) => send<T>("POST", path, body);
export const apiPatch = <T = any>(path: string, body?: unknown) => send<T>("PATCH", path, body);
export const apiDelete = <T = any>(path: string) => send<T>("DELETE", path);

/** multipart: фото, документы */
export async function apiUpload<T = any>(path: string, form: FormData): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: headers(false), body: form });
  if (r.status === 401) { unauthorized(); throw new ApiError(401, "Не авторизован"); }
  if (!r.ok) throw new ApiError(r.status, await detail(r));
  return r.json();
}

export async function apiDownload(path: string, filename: string) {
  const r = await fetch(path, { headers: headers(false) });
  if (!r.ok) throw new ApiError(r.status, await detail(r));
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
