export const BACKEND = "http://localhost:8000";
export const AUTH_TOKEN_KEY = "kitchen_agent_access_token";
export const OAUTH_ENABLED = Boolean(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID);

export interface AuthUser {
  sub: string;
  email: string;
  name: string | null;
  picture: string | null;
}

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
}

export function getAuthHeader(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function fetchWithAuth(input: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  Object.entries(getAuthHeader()).forEach(([key, value]) => {
    headers.set(key, value);
  });
  return fetch(input, { ...init, headers });
}
