from httpx import AsyncClient
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import CommentDMRule, DMLog, get_db
from dotenv import load_dotenv
import os
from routers.crud import get_httpx_client

load_dotenv()

router = APIRouter(prefix="/webhook", tags=["Webhook"])

VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')
PAGE_ACCESS_TOKEN = os.getenv('PAGE_ACCESS_TOKEN')
IG_USER_ID = os.getenv('IG_USER_ID')

if not all([VERIFY_TOKEN, PAGE_ACCESS_TOKEN, IG_USER_ID]):
    raise RuntimeError("Missing required environment variables")


@router.get("/")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(content=params.get("hub.challenge"))
    raise HTTPException(403, "Verification failed")


@router.post("/")
async def receive_webhook(
    request: Request, 
    db: AsyncSession = Depends(get_db),
    client: AsyncClient = Depends(get_httpx_client)
):
    data = await request.json()
    print("Webhook payload received")

    try:
        if data.get("object") not in ["instagram", "page"]:
            return {"status": "ignored"}

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "comments":
                    continue

                value = change.get("value", {})

                comment_text = value.get("text", "").strip().lower()
                media_id = value.get("media", {}).get("id")
                comment_id = value.get("id")
                user_id = value.get("from", {}).get("id")

                if not all([comment_text, media_id, comment_id, user_id]):
                    continue

                if await is_duplicate(db, comment_id):
                    print(f"Duplicate comment {comment_id} skipped")
                    continue

                rule = await get_rule(db, media_id, comment_text)
                if not rule:
                    print(f"No rule found for comment: '{comment_text}'")
                    continue

                await process_comment(db, rule, comment_id, media_id, user_id, client)

        return {"status": "ok"}

    except Exception as e:
        print(f"Webhook error: {e}")
        await db.rollback()
        return {"status": "error"}


# ====================== HELPER FUNCTIONS ======================

async def is_duplicate(db: AsyncSession, comment_id: str) -> bool:
    result = await db.execute(
        select(DMLog).where(DMLog.comment_id == comment_id)
    )
    return result.scalar_one_or_none() is not None


async def get_rule(db: AsyncSession, media_id: str, comment_text: str):
    result = await db.execute(
        select(CommentDMRule).where(
            CommentDMRule.media_id == media_id,
            CommentDMRule.catchphrase == comment_text,
            CommentDMRule.is_active == True
        )
    )
    return result.scalar_one_or_none()


async def process_comment(
    db: AsyncSession, 
    rule: CommentDMRule,
    comment_id: str, 
    media_id: str, 
    user_id: str, 
    client: AsyncClient
):
    try:
        await send_dm(comment_id, rule.dm_message, client)
        
        if rule.reply_message:
            await send_reply(comment_id, rule.reply_message, client)

        db.add(DMLog(
            user_id=user_id,
            media_id=media_id,
            comment_id=comment_id
        ))
        await db.commit()
        print(f"✅ Successfully processed comment {comment_id}")

    except Exception as e:
        print(f"❌ Error processing comment {comment_id}: {e}")
        await db.rollback()


# ====================== SEND FUNCTIONS ======================

async def send_dm(comment_id: str, message: str, client: AsyncClient):
    # Use graph.facebook.com for messaging (more reliable)
    url = f"https://graph.facebook.com/v25.0/{IG_USER_ID}/messages"
    
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": message}
    }

    response = await client.post(
        url, 
        json=payload, 
        params={"access_token": PAGE_ACCESS_TOKEN}   # Better to send as query param
    )

    if response.status_code != 200:
        print(f"❌ DM Failed: {response.status_code} - {response.text}")
        raise Exception(f"DM failed: {response.text}")
    
    print(f"✅ DM sent successfully for comment {comment_id}")
    
async def send_reply(comment_id: str, message: str, client: AsyncClient):
    url = f"https://graph.instagram.com/v25.0/{comment_id}/replies"

    response = await client.post(
        url, 
        params={"message": message, "access_token": PAGE_ACCESS_TOKEN}
    )

    if response.status_code == 200:
        print(f"✅ Reply sent for comment {comment_id}")
    else:
        print(f"⚠️ Reply failed | Status: {response.status_code}")