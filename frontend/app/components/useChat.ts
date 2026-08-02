'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Minimal chat state + SSE reader for /api/chat.
 *
 * This replaces `useChat` from @ai-sdk/react. The SDK brought 16 transitive packages
 * (an MCP client, the Vercel AI Gateway, an OIDC client) to supply one hook, and it did
 * not insulate this app from the wire format anyway — backend/main.py hand-writes the
 * chunk stream this file reads, so both ends of the protocol already live in this repo.
 * Keeping the client local means the format is defined once, here and in ui_message_stream().
 */

export interface TextPart {
  type: 'text';
  text: string;
}

export interface UIMessage {
  id: string;
  role: 'user' | 'assistant';
  parts: TextPart[];
}

export type ChatStatus = 'ready' | 'submitted' | 'streaming' | 'error';

/** The chunk types backend/main.py emits. Anything else on the wire is ignored. */
type Chunk =
  | { type: 'start' }
  | { type: 'text-start'; id: string }
  | { type: 'text-delta'; id: string; delta: string }
  | { type: 'text-end'; id: string }
  | { type: 'finish' };

// A counter rather than crypto.randomUUID(): these ids only have to be unique within one
// list to serve as React keys, and a counter needs no secure context to work.
let nextId = 0;
const messageId = () => `msg-${nextId++}`;

/**
 * Parse an SSE byte stream into the JSON payload of each `data:` line.
 *
 * Frames are separated by a blank line and may be split across reads, so the tail of the
 * buffer is held back until its terminator arrives. Lines that are not valid JSON are
 * skipped rather than thrown: one malformed frame should not cancel a stream that is
 * otherwise delivering text.
 */
async function* readSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<Chunk> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      for (;;) {
        const split = buffer.indexOf('\n\n');
        if (split === -1) break;

        const frame = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);

        for (const line of frame.split('\n')) {
          if (!line.startsWith('data:')) continue;
          try {
            yield JSON.parse(line.slice(5).trim()) as Chunk;
          } catch {
            // Not JSON — ignore this line and keep reading.
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export function useChat({ api }: { api: string }) {
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>('ready');
  const [error, setError] = useState<string | null>(null);

  // The conversation is held in a ref as well as in state. A `setMessages(prev => ...)`
  // updater does not run until React re-renders, which is far too late for a delta loop
  // that has to append to the message it created two chunks ago and for a request body
  // that has to include the turn just added. The ref is the synchronous source of truth;
  // state is what renders.
  const messagesRef = useRef<UIMessage[]>([]);
  const commit = useCallback((update: (prev: UIMessage[]) => UIMessage[]) => {
    messagesRef.current = update(messagesRef.current);
    setMessages(messagesRef.current);
  }, []);

  // Cancels an in-flight response if the component unmounts mid-stream, so the reader
  // does not keep writing into state that no longer exists.
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);

  const sendMessage = useCallback(
    async ({ text }: { text: string }) => {
      commit((prev) => [
        ...prev,
        { id: messageId(), role: 'user', parts: [{ type: 'text', text }] },
      ]);
      const sent = messagesRef.current;

      setStatus('submitted');
      setError(null);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const res = await fetch(api, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: sent }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          throw new Error(`Request failed (${res.status})`);
        }

        const assistantId = messageId();
        // Maps the stream's part ids to their slot in the assistant message, so deltas
        // land in the right part whatever order the ids arrive in.
        const partIndex = new Map<string, number>();
        let started = false;

        // Rewrites the assistant message in place. A no-op if it is no longer last,
        // which only happens if something else appended while the stream was open.
        const updateAssistant = (parts: (prev: TextPart[]) => TextPart[]) => {
          commit((prev) => {
            const last = prev[prev.length - 1];
            if (!last || last.id !== assistantId) return prev;
            return [...prev.slice(0, -1), { ...last, parts: parts(last.parts) }];
          });
        };

        for await (const chunk of readSSE(res.body)) {
          switch (chunk.type) {
            case 'start':
              setStatus('streaming');
              commit((prev) => [...prev, { id: assistantId, role: 'assistant', parts: [] }]);
              started = true;
              break;

            case 'text-start':
              if (!started) break;
              partIndex.set(chunk.id, messagesRef.current[messagesRef.current.length - 1].parts.length);
              updateAssistant((parts) => [...parts, { type: 'text', text: '' }]);
              break;

            case 'text-delta': {
              const index = partIndex.get(chunk.id);
              if (index === undefined) break;
              updateAssistant((parts) =>
                parts.map((part, i) =>
                  i === index ? { ...part, text: part.text + chunk.delta } : part
                )
              );
              break;
            }

            case 'text-end':
            case 'finish':
              break;
          }
        }

        // A stream that ended without ever starting a message delivered nothing, and
        // leaving the UI on "ready" with no reply would look like the send was dropped.
        if (!started) throw new Error('The response ended before it began.');

        setStatus('ready');
      } catch (e) {
        if (controller.signal.aborted) return;
        setError(e instanceof Error ? e.message : 'Something went wrong');
        setStatus('error');
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [api, commit]
  );

  return { messages, sendMessage, status, error };
}
