

import re

from requests import Session

from app.config import LABELS


def counts_bar(s: Session) -> str:
    new, learn, review = s.col.sched.counts()
    return (
        f"<div class='bar'><button class='quiet' hx-get='/decks' hx-target='#main'>"
        f"Decks</button><span>{new} new · {learn} learning · {review} due</span></div>"
    )


def clean(text: str) -> str:
    return re.sub(r"\[anki:play:[^\]]+\]", "", text)


def card_view(s: Session, answer: bool) -> str:
    card = s.cur["card"]
    out = card.render_output()
    body = clean(out.answer_text if answer else out.question_text)
    if answer:
        actions = "".join(
            f'<button class="r{e}" data-key="{e}" '
            f'hx-post="/rate/{card.id}/{e}" hx-target="#main">{LABELS[e]}</button>'
            for e in (1, 2, 3, 4)
        )
    else:
        actions = (
            f'<button class="show" data-key=" " hx-post="/show/{card.id}" '
            f'hx-target="#main">Show answer</button>'
        )
    return (
        f"{counts_bar(s)}<style>{out.css}</style>"
        f"<div class='card'>{body}</div><div class='actions'>{actions}</div>"
    )


def next_card(s: Session) -> str:
    queued = s.col.sched.get_queued_cards(fetch_limit=1)
    if not queued.cards:
        s.cur.clear()
        return (
            f"{counts_bar(s)}<div class='card'><p>All done for now.</p></div>"
            "<div class='actions'><button hx-get='/decks' hx-target='#main'>"
            "Back to decks</button></div>"
        )
    qc = queued.cards[0]
    card = s.col.get_card(qc.card.id)
    card.start_timer()
    s.cur.update(card=card, states=qc.states)
    return card_view(s, answer=False)