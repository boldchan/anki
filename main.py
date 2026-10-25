"""Multi-user web front-end for Anki collections (FastAPI + anki + HTMX).

No passwords: the start page lists users, a click selects one (stored in a cookie).
Each user has their own collection: data/users/<name>/collection.anki2
Optional sync with your own anki-syncserver: see data/sync.json (README in the reply).
Run:  uvicorn main:app --host 0.0.0.0 --port 8000     (trusted network only!)
"""
import html
import json
import os
import re
import threading
import time
from datetime import date, timedelta
from urllib.parse import parse_qs

from anki.collection import Collection
from anki.scheduler.v3 import CardAnswer
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

DATA = os.getenv("ANKI_DATA", "data")
USERS_DIR = os.path.join(DATA, "users")
IDLE_SECONDS = 600  # close a user's collection after this much inactivity
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

RATINGS = {1: CardAnswer.AGAIN, 2: CardAnswer.HARD, 3: CardAnswer.GOOD, 4: CardAnswer.EASY}
LABELS = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}


# ---------- per-user sessions ----------

class Session:
    def __init__(self, name: str):
        self.name = name
        self.col = Collection(os.path.join(USERS_DIR, name, "collection.anki2"))
        self.lock = threading.Lock()
        self.cur: dict = {}
        self.last = time.time()
        self.sync_msg = ""
        self.need_choice = False


SESSIONS: dict[str, Session] = {}
REGISTRY = threading.Lock()


class NeedUser(Exception):
    pass


def valid_user(name: str) -> bool:
    return bool(NAME_RE.match(name)) and os.path.isdir(os.path.join(USERS_DIR, name))


def list_users() -> list[str]:
    if not os.path.isdir(USERS_DIR):
        return []
    return sorted(n for n in os.listdir(USERS_DIR) if valid_user(n))


def open_session(name: str) -> Session:
    now = time.time()
    with REGISTRY:
        for other, s in list(SESSIONS.items()):
            if other != name and now - s.last > IDLE_SECONDS and s.lock.acquire(False):
                try:
                    s.col.close()
                    del SESSIONS[other]
                finally:
                    s.lock.release()
        s = SESSIONS.get(name)
        if s is None:
            s = SESSIONS[name] = Session(name)
        s.last = now
        return s


def session(request: Request) -> Session:
    name = request.cookies.get("user", "")
    if not valid_user(name):
        raise NeedUser()
    return open_session(name)


app = FastAPI()
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.exception_handler(NeedUser)
def _need_user(request: Request, exc: NeedUser) -> Response:
    return Response(status_code=200, headers={"HX-Redirect": "/"})


@app.on_event("shutdown")
def _close() -> None:
    for s in SESSIONS.values():
        s.col.close()


# ---------- daily stats (all users combined) ----------

STATS_FILE = os.path.join(DATA, "stats.json")
STATS_LOCK = threading.Lock()
KEEP_DAYS = 30
SHOW_DAYS = 7


