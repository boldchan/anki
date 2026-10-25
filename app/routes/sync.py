from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.deps import session
from app.sessions import Session
from app.sync import sync_now
from app.views.decks import deck_list

router = APIRouter()

@router.post("/sync", response_class=HTMLResponse)
def sync_route(s: Annotated[Session, Depends(session)]) -> str:
    with s.lock:
        sync_now(s)
        return deck_list(s)


@router.post("/fullsync/{direction}", response_class=HTMLResponse)
def fullsync(direction: str, s: Annotated[Session, Depends(session)]) -> str:
    if direction not in ("up", "down"):
        raise HTTPException(404)
    with s.lock:
        sync_now(s, force=direction)
        return deck_list(s)