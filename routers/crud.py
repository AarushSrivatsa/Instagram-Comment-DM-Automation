import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from database import AsyncSessionLocal, CommentDMRule
from dotenv import load_dotenv
import os

load_dotenv()

router = APIRouter(
    prefix="/crud",
    tags=["CRUD"]
)

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
GRAPH_API_VERSION = "v19.0"
IG_USER_ID = os.getenv("IG_USER_ID")

class RuleCreate(BaseModel):
    video_link: str
    catchphrase: str
    dm_message: str


class RuleUpdate(BaseModel):
    catchphrase: str
    dm_message: str

async def get_media_id(video_link: str) -> str:

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{IG_USER_ID}"

    params = {
        "fields": "media.limit(100){id,permalink}",
        "access_token": PAGE_ACCESS_TOKEN,
    }

    async with httpx.AsyncClient() as client:

        while url:

            response = await client.get(url, params=params)

            if response.status_code != 200:
                raise HTTPException(400, "Failed to fetch Instagram media")

            data = response.json()
            media_list = data.get("media", {}).get("data", [])

            for media in media_list:
                if media["permalink"].rstrip("/") == video_link.rstrip("/"):
                    return media["id"]

            next_url = data.get("media", {}).get("paging", {}).get("next")
            url = next_url
            params = {} 

    raise HTTPException(404, "Video not found in your Instagram account")


@router.post("/")
async def create_rule(rule: RuleCreate):

    media_id = await get_media_id(rule.video_link)

    async with AsyncSessionLocal() as db:

        new_rule = CommentDMRule(
            media_id=media_id,
            catchphrase=rule.catchphrase.lower(),
            dm_message=rule.dm_message
        )

        db.add(new_rule)
        await db.commit()
        await db.refresh(new_rule)

        return {
            "id": new_rule.id,
            "video_link": rule.video_link,
            "catchphrase": new_rule.catchphrase,
            "dm_message": new_rule.dm_message
        }

@router.get("/")
async def get_all_rules():

    async with AsyncSessionLocal() as db:

        result = await db.execute(select(CommentDMRule))

        rules = result.scalars().all()

        return [
            {
                "id": r.id,
                "media_id": r.media_id,
                "catchphrase": r.catchphrase,
                "dm_message": r.dm_message
            }
            for r in rules
        ]

@router.get("/video")
async def get_rules_by_video(
    video_link: str = Query(...)
):

    media_id = await get_media_id(video_link)

    async with AsyncSessionLocal() as db:

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
                "dm_message": r.dm_message
            }
            for r in rules
        ]

@router.put("/{rule_id}")
async def update_rule(rule_id: int, rule: RuleUpdate):

    async with AsyncSessionLocal() as db:

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

        await db.commit()
        await db.refresh(existing)

        return {
            "id": existing.id,
            "media_id": existing.media_id,
            "catchphrase": existing.catchphrase,
            "dm_message": existing.dm_message
        }

@router.delete("/{rule_id}")
async def delete_rule(rule_id: int):

    async with AsyncSessionLocal() as db:

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