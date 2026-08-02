import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useChat } from "../useChat";

/** Serialize chunks the way backend/main.py's sse() does. */
function sse(chunks: object[]): string {
  return chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`).join("");
}

/**
 * A fetch stub whose body arrives in the given byte-slices, so the reader is exercised
 * against frames that straddle a read boundary rather than one tidy chunk per event.
 */
function streamingResponse(slices: string[], { ok = true, status = 200 } = {}) {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const slice of slices) controller.enqueue(encoder.encode(slice));
      controller.close();
    },
  });
  return { ok, status, body } as unknown as Response;
}

const CHUNKS = [
  { type: "start" },
  { type: "text-start", id: "text-0" },
  { type: "text-delta", id: "text-0", delta: "Hello" },
  { type: "text-delta", id: "text-0", delta: ", " },
  { type: "text-delta", id: "text-0", delta: "world!" },
  { type: "text-end", id: "text-0" },
  { type: "finish" },
];

function text(parts: { text: string }[]): string {
  return parts.map((p) => p.text).join("");
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useChat", () => {
  it("assembles deltas into an assistant message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamingResponse([sse(CHUNKS)])));

    const { result } = renderHook(() => useChat({ api: "/api/chat" }));

    await act(async () => {
      await result.current.sendMessage({ text: "Say hello" });
    });

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].role).toBe("user");
    expect(text(result.current.messages[0].parts)).toBe("Say hello");
    expect(result.current.messages[1].role).toBe("assistant");
    expect(text(result.current.messages[1].parts)).toBe("Hello, world!");
    expect(result.current.error).toBeNull();
  });

  it("reassembles frames split across reads", async () => {
    // A single event cut mid-JSON, and a frame terminator cut in half — both of which a
    // real network delivers and a naive per-read parser drops.
    const raw = sse(CHUNKS);
    const slices = [raw.slice(0, 30), raw.slice(30, 101), raw.slice(101)];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamingResponse(slices)));

    const { result } = renderHook(() => useChat({ api: "/api/chat" }));

    await act(async () => {
      await result.current.sendMessage({ text: "Say hello" });
    });

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(text(result.current.messages[1].parts)).toBe("Hello, world!");
  });

  it("sends the full history as parts the backend understands", async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamingResponse([sse(CHUNKS)]));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat({ api: "/api/chat" }));

    await act(async () => {
      await result.current.sendMessage({ text: "first" });
    });
    await act(async () => {
      await result.current.sendMessage({ text: "second" });
    });

    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/chat");
    expect(init.method).toBe("POST");

    const sent = JSON.parse(init.body);
    // Three: user "first", the assistant's reply, then user "second".
    expect(sent.messages).toHaveLength(3);
    expect(sent.messages.map((m: { role: string }) => m.role)).toEqual([
      "user",
      "assistant",
      "user",
    ]);
    expect(sent.messages[2].parts).toEqual([{ type: "text", text: "second" }]);
  });

  it("reports a failed request instead of hanging", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(streamingResponse([], { ok: false, status: 401 }))
    );

    const { result } = renderHook(() => useChat({ api: "/api/chat" }));

    await act(async () => {
      await result.current.sendMessage({ text: "hi" });
    });

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBe("Request failed (401)");
  });

  it("reports a stream that ends without a reply", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamingResponse([""])));

    const { result } = renderHook(() => useChat({ api: "/api/chat" }));

    await act(async () => {
      await result.current.sendMessage({ text: "hi" });
    });

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBe("The response ended before it began.");
  });

  it("skips a malformed frame rather than dropping the stream", async () => {
    const withGarbage =
      sse(CHUNKS.slice(0, 3)) + "data: not json\n\n" + sse(CHUNKS.slice(3));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamingResponse([withGarbage])));

    const { result } = renderHook(() => useChat({ api: "/api/chat" }));

    await act(async () => {
      await result.current.sendMessage({ text: "hi" });
    });

    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(text(result.current.messages[1].parts)).toBe("Hello, world!");
  });
});
