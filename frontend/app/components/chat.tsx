'use client';

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BACKEND, AuthUser, OAUTH_ENABLED, clearAuthToken, getAuthHeader, getAuthToken } from '../lib/auth';
import GoogleAuth from './google-auth';

export default function Chat() {
  const [user, setUser] = useState<AuthUser | null>(OAUTH_ENABLED ? null : { sub: "local", email: "local", name: "Local", picture: null });
  const { messages, sendMessage, status } = useChat({
    transport: new DefaultChatTransport({
      api: `${BACKEND}/api/chat`,
      headers: () => getAuthHeader(),
    }),
  });

  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const isStreaming = status === 'streaming';

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  const handleAuthenticated = useCallback((nextUser: AuthUser) => {
    setUser(nextUser);
  }, []);

  function handleSignOut() {
    if (!OAUTH_ENABLED) return;
    clearAuthToken();
    setUser(null);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || isStreaming || (OAUTH_ENABLED && !getAuthToken())) return;
    setInput('');
    sendMessage({ text });
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent);
    }
  }

  if (OAUTH_ENABLED && !user) {
    return (
      <div className="flex h-full items-center justify-center p-6 bg-stone-50 dark:bg-stone-950">
        <GoogleAuth onAuthenticated={handleAuthenticated} />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-stone-50 dark:bg-stone-950">
      <header className="flex items-center justify-between gap-3 px-6 py-4 bg-white dark:bg-stone-900 border-b border-stone-200 dark:border-stone-800 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🥗</span>
          <div>
            <h1 className="text-lg font-semibold text-stone-900 dark:text-stone-50 leading-tight">
              Kitchen Agent
            </h1>
            <p className="text-xs text-stone-500 dark:text-stone-400">Meal planning &amp; kitchen management agent</p>
          </div>
        </div>
        {OAUTH_ENABLED && user && (
          <button
            onClick={handleSignOut}
            className="text-xs text-stone-500 hover:text-stone-800 dark:text-stone-400 dark:hover:text-stone-200"
          >
            Sign out {user.email}
          </button>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {messages.length === 0 && <div className="text-sm text-stone-500">Start a conversation.</div>}
        {messages.map((message) => {
          const isUser = message.role === 'user';
          const text = message.parts.filter((p) => p.type === 'text').map((p) => p.text).join('');

          return <div key={message.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}><div className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${isUser ? 'bg-emerald-600 text-white rounded-br-sm' : 'bg-white dark:bg-stone-800 text-stone-800 dark:text-stone-100 border border-stone-200 dark:border-stone-700 rounded-bl-sm'}`}>{text}</div></div>;
        })}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSubmit} className="shrink-0 px-4 pb-4 pt-2 bg-stone-50 dark:bg-stone-950 border-t border-stone-200 dark:border-stone-800">
        <div className="flex items-end gap-2 bg-white dark:bg-stone-900 rounded-2xl border border-stone-200 dark:border-stone-700 px-4 py-2">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown} placeholder="Ask about meals, recipes, or your kitchen…" rows={1} className="flex-1 resize-none bg-transparent text-sm text-stone-900 dark:text-stone-100 placeholder:text-stone-400 focus:outline-none py-1.5 max-h-40 overflow-y-auto" style={{ fieldSizing: 'content' } as React.CSSProperties} suppressHydrationWarning />
          <button type="submit" disabled={!input.trim() || isStreaming} suppressHydrationWarning className="shrink-0 w-8 h-8 rounded-full bg-emerald-600 disabled:bg-stone-200 dark:disabled:bg-stone-700 flex items-center justify-center transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed">
            <span className="text-white">➤</span>
          </button>
        </div>
      </form>
    </div>
  );
}
