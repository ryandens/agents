import json
from collections.abc import AsyncGenerator
from pathlib import Path

import anthropic
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


class Message(BaseModel):
    model_config = {"extra": "ignore"}

    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


async def vercel_stream(messages: list[dict]) -> AsyncGenerator[str, None]:
    async with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=2048,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield f"0:{json.dumps(text)}\n"
        final = await stream.get_final_message()
        usage = final.usage
        yield f'd:{{"finishReason":"stop","usage":{{"promptTokens":{usage.input_tokens},"completionTokens":{usage.output_tokens}}}}}\n'


@app.post("/api/chat")
async def chat(request: ChatRequest):
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    return StreamingResponse(
        vercel_stream(messages),
        media_type="text/plain; charset=utf-8",
        headers={"X-Vercel-AI-Data-Stream": "v1"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
