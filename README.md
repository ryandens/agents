# Ryan's Agents

A collection of AI agents. Currently home to one: the **Kitchen Agent**.

## Agents

### Kitchen Agent

An AI-powered meal planning and kitchen management app. Chat with the agent to plan meals, find recipes, and build grocery lists — then track what you actually have with the pantry manager.

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.14, FastAPI, Anthropic SDK (`claude-opus-4-7`) |
| Frontend | Next.js 16 (App Router), React 19, Tailwind CSS v4, Vercel AI SDK v6 |
| Package managers | `uv` (backend), `npm` (frontend) |
| Task runner | `just` |

## Prerequisites

- [just](https://github.com/casey/just)
- [uv](https://docs.astral.sh/uv/)
- Node.js 24 (use `nvm` — `.nvmrc` is included)
- An Anthropic API key

## Setup

```sh
# Install dependencies
just backend-install
just frontend-install

# Create .env at the repo root
cat > .env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_OAUTH_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
APP_AUTH_SECRET=replace-with-a-long-random-secret
NEXT_PUBLIC_GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
EOF
```

`GOOGLE_OAUTH_CLIENT_ID` enables backend token verification. `NEXT_PUBLIC_GOOGLE_CLIENT_ID` enables the Google sign-in button in the Next.js client.

## Running

```sh
just dev
```

Opens the frontend at `http://localhost:3000` and the backend at `http://localhost:8000`. Use `/login` to trigger Google sign-in.

## Features

### Chat (`/`)

Conversational interface powered by `claude-opus-4-7`. Ask it to plan meals, suggest recipes, or build a grocery list. Streams responses via Server-Sent Events.

### Pantry (`/pantry`)

Track everything in your kitchen:

- **Three storage locations** — Pantry, Fridge, Freezer
- **Rich item data** — name, brand, category, quantity, unit, purchase date, expiration date, notes
- **14 categories** — Produce, Dairy, Meat, Seafood, Grains, Legumes, Condiments, Spices, Beverages, Snacks, Baking, Canned, Frozen, Other
- **20 units** — weight, volume, count, and container types
- **Expiry badges** — green (fresh), amber (≤ 3 days), red (expired)
- **Category filter pills** — narrow the view without leaving the tab
- Items sorted by expiration date, soonest first

Data is stored in `backend/data/pantry.json`. The storage layer is designed to be swapped for a relational database or DynamoDB without changing the API.

## Development

```sh
just dev            # start both servers with hot-reload
just check          # run all checks (mirrors CI)

just backend-test   # pytest
just backend-lint   # ruff check
just backend-fmt    # ruff format --check

just frontend-test  # vitest
just frontend-lint  # eslint
just frontend-build # next build (type-check + compile)
```

## Project structure

```
agents/
├── backend/
│   ├── main.py              # FastAPI app — chat + pantry REST endpoints
│   ├── pantry.py            # Pydantic models and enums
│   ├── pantry_store.py      # JSON file storage layer
│   ├── test_main.py         # Chat API tests
│   ├── test_pantry_api.py   # Pantry REST API tests
│   └── test_pantry_store.py # Storage layer tests
└── frontend/
    └── app/
        ├── page.tsx             # Chat page
        ├── layout.tsx           # Root layout + nav
        └── pantry/
            ├── page.tsx         # Pantry list page
            ├── PantryForm.tsx   # Create / edit modal
            ├── PantryItemCard.tsx
            └── types.ts
```
