from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.config import RATINGS
from app.deps import session
from app.sessions import Session
from app.views.cards import card_view, next_card

router = APIRouter()

@router.post("/study/{deck_id}", response_class=HTMLResponse)
def study(deck_id: int, s: Annotated[Session, Depends(session)]) -> str:
    with s.lock:
        s.col.decks.set_current(deck_id)
        return next_card(s)


@router.post("/show/{card_id}", response_class=HTMLResponse)
def show(card_id: int, s: Annotated[Session, Depends(session)]) -> str:
    with s.lock:
        if not s.cur or s.cur["card"].id != card_id:
            return next_card(s)
        return card_view(s, answer=True)


@router.post("/rate/{card_id}/{ease}", response_class=HTMLResponse)
def rate(card_id: int, ease: int, s: Annotated[Session, Depends(session)]) -> str:
    with s.lock:
        if s.cur and s.cur["card"].id == card_id and ease in RATINGS:
            ans = s.col.sched.build_answer(
                card=s.cur["card"], states=s.cur["states"], rating=RATINGS[ease]
            )
            s.col.sched.answer_card(ans)
        return next_card(s)