def load_stats() -> dict:
    try:
        with open(STATS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def user_totals(name: str) -> tuple[int, int]:
    """(cards studied at least once, cards due now) for one user."""
    with REGISTRY:
        s = SESSIONS.get(name)
        temp = s is None
        if temp:
            s = SESSIONS[name] = Session(name)
        created = s.last
    with s.lock:
        learned = len(s.col.find_cards("-is:new"))
        due = len(s.col.find_cards("is:due"))
    if temp:
        with REGISTRY, s.lock:
            # close again unless someone started using it meanwhile
            if s.last == created and SESSIONS.get(name) is s:
                s.col.close()
                del SESSIONS[name]
    return learned, due


def take_snapshot(day: str) -> None:
    users, learned, due = {}, 0, 0
    for name in list_users():
        l, d = user_totals(name)
        users[name] = {"learned": l, "due": d}
        learned += l
        due += d
    with STATS_LOCK:
        stats = load_stats()
        stats[day] = {"learned": learned, "due": due, "users": users}
        for old in sorted(stats)[:-KEEP_DAYS]:
            del stats[old]
        os.makedirs(DATA, exist_ok=True)
        tmp = STATS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(stats, f)
        os.replace(tmp, STATS_FILE)


def stats_loop() -> None:
    """Every hour, overwrite today's data point with the latest numbers."""
    while True:
        try:
            take_snapshot(date.today().isoformat())
        except Exception as e:  # keep the thread alive
            print("stats error:", e)
        time.sleep(3600)


@app.on_event("startup")
def _start_stats() -> None:
    threading.Thread(target=stats_loop, daemon=True).start()


PALETTE = ["#2d7d6a", "#c0562b", "#4a6fa5", "#a8478b", "#9a8420", "#6b6b6b"]


def chart_svg(title: str, labels: list, series: dict, zero_base: bool) -> str:
    """series: {user: [value or None for each label]}"""
    head = f"<h2>{html.escape(title)}"
    allv = [v for vals in series.values() for v in vals if v is not None]
    if not allv:
        return f"<div class='chart'>{head}</h2><p class='msg'>No data yet.</p></div>"
    W, H, L, R, T, B = 320, 150, 34, 12, 14, 26
    real_hi, real_lo = max(allv), (0 if zero_base else min(allv))
    lo, hi = real_lo, (real_hi if real_hi != real_lo else real_lo + 1)
    n = len(labels)

    def x(i: int) -> float:
        return L + (W - L - R) * (i / (n - 1) if n > 1 else 0.5)

    def y(v: float) -> float:
        return T + (H - T - B) * (1 - (v - lo) / (hi - lo))

    lines = legend = ""
    total = 0
    for k, (user, vals) in enumerate(sorted(series.items())):
        color = PALETTE[k % len(PALETTE)]
        pts = [(i, v) for i, v in enumerate(vals) if v is not None]
        if len(pts) > 1:
            path = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in pts)
            lines += f"<polyline points='{path}' style='stroke:{color}'/>"
        lines += "".join(
            f"<circle cx='{x(i):.1f}' cy='{y(v):.1f}' r='3' style='fill:{color}'/>"
            for i, v in pts
        )
        last = vals[-1] if vals and vals[-1] is not None else 0
        total += last
        legend += f"<span style='--c:{color}'>{html.escape(user)} {last}</span>"
    xl = "".join(
        f"<text x='{x(i):.1f}' y='{H - 8}' text-anchor='middle'>{html.escape(t)}</text>"
        for i, t in enumerate(labels)
    )
    ylab = f"<text x='{L - 6}' y='{y(real_lo) + 3:.1f}' text-anchor='end'>{real_lo}</text>"
    if real_hi != real_lo:
        ylab += f"<text x='{L - 6}' y='{y(real_hi) + 3:.1f}' text-anchor='end'>{real_hi}</text>"
    return (
        f"<div class='chart'>{head}<b>total {total}</b></h2>"
        f"<svg viewBox='0 0 {W} {H}' role='img' aria-label='{html.escape(title)}'>"
        f"<line class='axis' x1='{L}' y1='{y(real_lo):.1f}' x2='{W - R}' y2='{y(real_lo):.1f}'/>"
        f"{ylab}{lines}{xl}</svg><div class='legend'>{legend}</div></div>"
    )


def stats_html() -> str:
    stats = load_stats()
    cutoff = (date.today() - timedelta(days=SHOW_DAYS - 1)).isoformat()
    days = [d for d in sorted(stats) if d >= cutoff]
    labels = [d[5:] for d in days]
    names = sorted({u for d in days for u in stats[d].get("users", {})})

    def series(key: str) -> dict:
        return {
            u: [stats[d].get("users", {}).get(u, {}).get(key) for d in days]
            for u in names
        }

    return (
        chart_svg("Cards studied", labels, series("learned"), False)
        + chart_svg("Cards due", labels, series("due"), True)
        + "<p class='msg'>One line per user, last 7 days. Updated hourly; each day keeps its latest reading.</p>"
    )


# ---------- sync with your own anki-syncserver (optional, per user) ----------
#
# data/sync.json:
#   {"endpoint": "http://127.0.0.1:8080/",
#    "accounts": {"alice": {"user": "alice", "password": "secret"}}}
# Web users without an entry stay local-only.

SYNC_FILE = os.path.join(DATA, "sync.json")
FULL_SYNC, FULL_DOWNLOAD, FULL_UPLOAD = 2, 3, 4  # SyncCollectionResponse.ChangesRequired


def sync_conf(name: str):
    try:
        with open(SYNC_FILE) as f:
            conf = json.load(f)
    except (FileNotFoundError, ValueError):
        return None
    acct = conf.get("accounts", {}).get(name)
    if not acct:
        return None
    return conf.get("endpoint"), acct["user"], acct["password"]


def wait_media(col: Collection, timeout: float = 60) -> None:
    """sync_media() returns immediately; wait until the background transfer ends."""
    time.sleep(0.3)
    end = time.time() + timeout
    while col.media_sync_status().active and time.time() < end:
        time.sleep(0.2)


