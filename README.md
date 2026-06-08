# Index

A Telegram bot that indexes media files from Telegram channels into MongoDB and exposes them through a searchable web app with on-demand HTTP streaming. Files never leave Telegram's servers, the bot streams them on demand using byte-range requests, so storage costs stay minimal.

## Features

- **Channel indexing** — Index, copy, update, and delete media (documents, videos, audio, photos) from allowed Telegram channels in bulk via owner commands.
- **Full-text search** — MongoDB text index (with optional Atlas Search) plus a query sanitizer that normalizes `&`/`and`, punctuation, and separators for consistent matching.
- **On-demand streaming** — FastAPI streams files directly from Telegram with HTTP `Range` support (1 MB chunks), so videos and audio can be played or downloaded without re-hosting.
- **Web frontend** — Public browse/search UI and an admin panel for managing files, posters.
- **Owner tools** — Stats, log retrieval, cache clearing, channel allow-list management, and restart.
- **In-memory caching** — TTL caches (5 min) for auth, users, and media lists to reduce database load.

## Tech stack

- **Bot:** [Pyrofork](https://pypi.org/project/Pyrofork/) (Pyrogram fork) + TgCrypto
- **API:** [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn
- **Database:** MongoDB via [Motor](https://motor.readthedocs.io/) (async)
- **Caching:** cachetools (`TTLCache`)
- **Runtime:** Python 3.11

## Architecture

```
Telegram Channel ──> Bot (Pyrofork) ──> MongoDB (file metadata)
                          │                    ▲
                          │                    │
                     FastAPI ────────> Web frontend (browse/search/stream)
                          │
                     Streams file bytes from Telegram on demand
```

The bot and the FastAPI server run together in a single process (see `bot.py`), sharing the same Pyrogram client so the API can stream media through the active Telegram session.

## Project layout

| Path | Description |
|------|-------------|
| `bot.py` | Entry point; starts the bot, FastAPI server, and the file-queue worker. |
| `app.py` | Pyrogram `Bot` client, query sanitizer, and link encoding helpers. |
| `fast_api.py` | FastAPI app: streaming, OTP auth, file details, public listing. |
| `config.py` | Loads environment/config (optionally from a remote `CONFIG_FILE_URL`). |
| `db.py` | MongoDB connection and collections; Atlas Search index notes. |
| `cache.py` | TTL caches and cache invalidation. |
| `handlers/owner.py` | Owner-only commands (`/index`, `/copy`, `/update`, `/del`, `/stats`, etc.). |
| `handlers/user.py` | `/start`, channel file ingestion, and member-update events. |
| `handlers/admin.py` | `/api/admin/*` routes for managing files, posters. |
| `static_frontend/` | Web UI (browse + admin). |
| `Dockerfile` | Container build. |

## Getting started

### Prerequisites

- Python 3.11+
- A MongoDB database (Atlas or self-hosted)
- Telegram API credentials (`API_ID`, `API_HASH`) and a bot token

### Configuration

Copy the sample config and fill in your values:

```bash
cp config.env.sample config.env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `API_ID` | yes | Telegram API ID. |
| `API_HASH` | yes | Telegram API hash. |
| `BOT_TOKEN` | yes | Telegram bot token from @BotFather. |
| `OWNER_ID` | yes | Telegram user ID of the bot owner/admin. |
| `BOT_USERNAME` | yes | Bot username (without `@`). |
| `LOG_CHANNEL_ID` | yes | Channel ID for startup/auth logs. |
| `API_BASE_URL` | yes | Public domain of the web app. |
| `MONGO_URI` | yes | MongoDB connection string. |
| `CF_DOMAIN` | no | Allowed CORS origin for the frontend. |
| `CONFIG_FILE_URL` | no | Remote URL to download `config.env` at startup. |

### Run locally

```bash
pip install -r requirements.txt
python bot.py
```

The FastAPI server listens on `http://0.0.0.0:8000`.

### Run with Docker

```bash
docker build -t index-bot .
docker run --env-file config.env -p 8000:8000 index-bot
```

## Usage

1. Add the bot as an admin to the channels you want to index.
2. Allow a channel: `/add <channel_id> <channel_name>`.
3. Index a range of messages: `/index <start_link> <end_link> [dup]`.
4. Browse and search the indexed media through the web app.

### Owner commands

| Command | Description |
|---------|-------------|
| `/index <start> <end> [dup]` | Index a range of channel messages. |
| `/copy <start> <end> <dest>` | Copy a range of files to another channel and index them. |
| `/update <start> <end>` | Refresh message/channel IDs for existing files. |
| `/del <link> [end_link]` | Delete a file (or range) from the database. |
| `/add <channel_id> <name>` | Add a channel to the allow-list. |
| `/rm <channel_id>` | Remove a channel from the allow-list. |
| `/stats` | Show users, file size, DB storage, and per-channel counts. |
| `/clear` | Clear in-memory caches. |
| `/log` | Send the bot log file. |
| `/restart` | Restart the bot. |

## API endpoints

- `GET /` — Web frontend.
- `GET|HEAD /stream/{file_link}` — Stream a file (supports `Range`).
- `POST /api/request-otp` — Request an OTP for a user ID.
- `POST /api/verify-otp` — Verify OTP and receive a session token.
- `GET /api/user/verify` — Validate a bearer token.
- `GET /api/others` — Paginated public file listing with search/sort.
- `GET /api/file/{file_id}` — File details.
- `/api/admin/*` — Owner-only management routes.

## License

See [LICENSE](LICENSE).
