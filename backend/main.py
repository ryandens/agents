import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Search from this file's location up through the repo root
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)

client = anthropic.AsyncAnthropic()


class Part(BaseModel):
    model_config = {"extra": "ignore"}

    type: str
    text: str = ""


class Message(BaseModel):
    model_config = {"extra": "ignore"}

    role: str
    # AI SDK v6 UIMessage.content is "" with text only in parts
    content: str | list[Any] = ""
    parts: list[Part] = []

    def text(self) -> str:
        if isinstance(self.content, list):
            return "".join(
                part.get("text", "")
                for part in self.content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if self.content:
            return self.content
        return "".join(p.text for p in self.parts if p.type == "text")


class ChatRequest(BaseModel):
    model_config = {"extra": "ignore"}

    messages: list[Message]


def sse(chunk: dict) -> str:
    return f"data: {json.dumps(chunk)}\n\n"


async def ui_message_stream(messages: list[MessageParam]) -> AsyncGenerator[str, None]:
    # AI SDK v6 expects SSE with UIMessageChunk objects
    text_id = "text-0"
    yield sse({"type": "text-start", "id": text_id})
    async with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=2048,
        messages=messages,
    ) as stream:
        async for delta in stream.text_stream:
            yield sse({"type": "text-delta", "id": text_id, "delta": delta})
    yield sse({"type": "text-end", "id": text_id})
    yield "data: [DONE]\n\n"


@app.post("/api/chat")
async def chat(request: ChatRequest):
    messages = cast(
        list[MessageParam],
        [{"role": m.role, "content": m.text()} for m in request.messages if m.text()],
    )
    return StreamingResponse(
        ui_message_stream(messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