def full_sync(s: "Session", auth, upload: bool, usn) -> None:
    s.col.close_for_full_sync()
    try:
        s.col.full_upload_or_download(
            auth=auth, server_usn=usn if upload else None, upload=upload
        )
    finally:
        s.col.reopen(after_full_sync=True)


def sync_now(s: "Session", media: bool = True, force: str | None = None) -> None:
    """Sync one user's collection. Caller holds s.lock. Never raises.

    force is "up" or "down" and only matters when Anki cannot decide the
    direction itself (both sides have data and have diverged).
    """
    s.need_choice = False
    conf = sync_conf(s.name)
    if conf is None:
        s.sync_msg = ""
        return
    endpoint, user, password = conf
    s.cur.clear()
    try:
        auth = s.col.sync_login(user, password, endpoint)
        out = s.col.sync_collection(auth, False)
        req = out.required
        if req == FULL_SYNC:
            if force not in ("up", "down"):
                s.need_choice = True
                return
            req = FULL_UPLOAD if force == "up" else FULL_DOWNLOAD
        if req == FULL_UPLOAD:
            full_sync(s, auth, True, out.server_media_usn)
        elif req == FULL_DOWNLOAD:
            full_sync(s, auth, False, None)
        if media:
            s.col.sync_media(auth)
            wait_media(s.col)
        s.sync_msg = "Synced " + time.strftime("%H:%M")
    except Exception as e:
        s.sync_msg = "Sync failed: " + (str(e).strip().splitlines() or ["error"])[0]


def sync_block(s: "Session") -> str:
    if sync_conf(s.name) is None:
        return ""
    if s.need_choice:
        return (
            "<div class='sync2'><p class='msg'>This copy and the sync server both contain "
            "data and have diverged. Which one should be kept?</p><div class='actions'>"
            "<button hx-post='/fullsync/down' hx-target='#main' "
            "hx-confirm='Replace this copy with the server data?'>Keep server data</button>"
            "<button hx-post='/fullsync/up' hx-target='#main' "
            "hx-confirm='Replace the server data with this copy?'>Keep this copy</button>"
            "</div></div>"
        )
    return (
        f"<div class='sync'><span class='msg'>{html.escape(s.sync_msg)}</span>"
        "<button class='quiet' hx-post='/sync' hx-target='#main'>Sync now</button></div>"
    )


# ---------- rendering helpers ----------

def clean(text: str) -> str:
    return re.sub(r"\[anki:play:[^\]]+\]", "", text)


def user_picker(msg: str = "") -> str:
    items = "".join(
        f'<li><button hx-post="/login/{n}" hx-target="#main">{html.escape(n)}</button></li>'
        for n in list_users()
    )
    note = f"<p class='msg'>{html.escape(msg)}</p>" if msg else ""
    return (
        "<h1>Who is studying?</h1>"
        f"<ul class='decks'>{items}</ul>{note}"
        "<form class='new' hx-post='/newuser' hx-target='#main'>"
        "<input name='name' placeholder='New user name' maxlength='32' required>"
        "<button>Add</button></form>"
        + stats_html()
    )


def deck_list(s: Session) -> str:
    items = "".join(
        f'<li><button hx-post="/study/{d.id}" hx-target="#main">'
        f"{html.escape(d.name)}</button></li>"
        for d in s.col.decks.all_names_and_ids()
    )
    return (
        f"<div class='bar'><span>{html.escape(s.name)}</span>"
        "<button class='quiet' hx-post='/logout' hx-target='#main'>Switch user</button></div>"
        f"<h1>Decks</h1><ul class='decks'>{items}</ul>{sync_block(s)}"
    )


def counts_bar(s: Session) -> str:
    new, learn, review = s.col.sched.counts()
    return (
        f"<div class='bar'><button class='quiet' hx-get='/decks' hx-target='#main'>"
        f"Decks</button><span>{new} new · {learn} learning · {review} due</span></div>"
    )


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


# ---------- routes ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> str:
    name = request.cookies.get("user", "")
    if not valid_user(name):
        return PAGE.replace("{{MAIN}}", user_picker())
    s = open_session(name)
    with s.lock:
        sync_now(s)
        return PAGE.replace("{{MAIN}}", deck_list(s))


@app.post("/login/{name}", response_class=HTMLResponse)
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


@app.get("/decks", response_class=HTMLResponse)
def decks(s: Session = Depends(session)) -> str:
    with s.lock:
        sync_now(s, media=False)
        return deck_list(s)


