import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import UUID

import anthropic
from anthropic.types import MessageParam
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel

from pantry import PantryItem, PantryItemCreate, PantryItemUpdate, StorageLocation
from pantry_store import PantryStore

# Search from this file's location up through the repo root
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
_auth_request = google_requests.Request()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://agents.ryandens.com",
    ],
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


def authenticated(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.removeprefix("Bearer ")
    try:
        return id_token.verify_oauth2_token(token, _auth_request, GOOGLE_CLIENT_ID)
    except (GoogleAuthError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


# Depends() called in an argument default trips B008, so carry it in the type.
AuthenticatedUser = Annotated[dict, Depends(authenticated)]

pantry_store = PantryStore()

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


async def ui_message_stream(messages: list[MessageParam]) -> AsyncGenerator[str]:
    # AI SDK v6 expects SSE with UIMessageChunk objects
    text_id = "text-0"
    yield sse({"type": "start"})
    yield sse({"type": "text-start", "id": text_id})
    async with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=2048,
        messages=messages,
    ) as stream:
        async for delta in stream.text_stream:
            yield sse({"type": "text-delta", "id": text_id, "delta": delta})
    yield sse({"type": "text-end", "id": text_id})
    yield sse({"type": "finish"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: ChatRequest, _: AuthenticatedUser):
    messages = cast(
        list[MessageParam],
        [{"role": m.role, "content": m.text()} for m in request.messages if m.text()],
    )
    return StreamingResponse(
        ui_message_stream(messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/pantry", response_model=list[PantryItem])
def list_pantry(_: AuthenticatedUser, location: StorageLocation | None = None):
    return pantry_store.list_items(location=location)


@app.post("/api/pantry", response_model=PantryItem, status_code=201)
def create_pantry_item(data: PantryItemCreate, _: AuthenticatedUser):
    return pantry_store.create_item(data)


@app.get("/api/pantry/{item_id}", response_model=PantryItem)
def get_pantry_item(item_id: UUID, _: AuthenticatedUser):
    item = pantry_store.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.patch("/api/pantry/{item_id}", response_model=PantryItem)
def update_pantry_item(item_id: UUID, data: PantryItemUpdate, _: AuthenticatedUser):
    item = pantry_store.update_item(item_id, data)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.delete("/api/pantry/{item_id}", status_code=204)
def delete_pantry_item(item_id: UUID, _: AuthenticatedUser):
    if not pantry_store.delete_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
