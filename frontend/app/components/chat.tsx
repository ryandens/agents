'use client';

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { useEffect, useRef, useState } from 'react';

export default function Chat() {
  const { messages, sendMessage, status } = useChat({
    transport: new DefaultChatTransport({ api: `${process.env.NEXT_PUBLIC_BACKEND ?? ""}/api/chat` }),
  });

  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const isStreaming = status === 'streaming';

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput('');
    sendMessage({ text });
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent);
    }
  }

  return (
    <div className="flex flex-col h-full bg-stone-50 dark:bg-stone-950">
      {/* Header */}
      <header className="flex items-center gap-3 px-6 py-4 bg-white dark:bg-stone-900 border-b border-stone-200 dark:border-stone-800 shrink-0">
        <span className="text-2xl">🥗</span>
        <div>
          <h1 className="text-lg font-semibold text-stone-900 dark:text-stone-50 leading-tight">
            Kitchen Agent
          </h1>
          <p className="text-xs text-stone-500 dark:text-stone-400">
            Meal planning &amp; kitchen management agent
          </p>
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
            <span className="text-5xl">🍳</span>
            <h2 className="text-xl font-medium text-stone-700 dark:text-stone-300">
              What&apos;s on the menu?
            </h2>
            <p className="text-sm text-stone-500 dark:text-stone-400 max-w-sm">
              Ask me to plan meals, find recipes, build a grocery list, or use up what&apos;s in your fridge.
            </p>
            <div className="flex flex-wrap justify-center gap-2 mt-2">
              {[
                'Plan this week\'s dinners',
                'What can I make with chicken and rice?',
                'Build me a grocery list for 4 people',
                'Suggest a healthy 30-minute meal',
              ].map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => {
                    setInput('');
                    sendMessage({ text: prompt });
                  }}
                  className="px-3 py-1.5 text-sm rounded-full bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 text-stone-700 dark:text-stone-300 hover:bg-stone-100 dark:hover:bg-stone-700 transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) => {
          const isUser = message.role === 'user';
          const text = message.parts
            .filter((p) => p.type === 'text')
            .map((p) => p.text)
            .join('');

          return (
            <div
              key={message.id}
              className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
            >
              {!isUser && (
                <div className="w-7 h-7 rounded-full bg-emerald-100 dark:bg-emerald-900 flex items-center justify-center text-sm shrink-0 mr-2 mt-1">
                  🥗
                </div>
              )}
              <div
                className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
                  isUser
                    ? 'bg-emerald-600 text-white rounded-br-sm'
                    : 'bg-white dark:bg-stone-800 text-stone-800 dark:text-stone-100 border border-stone-200 dark:border-stone-700 rounded-bl-sm'
                }`}
              >
                {text}
              </div>
            </div>
          );
        })}

        {isStreaming && (
          <div className="flex justify-start">
            <div className="w-7 h-7 rounded-full bg-emerald-100 dark:bg-emerald-900 flex items-center justify-center text-sm shrink-0 mr-2 mt-1">
              🥗
            </div>
            <div className="bg-white dark:bg-stone-800 border border-stone-200 dark:border-stone-700 rounded-2xl rounded-bl-sm px-4 py-3">
              <span className="flex gap-1 items-center h-4">
                <span className="w-1.5 h-1.5 rounded-full bg-stone-400 animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-stone-400 animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-stone-400 animate-bounce [animation-delay:300ms]" />
              </span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSubmit}
        className="shrink-0 px-4 pb-4 pt-2 bg-stone-50 dark:bg-stone-950 border-t border-stone-200 dark:border-stone-800"
      >
        <div className="flex items-end gap-2 bg-white dark:bg-stone-900 rounded-2xl border border-stone-200 dark:border-stone-700 px-4 py-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about meals, recipes, or your kitchen…"
            rows={1}
            className="flex-1 resize-none bg-transparent text-sm text-stone-900 dark:text-stone-100 placeholder:text-stone-400 focus:outline-none py-1.5 max-h-40 overflow-y-auto"
            style={{ fieldSizing: 'content' } as React.CSSProperties}
            suppressHydrationWarning
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            suppressHydrationWarning
            className="shrink-0 w-8 h-8 rounded-full bg-emerald-600 disabled:bg-stone-200 dark:disabled:bg-stone-700 flex items-center justify-center transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
              className="w-4 h-4 text-white dark:disabled:text-stone-500"
            >
              <path d="M3.105 2.288a.75.75 0 0 0-.826.95l1.414 4.926A1.5 1.5 0 0 0 5.135 9.25h6.115a.75.75 0 0 1 0 1.5H5.135a1.5 1.5 0 0 0-1.442 1.086l-1.414 4.926a.75.75 0 0 0 .826.95 28.897 28.897 0 0 0 15.293-7.155.75.75 0 0 0 0-1.114A28.897 28.897 0 0 0 3.105 2.288Z" />
            </svg>
          </button>
        </div>
        <p className="text-center text-xs text-stone-400 mt-2">
          Enter to send · Shift+Enter for new line
        </p>
      </form>
    </div>
  );
}
