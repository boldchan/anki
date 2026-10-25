import os
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import NAME_RE, USERS_DIR
from app.main import app
from app.sessions import open_session, valid_user
from app.sync import sync_now
from app.templating import templates
from app.views.decks import deck_list, user_picker

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> str:
    name = request.cookies.get("user", "")
    if not valid_user(name):
        main = user_picker()
    else:
        s = open_session(name)
        with s.lock:
            sync_now(s)
            main = deck_list(s)
    return templates.TemplateResponse(request, "index.html", {"main": main})

@router.post("/login/{name}", response_class=HTMLResponse)
def login(name: str) -> HTMLResponse:
    if not valid_user(name):
        raise HTTPException(404)
    s = open_session(name)
    with s.lock:
        sync_now(s)
        resp = HTMLResponse(deck_list(s))
    resp.set_cookie("user", name, max_age=365 * 86400, httponly=True, samesite="lax")
    return resp


@app.post("/newuser", response_class=HTMLResponse)
async def newuser(request: Request):
    form = parse_qs((await request.body()).decode())
    name = (form.get("name") or [""])[0].strip()
    if not NAME_RE.match(name):
        return HTMLResponse(user_picker("Use letters, digits, _ or - (max 32)."))
    os.makedirs(os.path.join(USERS_DIR, name), exist_ok=True)
    return login(name)


@app.post("/logout", response_class=HTMLResponse)
def logout() -> HTMLResponse:
    resp = HTMLResponse(user_picker())
    resp.delete_cookie("user")
    return resp