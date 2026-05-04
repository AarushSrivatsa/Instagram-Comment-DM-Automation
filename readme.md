# InBot

A production-ready Instagram comment-to-DM automation backend built with FastAPI, PostgreSQL, and the Instagram Graph API.

## What it does

InBot listens to Instagram webhook events and automatically sends DMs (and optional comment replies) to users who comment a specific catchphrase on your posts.

**Example use case:** Post a reel and say *"Comment 'LINK' to get the resource."* — InBot handles the rest automatically, in real-time.

- **Webhook listener** — receives Instagram comment events instantly via the Graph API
- **Rule-based automation** — define catchphrase → DM message → optional reply per post
- **Duplicate prevention** — logs every processed comment, never double-sends
- **Async throughout** — fully async FastAPI + SQLAlchemy, no blocking I/O
- **CRUD API** — create, read, update, delete automation rules via REST

## Stack

| Layer | Tech |
|---|---|
| Framework | FastAPI (async) |
| Database | PostgreSQL + SQLAlchemy (async) |
| HTTP Client | httpx (async) |
| External API | Instagram Graph API v25.0 |
| Config | python-dotenv |

## Project Structure

```
.
├── main.py              # FastAPI app, router registration, static files
├── database.py          # Async engine, session factory, SQLAlchemy models
└── routers/
    ├── webhook.py       # Instagram webhook verification + event handler
    └── crud.py          # Rule management CRUD API
```

## Database Models

**`CommentDMRule`** — stores automation rules per post
- `media_id` — Instagram media ID (resolved from post URL)
- `catchphrase` — keyword to trigger on (stored lowercase)
- `dm_message` — message to send via DM
- `reply_message` — optional public comment reply
- `is_active` — toggle rules without deleting

**`DMLog`** — deduplication log
- `comment_id` — unique constraint prevents double processing
- `user_id`, `media_id`, `sent_at` — audit trail

## API Overview

### Webhook — `/webhook`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/webhook/` | Instagram webhook verification |
| POST | `/webhook/` | Receive and process comment events |

### Rules — `/crud`

| Method | Endpoint | Description |
|---|---|---|
| POST | `/crud/` | Create automation rule for a post |
| GET | `/crud/` | List all rules |
| GET | `/crud/video?video_link=...` | Get rules for a specific post |
| PUT | `/crud/{rule_id}` | Update rule catchphrase/messages |
| DELETE | `/crud/{rule_id}` | Delete a rule |

## Getting Started

### 1. Clone and set up environment

```bash
git clone https://github.com/AarushSrivatsa/InBot
cd InBot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

Create a `.env` file in the root:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/inbot
PAGE_ACCESS_TOKEN=your-instagram-page-access-token
VERIFY_TOKEN=your-custom-webhook-verify-token
IG_USER_ID=your-instagram-user-id
```

### 3. Initialize database

```bash
python database.py
```

### 4. Run

```bash
uvicorn main:app --reload
```

### 5. Configure Instagram Webhook

In your [Meta Developer App](https://developers.facebook.com/):
- Set webhook URL to `https://your-domain.com/webhook/`
- Set verify token to match `VERIFY_TOKEN` in your `.env`
- Subscribe to the `comments` field under Instagram

## How It Works

1. Someone comments a catchphrase on your Instagram post
2. Instagram sends a webhook event to `/webhook/`
3. InBot checks if the `comment_id` has already been processed (deduplication)
4. Looks up a matching active rule for that `media_id` + `catchphrase`
5. Sends a DM via the Instagram Graph API
6. Optionally posts a public reply to the comment
7. Logs the processed comment to prevent duplicates

## Creating a Rule

```bash
curl -X POST http://localhost:8000/crud/ \
  -H "Content-Type: application/json" \
  -d '{
    "video_link": "https://www.instagram.com/reel/ABC123/",
    "catchphrase": "link",
    "dm_message": "Here is the link you asked for: https://example.com",
    "reply_message": "Sent you a DM!"
  }'
```

InBot resolves the post URL to a `media_id` automatically using the Graph API.