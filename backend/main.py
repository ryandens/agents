import hashlib
import json
import logging
import os
import secrets
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anthropic
from anthropic.types import MessageParam
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field
from starlette.datastructures import Headers
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

import auth
import db
from auth import authenticated
from browser_history import SiteVisit
from browser_history_store import BrowserHistoryStore
from chat_workouts import WORKOUT_TOOL, WorkoutToolSession
from fitness import WorkoutRecordingContext
from fitness_api import router as fitness_router
from fitness_store import FitnessStore
from pantry import PantryItem, PantryItemCreate, PantryItemUpdate, StorageLocation
from pantry_store import PantryStore
from youtube_shorts import DEFAULT_DAYS, MAX_DAYS, ShortsDay, fill_gaps, window

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

# Off by default and security-relevant, so say so at startup: this is the one setting
# that lets the API be reached without a browser session behind it.
if service_accounts := auth.allowed_service_accounts():
    logger.info(
        "ALLOWED_SERVICE_ACCOUNTS set — bearer auth enabled for %d account(s)",
        len(service_accounts),
    )

# The frontend's static export, served at "/" so the app and the API share an origin.
# Populated by `just build` locally and by the frontend stage of backend/Dockerfile in
# the image; absent when running the backend on its own against `next dev`.
static_dir_env = os.environ.get("STATIC_DIR", "")
STATIC_DIR = (
    Path(static_dir_env) if static_dir_env else Path(__file__).parent / "static"
)


# The pantry lives in Postgres, so the pool is process-wide state with a lifetime tied
# to the app rather than to a request. Opened here rather than at import so that
# importing this module — which the tests do — never reaches for a database.
pool: ConnectionPool | None = None
pantry_store: PantryStore | None = None
browser_history_store: BrowserHistoryStore | None = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global pool, pantry_store, browser_history_store

    pool = db.open_pool()
    # No schema creation here on purpose. Migrations are a separate deploy step run by a
    # role that owns the schema; this process connects with DML rights only, so it could
    # not create a table even if it tried. A missing table surfaces as a failing query
    # rather than being silently papered over at startup.
    pantry_store = PantryStore(pool)
    browser_history_store = BrowserHistoryStore(pool)
    logger.info("connected to the pantry database")
    try:
        yield
    finally:
        pantry_store = None
        browser_history_store = None
        pool.close()
        pool = None


def store() -> PantryStore:
    """The pantry store, or a 503 if the app is running without one.

    Only reachable if a request arrives outside the lifespan — which the tests do by
    overriding this dependency, and nothing in production does.
    """
    if pantry_store is None:
        raise HTTPException(status_code=503, detail="Pantry storage is unavailable")
    return pantry_store


def visit_store() -> BrowserHistoryStore:
    """The browser history store, on the same terms as store() above."""
    if browser_history_store is None:
        raise HTTPException(
            status_code=503, detail="Browser history storage is unavailable"
        )
    return browser_history_store


Pantry = Annotated[PantryStore, Depends(store)]
History = Annotated[BrowserHistoryStore, Depends(visit_store)]

# A day of heavy browsing is a few thousand visits, so this bounds one request at
# roughly a week of it. The exporter chunks well below the limit.
#
# This is an API contract, NOT a memory bound: it is checked in the handler, which runs
# only after FastAPI has already read the body and built every SiteVisit in the list. By
# then the allocation has happened. MAX_REQUEST_BYTES below is what actually bounds it.
MAX_VISITS_PER_REQUEST = 10_000

# The real limit on what one request can allocate, enforced before the body is read.
#
# There is nowhere else to put it: the app sits behind `tailscale serve` on loopback,
# with no ALB and no nginx, so the usual advice to cap body size at the proxy has no
# proxy to apply to. 16 MiB is far above a legitimate batch — 500 visits at a few
# hundred bytes each is well under 1 MiB — and far below what would trouble the host.
MAX_REQUEST_BYTES = 16 * 1024 * 1024


class LimitRequestBody:
    """Reject an over-large request before anything reads its body.

    Plain ASGI rather than BaseHTTPMiddleware: the latter buffers responses, which would
    break the SSE stream /api/chat returns.

    Enforced on Content-Length, which every real client sends — requests, httpx and
    urllib all set it for a bytes body. A chunked upload without the header slips past
    this and is bounded only by MAX_VISITS_PER_REQUEST after parsing; closing that would
    mean counting bytes as they arrive and abandoning a partly-read request, which is a
    lot of machinery for a route only authenticated callers can reach.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            declared = Headers(scope=scope).get("content-length", "")
            if declared.isdigit() and int(declared) > self.max_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"request body is {declared} bytes, over the "
                            f"{self.max_bytes} byte limit; send it in smaller batches"
                        )
                    },
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def frontend_cache_headers(request: Request, call_next):
    """Revalidate frontend HTML while retaining Next's immutable build assets."""
    response = await call_next(request)
    if response.status_code == 200:
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        elif request.url.path.startswith("/_next/static/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


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
    https_only=auth.cookie_secure(),
)
# Added last, so it is the outermost layer and runs before all of the above: an
# oversized request should be turned away before anything decodes a session cookie or
# reads a byte of the body.
app.add_middleware(LimitRequestBody, max_bytes=MAX_REQUEST_BYTES)

