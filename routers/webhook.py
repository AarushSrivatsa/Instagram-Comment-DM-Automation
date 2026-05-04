import httpx
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import AsyncSessionLocal, CommentDMRule, DMLog, get_db
from dotenv import load_dotenv
import os

load_dotenv()

router = APIRouter(prefix="/webhook", tags=["Webhook"])

VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')
PAGE_ACCESS_TOKEN = os.getenv('PAGE_ACCESS_TOKEN')
IG_USER_ID = os.getenv('IG_USER_ID')

# Basic validation
if not all([VERIFY_TOKEN, PAGE_ACCESS_TOKEN, IG_USER_ID]):
    raise RuntimeError("Missing required environment variables: VERIFY_TOKEN, PAGE_ACCESS_TOKEN, or IG_USER_ID")


@router.get("/")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)

    raise HTTPException(403, "Verification failed")


@router.post("/")
async def receive_webhook(request: Request, db : AsyncSession = Depends(get_db)):
    data = await request.json()
    print("Webhook payload received:", data)

    try:
        if data.get("object") not in ["instagram", "page"]:
            return {"status": "ignored"}

        for entry_item in data.get("entry", []):
            for change in entry_item.get("changes", []):
                if change.get("field") != "comments":
                    continue

                value = change.get("value", {})

                comment_text = value.get("text", "").strip().lower()
                media_id = value.get("media", {}).get("id")
                comment_id = value.get("id")
                user_id = value.get("from", {}).get("id")

                print(f"Comment received: '{comment_text}' | Media: {media_id} | Comment ID: {comment_id}")

                if not all([comment_text, media_id, comment_id, user_id]):
                    continue

                    # Prevent sending DM multiple times for same comment
                existing_log = await db.execute(
                    select(DMLog).where(DMLog.comment_id == comment_id)
                )
                if existing_log.scalar_one_or_none():
                    print("Duplicate comment skipped")
                    continue

                    # Find matching rule
                rule_result = await db.execute(
                    select(CommentDMRule).where(
                        CommentDMRule.media_id == media_id,
                        CommentDMRule.catchphrase == comment_text,
                        CommentDMRule.is_active == True
                    )
                )
                rule = rule_result.scalar_one_or_none()

                if not rule:
                    print(f"No active rule found for media_id={media_id}, catchphrase='{comment_text}'")
                    continue

                    # Send DM using graph.instagram.com
                await send_dm(comment_id, rule.dm_message)

                    # Send public reply if configured
                if rule.reply_message:
                    await send_reply(comment_id, rule.reply_message)

                    # Log the action
                new_log = DMLog(
                    user_id=user_id,
                    media_id=media_id,
                    comment_id=comment_id
                )
                db.add(new_log)
                await db.commit()

        return {"status": "ok"}

    except Exception as e:
        print(f"Webhook error: {str(e)}")
        return {"status": "error"}


# ====================== SEND DM (Using graph.instagram.com) ======================
async def send_dm(comment_id: str, message: str):
    url = f"https://graph.instagram.com/v25.0/{IG_USER_ID}/messages"

    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": message}
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {PAGE_ACCESS_TOKEN}"}
        )

        print(f"DM Response Status: {response.status_code}")
        if response.status_code != 200:
            print(f"DM Error Body: {response.text}")
            raise Exception(f"DM failed: {response.text}")
        else:
            print(f"✅ DM sent successfully for comment {comment_id}")

# ====================== SEND COMMENT REPLY ======================
async def send_reply(comment_id: str, message: str):
    url = f"https://graph.instagram.com/v25.0/{comment_id}/replies"

    params = {
        "message": message,
        "access_token": PAGE_ACCESS_TOKEN
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, params=params)

        if response.status_code == 200:
            print(f"✅ Public reply sent under comment {comment_id}")
        else:
            print(f"⚠️ Reply failed | Status: {response.status_code}")
            print(f"Response: {response.text}")
            # We don't raise here so DM can still succeed even if reply fails

    