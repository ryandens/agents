import json
import logging
import os
import secrets
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import UUID

import anthropic
from anthropic.types import MessageParam
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

import auth
from auth import authenticated
from pantry import PantryItem, PantryItemCreate, PantryItemUpdate, StorageLocation
from pantry_store import PantryStore

# Search from this file's location up through the repo root
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

# Signs the session cookie. A generated fallback keeps `just dev` and the image smoke
# test working without configuration; the cost is that every restart invalidates every
# session, so production sets this explicitly.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_urlsafe(32)
    logger.warning(
        "SESSION_SECRET unset — using an ephemeral key; sessions reset on restart"
    )

if not auth.allowed_emails():
    logger.warning("ALLOWED_EMAILS is empty — every sign-in will be rejected")

# The frontend's static export, served at "/" so the app and the API share an origin.
# Populated by `just build` locally and by the frontend stage of backend/Dockerfile in
# the image; absent when running the backend on its own against `next dev`.
static_dir_env = os.environ.get("STATIC_DIR", "")
STATIC_DIR = (
    Path(static_dir_env) if static_dir_env else Path(__file__).parent / "static"
)

app = FastAPI()
# Production is same-origin, so CORS only matters for `next dev` talking to a backend
# started without the dev proxy. allow_credentials is required for the browser to send
# the session cookie on those cross-origin calls, and it forbids a wildcard origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Content-Type"],
)
# Outermost middleware runs first, so this must be added last to have request.session
# populated before anything above it reads the session.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="agents_session",
    max_age=7 * 24 * 60 * 60,
    same_site="lax",  # "strict" would drop the cookie on the redirect back from Google
    https_only=auth.COOKIE_SECURE,
)

app.include_router(auth.router)

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


# Mounted last so it only sees paths no API route claimed. html=True resolves
# directories to index.html, matching the export's trailingSlash layout.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