app.include_router(auth.router)
app.include_router(fitness_router)

# Depends() called in an argument default trips B008, so carry it in the type.
AuthenticatedUser = Annotated[dict, Depends(authenticated)]

client = anthropic.AsyncAnthropic()


class Part(BaseModel):
    model_config = {"extra": "ignore"}

    type: str
    text: str = ""


class Message(BaseModel):
    model_config = {"extra": "ignore"}

    id: str | None = Field(default=None, max_length=200)
    role: Literal["user", "assistant"]
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
    timezone: str = "UTC"


def sse(chunk: dict) -> str:
    return f"data: {json.dumps(chunk)}\n\n"


async def ui_message_stream(
    messages: list[MessageParam], workouts: WorkoutToolSession
) -> AsyncGenerator[str]:
    # AI SDK v6 expects SSE with UIMessageChunk objects
    text_id = "text-0"
    yield sse({"type": "start"})
    yield sse({"type": "text-start", "id": text_id})
    conversation = list(messages)
    try:
        for _ in range(4):
            async with client.messages.stream(
                model="claude-opus-4-7",
                max_tokens=8192,
                system=workouts.system,
                tools=[WORKOUT_TOOL],
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                messages=conversation,
            ) as stream:
                async for delta in stream.text_stream:
                    yield sse({"type": "text-delta", "id": text_id, "delta": delta})
                final = await stream.get_final_message()
            if final.stop_reason != "tool_use":
                if final.stop_reason == "max_tokens":
                    yield sse(
                        {
                            "type": "text-delta",
                            "id": text_id,
                            "delta": "\nThe response was cut off. Please send a shorter workout log; incomplete tool calls were not recorded.",
                        }
                    )
                break
            conversation.append(
                {
                    "role": "assistant",
                    "content": [
                        block.model_dump(mode="json", exclude_none=True)
                        for block in final.content
                    ],
                }
            )
            results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                result = await workouts.execute(block.name, block.input)
                failed = "error" in result
                if not failed:
                    yield sse(
                        {
                            "type": "data-workout-saved",
                            "id": result["id"],
                            "data": result,
                        }
                    )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                        "is_error": failed,
                    }
                )
            conversation.append({"role": "user", "content": results})
        else:
            yield sse(
                {
                    "type": "text-delta",
                    "id": text_id,
                    "delta": "\nI couldn't complete the remaining steps. Check any saved-workout card above, or send the missing details to continue.",
                }
            )
    except Exception:
        logger.exception("chat stream failed")
        yield sse(
            {
                "type": "error",
                "errorText": "The chat request failed. Any workout shown in a saved-workout card is already recorded; retrying the same message will not duplicate it.",
            }
        )
    yield sse({"type": "text-end", "id": text_id})
    yield sse({"type": "finish"})


@app.get("/api/version")
def version(_: AuthenticatedUser):
    """The runtime deployment label, independent of the image's identity."""
    return JSONResponse(
        content={"version": os.environ.get("APP_VERSION", "dev").split("@", 1)[0]},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
def health():
    """Readiness, including the database.

    user_data.sh waits on this before declaring a boot good and `just restart` waits on
    it before declaring a rollout good, so it has to fail when the app is up but cannot
    reach its data — an app that answers 200 with a dead database would let a broken
    deploy through both gates.
    """
    if pool is None:
        return JSONResponse(
            status_code=503, content={"status": "error", "database": "not configured"}
        )
    try:
        db.ping(pool)
    except Exception:
        logger.exception("health check could not reach the database")
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unreachable"},
        )
    return {"status": "ok", "database": "ok"}


