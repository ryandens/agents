'use client';

import Script from 'next/script';
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';

interface AuthContextValue {
  token: string;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: Record<string, unknown>) => void;
          prompt: () => void;
          renderButton: (element: HTMLElement, config: Record<string, unknown>) => void;
        };
      };
    };
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [scriptLoaded, setScriptLoaded] = useState(false);
  const buttonRef = useRef<HTMLDivElement>(null);

  function onGsiLoad() {
    window.google?.accounts.id.initialize({
      client_id: process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID,
      callback: ({ credential }: { credential: string }) => setToken(credential),
      auto_select: true,
    });
    window.google?.accounts.id.prompt();
    setScriptLoaded(true);
  }

  useEffect(() => {
    if (scriptLoaded && !token && buttonRef.current) {
      window.google?.accounts.id.renderButton(buttonRef.current, {
        theme: 'outline',
        size: 'large',
        text: 'sign_in_with',
        shape: 'pill',
      });
    }
  }, [scriptLoaded, token]);

  if (!token) {
    return (
      <>
        <Script
          src="https://accounts.google.com/gsi/client"
          onLoad={onGsiLoad}
          strategy="afterInteractive"
        />
        <div className="min-h-screen flex items-center justify-center bg-stone-50 dark:bg-stone-950">
          <div className="flex flex-col items-center gap-6 text-center p-8">
            <span className="text-5xl">🥗</span>
            <div>
              <h1 className="text-2xl font-semibold text-stone-900 dark:text-stone-50">
                Kitchen Agent
              </h1>
              <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
                Sign in to continue
              </p>
            </div>
            <div ref={buttonRef} className="min-h-[44px]" />
            {!scriptLoaded && (
              <p className="text-xs text-stone-400">Loading…</p>
            )}
          </div>
        </div>
      </>
    );
  }

  return (
    <AuthContext.Provider value={{ token }}>
      {children}
    </AuthContext.Provider>
  );
}
