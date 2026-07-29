'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

interface User {
  sub: string;
  email: string;
  name: string;
  picture: string;
}

interface AuthContextValue {
  user: User;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

// The backend redirects back with ?error=<reason> when it refuses a sign-in. Anything
// unrecognised falls back to a generic message rather than echoing the raw value into
// the page.
const ERROR_MESSAGES: Record<string, string> = {
  not_authorized: 'That account is not on the allowlist for this app.',
  email_unverified: 'That Google account has no verified email address.',
  access_denied: 'Sign-in was cancelled.',
  state_mismatch: 'Sign-in expired before it completed. Please try again.',
  nonce_mismatch: 'Sign-in could not be verified. Please try again.',
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Read and strip ?error= so a refusal does not survive a reload. Reading it here
    // rather than in a state initializer keeps the first client render identical to the
    // prerendered HTML, which has no query string to read.
    const params = new URLSearchParams(window.location.search);
    const reason = params.get('error');
    if (reason) {
      params.delete('error');
      const query = params.toString();
      window.history.replaceState({}, '', window.location.pathname + (query ? `?${query}` : ''));
    }

    // The session cookie is HttpOnly, so asking the backend is the only way to find out
    // whether there is a valid session. Both setState calls land in async callbacks, not
    // the effect body, so this does not cascade renders.
    fetch('/api/auth/me')
      .then((res) => (res.ok ? res.json() : null))
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => {
        if (reason) setError(ERROR_MESSAGES[reason] ?? 'Sign-in failed. Please try again.');
        setChecked(true);
      });
  }, []);

  const signOut = useCallback(async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    setUser(null);
  }, []);

  if (!checked) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-stone-50 dark:bg-stone-950">
        <p className="text-xs text-stone-400">Loading…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-stone-50 dark:bg-stone-950">
        <div className="flex flex-col items-center gap-6 text-center p-8">
          <span className="text-5xl">🥗</span>
          <div>
            <h1 className="text-2xl font-semibold text-stone-900 dark:text-stone-50">
              Kitchen Agent
            </h1>
            <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">Sign in to continue</p>
          </div>
          {error && (
            <p className="text-sm text-red-600 dark:text-red-400 max-w-xs" role="alert">
              {error}
            </p>
          )}
          {/* A plain link, not fetch: the backend answers with a 302 to Google, which
              the browser must follow as a top-level navigation. */}
          <a
            href="/api/auth/login"
            className="px-5 py-2.5 rounded-full border border-stone-300 dark:border-stone-700 text-sm font-medium text-stone-700 dark:text-stone-200 hover:bg-stone-100 dark:hover:bg-stone-800 transition-colors"
          >
            Sign in with Google
          </a>
        </div>
      </div>
    );
  }

  return <AuthContext.Provider value={{ user, signOut }}>{children}</AuthContext.Provider>;
}
