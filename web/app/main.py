"""Multi-user web front-end for Anki collections (FastAPI + anki + HTMX).

No passwords: the start page lists users, a click selects one (stored in a cookie).
Each user has their own collection: data/users/<name>/collection.anki2
Optional sync with your own anki-syncserver: see data/sync.json (README in the reply).
Run:  uvicorn main:app --host 0.0.0.0 --port 8000     (trusted network only!)
"""
import os
from pathlib import Path
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.deps import NeedUser
from app.routes.deck import router as deck_router
from app.routes.media import router as media_router
from app.routes.study import router as study_router
from app.routes.sync import router as sync_router
from app.routes.users import router as user_router
from app.sessions import close_all_sessions
from app.stats import stats_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=stats_loop, daemon=True).start()
    yield
    close_all_sessions()

app = FastAPI(lifespan=lifespan)
app.include_router(user_router)
app.include_router(sync_router)
app.include_router(media_router)
app.include_router(deck_router)
app.include_router(study_router)

BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.exception_handler(NeedUser)
def _need_user(request: Request, exc: NeedUser) -> Response:
    return Response(status_code=200, headers={"HX-Redirect": "/"})




