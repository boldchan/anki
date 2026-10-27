from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.deps import session
from app.sessions import Session
from app.sync import sync_now
from app.views.decks import deck_list

router = APIRouter()

@router.get("/decks", response_class=HTMLResponse)
def decks(s: Annotated[Session, Depends(session)]) -> str:
    with s.lock:
        sync_now(s, media=False)
        return deck_list(s)