@app.post("/sync", response_class=HTMLResponse)
def sync_route(s: Session = Depends(session)) -> str:
    with s.lock:
        sync_now(s)
        return deck_list(s)


@app.post("/fullsync/{direction}", response_class=HTMLResponse)
def fullsync(direction: str, s: Session = Depends(session)) -> str:
    if direction not in ("up", "down"):
        raise HTTPException(404)
    with s.lock:
        sync_now(s, force=direction)
        return deck_list(s)


@app.post("/study/{deck_id}", response_class=HTMLResponse)
def study(deck_id: int, s: Session = Depends(session)) -> str:
    with s.lock:
        s.col.decks.set_current(deck_id)
        return next_card(s)


@app.post("/show/{card_id}", response_class=HTMLResponse)
def show(card_id: int, s: Session = Depends(session)) -> str:
    with s.lock:
        if not s.cur or s.cur["card"].id != card_id:
            return next_card(s)
        return card_view(s, answer=True)


@app.post("/rate/{card_id}/{ease}", response_class=HTMLResponse)
def rate(card_id: int, ease: int, s: Session = Depends(session)) -> str:
    with s.lock:
        if s.cur and s.cur["card"].id == card_id and ease in RATINGS:
            ans = s.col.sched.build_answer(
                card=s.cur["card"], states=s.cur["states"], rating=RATINGS[ease]
            )
            s.col.sched.answer_card(ans)
        return next_card(s)


@app.get("/media/{name}")
def media(name: str, s: Session = Depends(session)):
    path = os.path.join(s.col.media.dir(), os.path.basename(name))
    if not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path)


PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="/media/">
<title>Flashcards</title>
<script src="/static/htmx.min.js"></script>
<style>
:root{--bg:#fbfaf7;--fg:#1d1b18;--mute:#6f6a62;--line:#ddd8cf;--card:#fff;--accent:#2d5a4a}
@media (prefers-color-scheme:dark){
:root{--bg:#161512;--fg:#ece8e0;--mute:#9a948a;--line:#34312b;--card:#1f1d19;--accent:#7fb8a2}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
#main{max-width:34rem;margin:0 auto;padding:1.25rem 1rem 3rem}
h1{font:600 1.4rem Georgia,"Noto Serif",serif;margin:1rem 0}
button{font:inherit;color:var(--fg);background:var(--card);border:1px solid var(--line);
border-radius:6px;padding:.7rem 1rem;cursor:pointer}
button:hover{border-color:var(--accent)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.decks{list-style:none;margin:0;padding:0;display:grid;gap:.5rem}
.decks button{width:100%;text-align:left}
.bar{display:flex;justify-content:space-between;align-items:center;
color:var(--mute);font-size:.9rem;margin-bottom:1rem}
.new{display:flex;gap:.5rem;margin-top:1.25rem}
.new input{flex:1;min-width:0;font:inherit;padding:.7rem;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
.msg{color:var(--mute);font-size:.9rem}
.sync{display:flex;justify-content:space-between;align-items:center;margin-top:1.25rem}
.sync2{margin-top:1.25rem}
.chart h2{font:600 1rem system-ui,sans-serif;margin:1.75rem 0 .25rem;display:flex;justify-content:space-between;align-items:baseline}
.chart svg{width:100%;height:auto;display:block}
.chart svg text{font-size:9px;fill:var(--mute)}
.chart polyline{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round}
.chart circle{fill:var(--accent)}
.chart .axis{stroke:var(--line)}
.legend{display:flex;flex-wrap:wrap;gap:.25rem .9rem;font-size:.85rem;color:var(--mute)}
.legend span::before{content:'';display:inline-block;width:.6rem;height:.6rem;border-radius:50%;background:var(--c);margin-right:.3rem}
.quiet{border:0;background:none;color:var(--mute);padding:.3rem 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:2rem 1.25rem;min-height:12rem;display:flex;flex-direction:column;
justify-content:center;align-items:center;text-align:center;
font:1.6rem/1.45 Georgia,"Noto Serif",serif}
.card img{max-width:100%}
.actions{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:.5rem;margin-top:1rem}
.show{background:var(--accent);color:var(--bg);border-color:var(--accent)}
.cloze{color:var(--accent);font-weight:600}
</style></head>
<body><main id="main">{{MAIN}}</main>
<script>
document.addEventListener("keydown",e=>{
  const b=document.querySelector('[data-key="'+e.key+'"]');
  if(b){e.preventDefault();b.click();}
});
</script></body></html>"""
