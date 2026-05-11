from httpx import AsyncClient
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import CommentDMRule, get_db
from dotenv import load_dotenv
from typing import Optional
import os
from datetime import datetime

load_dotenv()

router = APIRouter(
    prefix="/crud",
    tags=["CRUD"]
)

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
IG_USER_ID = os.getenv("IG_USER_ID")


# ====================== DEPENDENCIES ======================
async def get_httpx_client():
    """Dependency that provides httpx AsyncClient"""
    async with AsyncClient(timeout=20.0) as client:
        yield client

# ====================== MODELS ======================
class RuleCreate(BaseModel):
    video_link: str
    catchphrase: str
    dm_message: str
    reply_message: Optional[str] = None


class RuleUpdate(BaseModel):
    catchphrase: str
    dm_message: str
    reply_message: Optional[str] = None


class RuleResponse(BaseModel):
    id: int
    media_id: str
    catchphrase: str
    dm_message: str
    reply_message: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ====================== UTILS ======================
def extract_shortcode(url: str) -> str:
    url = url.split("?")[0].rstrip("/")
    parts = [p for p in url.split("/") if p]
    return parts[-1] if parts else ""
async def get_media_id(
    rule: RuleCreate, 
    client: AsyncClient = Depends(get_httpx_client)
) -> str:
    
    video_link = rule.video_link
    shortcode = extract_shortcode(video_link)
    
    if not shortcode:
        raise HTTPException(400, "Invalid Instagram URL")

    print(f"🔍 Shortcode: {shortcode}")
    print(f"🔑 IG_USER_ID: {IG_USER_ID} (type: {type(IG_USER_ID)})")

    # Try both endpoints
    endpoints = [
        f"https://graph.facebook.com/v25.0/{IG_USER_ID}/media",
        f"https://graph.instagram.com/v25.0/{IG_USER_ID}/media"
    ]

    for base_url in endpoints:
        print(f"📡 Trying: {base_url}")
        url = base_url
        params = {
            "fields": "id,shortcode,permalink,media_type",
            "limit": 100,
            "access_token": PAGE_ACCESS_TOKEN,
        }

        page = 1
        while url:
            response = await client.get(url, params=params)
            print(f"   Status: {response.status_code} | Page {page}")

            if response.status_code == 200:
                data = response.json()
                for media in data.get("data", []):
                    api_shortcode = media.get("shortcode") or extract_shortcode(media.get("permalink", ""))
                    if api_shortcode == shortcode:
                        print(f"✅ MEDIA FOUND! ID: {media['id']}")
                        return media["id"]

                url = data.get("paging", {}).get("next")
                params = {}
                page += 1
            else:
                print(f"   Failed: {response.text[:400]}")
                break

    raise HTTPException(404, "Video not found. Make sure the reel is from this Business Account.")

# ====================== ROUTES ======================
@router.post("/")
async def create_rule(
    rule: RuleCreate, 
    db: AsyncSession = Depends(get_db),
    media_id: str = Depends(get_media_id)
):
    print("=== CREATE RULE CALLED SUCCESSFULLY ===")
    print(f"Rule data received: {rule.model_dump()}")
    print(f"Media ID from dependency: {media_id}")

    try:
        new_rule = CommentDMRule(
            media_id=media_id,
            catchphrase=rule.catchphrase.lower().strip(),
            dm_message=rule.dm_message,
            reply_message=rule.reply_message,
        )

        db.add(new_rule)
        await db.commit()
        await db.refresh(new_rule)

        print(f"✅ Rule created with ID: {new_rule.id}")
        return new_rule

    except Exception as e:
        print(f"❌ Error inside create_rule: {e}")
        raise

@router.get("/", response_model=list[RuleResponse])
async def get_all_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CommentDMRule))
    return result.scalars().all()


@router.get("/video", response_model=list[RuleResponse])
async def get_rules_by_video(
    video_link: str = Query(...),
    db: AsyncSession = Depends(get_db),
    media_id: str = Depends(get_media_id)
):
    result = await db.execute(
        select(CommentDMRule).where(CommentDMRule.media_id == media_id)
    )
    return result.scalars().all()


@router.put("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: int, 
    rule: RuleUpdate, 
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(CommentDMRule).where(CommentDMRule.id == rule_id))
    existing = result.scalar_one_or_none()

    if not existing:
        raise HTTPException(404, "Rule not found")

    existing.catchphrase = rule.catchphrase.lower().strip()
    existing.dm_message = rule.dm_message
    existing.reply_message = rule.reply_message

    await db.commit()
    await db.refresh(existing)
    return existing


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CommentDMRule).where(CommentDMRule.id == rule_id))
    existing = result.scalar_one_or_none()

    if not existing:
        raise HTTPException(404, "Rule not found")

    await db.delete(existing)
    await db.commit()

    return {"status": "deleted", "rule_id": rule_id}