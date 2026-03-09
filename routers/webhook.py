import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from database import AsyncSessionLocal, CommentDMRule, DMLog
from dotenv import load_dotenv
import os

load_dotenv()

router = APIRouter(
    prefix="/webhook",
    tags=["Webhook"]
)

VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')
PAGE_ACCESS_TOKEN = os.getenv('PAGE_ACCESS_TOKEN')
IG_USER_ID = os.getenv('IG_USER_ID')

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
async def receive_webhook(request: Request):

    data = await request.json()

    print("Webhook payload:", data)

    try:

        if data.get("object") not in ["instagram", "page"]:
            return {"status": "ignored"}

        entry = data.get("entry", [])

        for entry_item in entry:

            changes = entry_item.get("changes", [])

            for change in changes:

                value = change.get("value", {})

                comment_text = value.get("text", "").strip().lower()
                media_id = value.get("media", {}).get("id")
                comment_id = value.get("id")
                user_id = value.get("from", {}).get("id")

                print(f"comment: {comment_text} | media: {media_id} | comment_id: {comment_id} | user: {user_id}")

                if not all([comment_text, media_id, comment_id, user_id]):
                    continue

                async with AsyncSessionLocal() as db:

                    log_check = await db.execute(
                        select(DMLog).where(
                            DMLog.comment_id == comment_id
                        )
                    )

                    existing_log = log_check.scalar_one_or_none()

                    if existing_log:
                        continue

                    rule_result = await db.execute(
                        select(CommentDMRule).where(
                            CommentDMRule.media_id == media_id,
                            CommentDMRule.catchphrase == comment_text,
                            CommentDMRule.is_active == True
                        )
                    )

                    rule = rule_result.scalar_one_or_none()

                    if not rule:
                        print(f"No rule found for media_id={media_id} catchphrase={comment_text}")
                        continue

                    await send_dm(comment_id, rule.dm_message)

                    new_log = DMLog(
                        user_id=user_id,
                        media_id=media_id,
                        comment_id=comment_id
                    )

                    db.add(new_log)
                    await db.commit()

        return {"status": "ok"}

    except Exception as e:

        print("Webhook error:", str(e))

        return {"status": "error"}

async def send_dm(comment_id: str, message: str):

    url = f"https://graph.instagram.com/v21.0/{IG_USER_ID}/messages"

    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": message},
    }

    async with httpx.AsyncClient() as client:

        response = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {PAGE_ACCESS_TOKEN}"}
        )

        if response.status_code != 200:
            raise Exception(f"DM failed for comment {comment_id}: {response.text}")

        print("DM sent:", response.text)