from fastapi import FastAPI
from routers.webhook import router as webhook_router
from routers.crud import router as crud_router
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.include_router(webhook_router)
app.include_router(crud_router)

@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return """
    <h1>Privacy Policy</h1>
    <p>This application uses the Instagram Graph API to access Instagram account data
    with user permission.</p>
    <p>Data is used only for application functionality. We do not sell or share user data.</p>
    <p>Users may request deletion of their data by contacting: pitlaaarushsrivatsa@gmail.com</p>
    """

@app.get("/")
def frontend():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")