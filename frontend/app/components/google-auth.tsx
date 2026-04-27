"use client";

import Script from "next/script";
import { useEffect, useState } from "react";
import { BACKEND, AuthUser, clearAuthToken, fetchWithAuth, setAuthToken } from "../lib/auth";

type CredentialResponse = { credential?: string };

type GoogleAccounts = {
  id: {
    initialize: (options: {
      client_id: string;
      callback: (response: CredentialResponse) => void;
    }) => void;
    renderButton: (
      parent: HTMLElement,
      options: { theme?: string; size?: string; text?: string; shape?: string }
    ) => void;
  };
};

function getGoogleAccounts(): GoogleAccounts | null {
  if (typeof window === "undefined") return null;
  return (window as Window & { google?: { accounts?: GoogleAccounts } }).google?.accounts ?? null;
}

interface Props {
  onAuthenticated: (user: AuthUser) => void;
}

export default function GoogleAuth({ onAuthenticated }: Props) {
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadCurrentUser() {
      const res = await fetchWithAuth(`${BACKEND}/api/auth/me`);
      if (!res.ok) {
        clearAuthToken();
        return;
      }
      const user: AuthUser = await res.json();
      if (!cancelled) onAuthenticated(user);
    }

    void loadCurrentUser();
    return () => {
      cancelled = true;
    };
  }, [onAuthenticated]);

  function initGoogleButton() {
    if (!clientId) {
      setError("NEXT_PUBLIC_GOOGLE_CLIENT_ID is not configured.");
      return;
    }

    const accounts = getGoogleAccounts();
    const container = document.getElementById("google-signin-button");
    if (!accounts || !container) return;

    accounts.id.initialize({
      client_id: clientId,
      callback: async (response) => {
        const credential = response.credential;
        if (!credential) {
          setError("Google sign-in did not return a credential.");
          return;
        }

        const res = await fetch(`${BACKEND}/api/auth/google`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ credential }),
        });

        if (!res.ok) {
          const payload = await res.json().catch(() => ({}));
          setError(payload?.detail ?? `Sign-in failed (${res.status})`);
          return;
        }

        const payload = (await res.json()) as { access_token: string; user: AuthUser };
        setAuthToken(payload.access_token);
        setError(null);
        onAuthenticated(payload.user);
      },
    });

    container.innerHTML = "";
    accounts.id.renderButton(container, {
      theme: "outline",
      size: "large",
      text: "signin_with",
      shape: "pill",
    });
  }

  return (
    <>
      <Script
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onLoad={initGoogleButton}
      />
      <div className="flex flex-col items-center gap-3 text-center">
        <h2 className="text-lg font-semibold text-stone-800 dark:text-stone-100">Sign in required</h2>
        <p className="text-sm text-stone-500 dark:text-stone-400 max-w-md">
          Connect with Google to access chat and pantry APIs.
        </p>
        <div id="google-signin-button" className="min-h-10" />
        {error && <p className="text-sm text-red-500">{error}</p>}
      </div>
    </>
  );
}
