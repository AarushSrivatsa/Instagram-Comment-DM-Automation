import httpx
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import AsyncSessionLocal, CommentDMRule, get_db
from dotenv import load_dotenv
from typing import Optional
import os

load_dotenv()

router = APIRouter(
    prefix="/crud",
    tags=["CRUD"]
)

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
IG_USER_ID = os.getenv("IG_USER_ID")

class RuleCreate(BaseModel):
    video_link: str
    catchphrase: str
    dm_message: str
    reply_message: Optional[str] = None

class RuleUpdate(BaseModel):
    catchphrase: str
    dm_message: str
    reply_message: Optional[str] = None

def extract_shortcode(url: str) -> str:
    url = url.split("?")[0]
    url = url.rstrip("/")
    parts = [p for p in url.split("/") if p]
    return parts[-1] if parts else ""

async def get_media_id(video_link: str) -> str:
    shortcode = extract_shortcode(video_link)
    print(f"Looking for shortcode: '{shortcode}'")

    url = f"https://graph.instagram.com/v25.0/{IG_USER_ID}/media"
    params = {
        "fields": "id,permalink",
        "limit": 100,
        "access_token": PAGE_ACCESS_TOKEN,
    }

    async with httpx.AsyncClient() as client:
        while url:
            response = await client.get(url, params=params)

            if response.status_code != 200:
                print(f"Instagram API error {response.status_code}: {response.text}")
                raise HTTPException(400, f"Instagram API error: {response.text}")

            data = response.json()

            for media in data.get("data", []):
                api_shortcode = extract_shortcode(media["permalink"])
                print(f"Comparing: '{api_shortcode}' == '{shortcode}'")
                if api_shortcode == shortcode:
                    return media["id"]

            url = data.get("paging", {}).get("next")
            params = {}

    raise HTTPException(404, "Video not found in your Instagram account")

@router.post("/")
async def create_rule(rule: RuleCreate, db : AsyncSession = Depends(get_db)):

    media_id = await get_media_id(rule.video_link)

    new_rule = CommentDMRule(
        media_id=media_id,
        catchphrase=rule.catchphrase.lower(),
        dm_message=rule.dm_message,
        reply_message=rule.reply_message or None,
    )

    db.add(new_rule)
    await db.commit()
    await db.refresh(new_rule)

    return {
        "id": new_rule.id,
        "video_link": rule.video_link,
        "catchphrase": new_rule.catchphrase,
        "dm_message": new_rule.dm_message,
        "reply_message": new_rule.reply_message,
    }

@router.get("/")
async def get_all_rules(db : AsyncSession = Depends(get_db)):
    result = await db.execute(select(CommentDMRule))
    rules = result.scalars().all()

    return [
        {
            "id": r.id,
            "media_id": r.media_id,
            "catchphrase": r.catchphrase,
            "dm_message": r.dm_message,
            "reply_message": r.reply_message,
        }
        for r in rules
    ]

@router.get("/video")
async def get_rules_by_video(
    video_link: str = Query(...),
    db : AsyncSession = Depends(get_db)
):

    media_id = await get_media_id(video_link)

    result = await db.execute(
        select(CommentDMRule).where(
            CommentDMRule.media_id == media_id
        )
    )

    rules = result.scalars().all()
    return [
        {
            "id": r.id,
            "video_link": video_link,
            "catchphrase": r.catchphrase,
            "dm_message": r.dm_message,
            "reply_message": r.reply_message,
        }
        for r in rules
    ]

@router.put("/{rule_id}")
async def update_rule(rule_id: int, rule: RuleUpdate, db : AsyncSession = Depends(get_db)):
    
    result = await db.execute(
        select(CommentDMRule).where(
            CommentDMRule.id == rule_id
            )
            )

    existing = result.scalar_one_or_none()

    if not existing:
            raise HTTPException(404, "Rule not found")

    existing.catchphrase = rule.catchphrase.lower()
    existing.dm_message = rule.dm_message
    existing.reply_message = rule.reply_message or None

    await db.commit()
    await db.refresh(existing)

    return {
        "id": existing.id,
        "media_id": existing.media_id,
        "catchphrase": existing.catchphrase,
        "dm_message": existing.dm_message,
        "reply_message": existing.reply_message,
    }

@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, db : AsyncSession = Depends(get_db)):

    result = await db.execute(
        select(CommentDMRule).where(
                CommentDMRule.id == rule_id
            )
        )

    existing = result.scalar_one_or_none()

    if not existing:
        raise HTTPException(404, "Rule not found")

    await db.delete(existing)
    await db.commit()

    return {
            "status": "deleted",
            "rule_id": rule_id
        }