@app.post("/api/chat")
async def chat(request: ChatRequest, user: AuthenticatedUser):
    try:
        zone = ZoneInfo(request.timezone)
    except ZoneInfoNotFoundError, ValueError:
        raise HTTPException(400, "Unknown time zone") from None
    user_messages = [
        message
        for message in request.messages
        if message.role == "user" and message.text()
    ]
    if not user_messages:
        raise HTTPException(422, "Send a message first")
    # Keep the pasted log when later user turns supply its date or other details.
    # A saved receipt starts a new log, excluding already-recorded sessions.
    source_messages = []
    for message in request.messages:
        if message.role == "assistant" and any(
            part.type == "data-workout-saved" for part in message.parts
        ):
            source_messages.clear()
        elif message.role == "user" and message.text():
            source_messages.append(message.text())
        if message is user_messages[-1]:
            # A partial response may already include this log's saved receipt.
            # Ignore it so retrying retains the original receipt fingerprint.
            break
    # Keep the beginning of an oversized log rather than only its final reply.
    source_note = "\n\n".join(source_messages)[:20000]
    message_id = (
        user_messages[-1].id or hashlib.sha256(source_note.encode()).hexdigest()
    )
    workouts = WorkoutToolSession(
        FitnessStore(pool) if pool else None,
        WorkoutRecordingContext(user["sub"], message_id, source_note),
        datetime.now(zone).date().isoformat(),
        request.timezone,
    )
    messages = cast(
        list[MessageParam],
        [{"role": m.role, "content": m.text()} for m in request.messages if m.text()],
    )
    return StreamingResponse(
        ui_message_stream(messages, workouts),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/pantry", response_model=list[PantryItem])
def list_pantry(
    _: AuthenticatedUser, pantry: Pantry, location: StorageLocation | None = None
):
    return pantry.list_items(location=location)


@app.post("/api/pantry", response_model=PantryItem, status_code=201)
def create_pantry_item(data: PantryItemCreate, _: AuthenticatedUser, pantry: Pantry):
    return pantry.create_item(data)


@app.get("/api/pantry/{item_id}", response_model=PantryItem)
def get_pantry_item(item_id: UUID, _: AuthenticatedUser, pantry: Pantry):
    item = pantry.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.patch("/api/pantry/{item_id}", response_model=PantryItem)
def update_pantry_item(
    item_id: UUID, data: PantryItemUpdate, _: AuthenticatedUser, pantry: Pantry
):
    item = pantry.update_item(item_id, data)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.delete("/api/pantry/{item_id}", status_code=204)
def delete_pantry_item(item_id: UUID, _: AuthenticatedUser, pantry: Pantry):
    if not pantry.delete_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found")


@app.post("/api/browser-history", status_code=201)
def record_browser_history(
    visits: list[SiteVisit], _: AuthenticatedUser, history: History
) -> dict:
    """Accept a batch of browser visits.

    Reports `received` and `stored` separately rather than just succeeding, because the
    store drops duplicates silently and a client re-sending a day it already uploaded
    deserves to be able to tell that apart from a day that genuinely had no new visits.
    """
    if len(visits) > MAX_VISITS_PER_REQUEST:
        raise HTTPException(
            status_code=413,
            detail=(
                f"too many visits in one request: {len(visits)} > "
                f"{MAX_VISITS_PER_REQUEST}; send them in smaller batches"
            ),
        )
    stored = history.record_visits(visits)
    return {"received": len(visits), "stored": stored}


@app.get("/api/browser-history", response_model=list[SiteVisit])
def list_browser_history(_: AuthenticatedUser, history: History, limit: int = 100):
    """Recent visits, newest first — enough to confirm an upload actually landed."""
    return history.list_visits(limit=max(0, min(limit, 1000)))


@app.get("/api/youtube-shorts/daily", response_model=list[ShortsDay])
def daily_youtube_shorts(
    _: AuthenticatedUser,
    history: History,
    days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = DEFAULT_DAYS,
    tz: str = "UTC",
) -> list[ShortsDay]:
    """Shorts watched per day for the last `days` days, oldest first.

    Always exactly `days` entries. `has_history` distinguishes days with any
    stored Safari history from gaps. Zero Shorts only counts as an achievement on
    days with history; it does not prove that all devices have finished syncing.

    `tz` names the zone the days are cut in — the browser's own, so "today" on the
    graph is the day the person reading it is having. It has to be a zone name both
    Python and Postgres know; the two ship separate copies of the IANA database, which
    agree on every zone that has existed long enough to have visits in it.

    `days` is rejected outside 1..MAX_DAYS rather than clamped. Clamping would answer a
    request for two years with one year of data and no indication it had done so, and
    the caller would draw it as if it were the range it asked for.
    """
    try:
        zone = ZoneInfo(tz)
    except ZoneInfoNotFoundError, ValueError:
        # ValueError too: ZoneInfo raises it for a key that is not a zone name at all
        # (absolute, or containing ".."), which it refuses before ever looking it up.
        raise HTTPException(
            status_code=400, detail=f"unknown time zone: {tz!r}"
        ) from None

    # "Today" comes from the same zone the buckets do, so the last column of the graph
    # is the day in progress rather than a UTC day that may have already rolled over.
    start, end = window(days, datetime.now(zone).date())
    return fill_gaps(history.daily_shorts(start, end, tz), start, end)


# Register the export as low-priority routes so API paths continue to take precedence.
# The static build emits one HTML file per route, so there is no SPA fallback.
if STATIC_DIR.is_dir():
    app.frontend("/", directory=STATIC_DIR, fallback=None)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
