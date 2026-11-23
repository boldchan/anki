import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse

from app.templating import templates

BASE = Path(__file__).parent
DB = BASE / "meter.db"

router = APIRouter(prefix="meter")


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


with closing(db()) as c:
    c.execute(
        "CREATE TABLE IF NOT EXISTS readings ("
        "id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kwh REAL NOT NULL)"
    )
    c.commit()


def message(request: Request, items: list[tuple[str, str]], headers: dict | None = None):
    """items: [(level, text)]，level 对应 CSS 类 ok / warn / err"""
    return templates.TemplateResponse(
        request, "message.html", {"items": items}, headers=headers
    )


# ---------- 页面 ----------
@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "meter.html",
        {
            "now": datetime.now().isoformat(timespec="minutes"),
            "day_options": [7, 30, 90, 365],
            "default_days": 30,
        },
    )


# ---------- 1) 手动输入读数 ----------
@router.post("/readings", response_class=HTMLResponse)
async def add_reading(request: Request, kwh: float = Form(...), ts: str = Form("")):
    try:
        when = datetime.fromisoformat(ts) if ts else datetime.now()
    except ValueError:
        return message(request, [("err", "时间格式无效")])
    if kwh < 0:
        return message(request, [("err", "读数不能为负数")])

    when_s = when.isoformat(timespec="minutes")
    items = [("ok", f"已保存：{kwh:.1f} kWh")]
    with closing(db()) as c:
        prev = c.execute(
            "SELECT kwh FROM readings WHERE ts <= ? ORDER BY ts DESC LIMIT 1", (when_s,)
        ).fetchone()
        if prev and kwh < prev["kwh"]:
            items.append(
                ("warn", f"注意：比上一次读数（{prev['kwh']:.1f}）更小，已保存，请确认是否输错。")
            )
        c.execute("INSERT INTO readings (ts, kwh) VALUES (?, ?)", (when_s, kwh))
        c.commit()

    return message(request, items, headers={"HX-Trigger": "readings-changed"})


# ---------- 2) 历史记录（可选天数） ----------
@router.get("/history", response_class=HTMLResponse)
async def history(request: Request, days: int = Query(30, ge=1, le=3650)):
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="minutes")
    with closing(db()) as c:
        rows = c.execute(
            "SELECT * FROM ("
            "  SELECT id, ts, kwh, kwh - LAG(kwh) OVER (ORDER BY ts) AS delta FROM readings"
            ") WHERE ts >= ? ORDER BY ts DESC",
            (since,),
        ).fetchall()

    total = sum(r["delta"] for r in rows if r["delta"] is not None and r["delta"] > 0)
    return templates.TemplateResponse(
        request, "history.html", {"rows": rows, "days": days, "total": total}
    )