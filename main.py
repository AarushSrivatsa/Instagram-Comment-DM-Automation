from fastapi import FastAPI

from routers.webhook import router as webhook_router
from routers.crud import router as crud_router

app = FastAPI()

app.include_router(webhook_router)
app.include_router(crud_router)
