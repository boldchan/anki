import math
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse

from app.templating import templates

BASE = Path(__file__).parent
DB = BASE / "meter.db"
DAY_OPTIONS = [7, 30, 90, 365]
DEFAULT_DAYS = 30

router = APIRouter(prefix="/meter")


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


# ---------- 折线图（后端直接算出 SVG 坐标） ----------
W, H = 1000, 290
LEFT, RIGHT, TOP, BOTTOM = 56, 24, 28, 40


def nice_step(span: float, n: int = 4) -> float:
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def build_chart(rows, start: datetime, end: datetime, days: int):
    pts = sorted((datetime.fromisoformat(r["ts"]), r["kwh"]) for r in rows)
    if len(pts) < 2:
        return None

    x0, x1, y0, y1 = LEFT, W - RIGHT, TOP, H - BOTTOM
    t0, t1 = start.timestamp(), end.timestamp()
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    step = nice_step((hi - lo) or 1)
    ymin, ymax = math.floor(lo / step) * step, math.ceil(hi / step) * step
    if ymax == ymin:
        ymax += step

    def X(t):
        return x0 + min(max((t.timestamp() - t0) / (t1 - t0), 0), 1) * (x1 - x0)

    def Y(v):
        return y1 - (v - ymin) / (ymax - ymin) * (y1 - y0)

    coords = [(round(X(t), 1), round(Y(v), 1)) for t, v in pts]
    line = " ".join(f"{x},{y}" for x, y in coords)
    area = f"{line} {coords[-1][0]},{y1} {coords[0][0]},{y1}"

    yticks, v = [], ymin
    while v <= ymax + 1e-9:
        yticks.append((round(Y(v), 1), f"{v:g}"))
        v += step

    fmt = "%m-%d" if days <= 90 else "%Y-%m"
    xticks = [
        (round(x0 + (x1 - x0) * i / 6, 1), (start + (end - start) * i / 6).strftime(fmt))
        for i in range(7)
    ]
    last_x, last_y = coords[-1]
    return {
        "w": W, "h": H, "x0": x0, "x1": x1, "y1": y1,
        "line": line, "area": area, "yticks": yticks, "xticks": xticks,
        "last": (last_x, last_y, max(last_y - 12, 16), f"{pts[-1][1]:.1f}"),
        "first_value": f"{pts[0][1]:.1f}", "last_value": f"{pts[-1][1]:.1f}",
    }


# ---------- 页面数据：读数、统计、历史、图表共用同一份 ----------
def dashboard(days: int) -> dict:
    end = datetime.now()
    start = end - timedelta(days=days)
    with closing(db()) as c:
        # 先对全表算与上一条的差值，再按时间过滤，窗口内第一条也有差值
        rows = c.execute(
            "SELECT * FROM ("
            "  SELECT id, ts, kwh, kwh - LAG(kwh) OVER (ORDER BY ts) AS delta FROM readings"
            ") WHERE ts >= ? ORDER BY ts DESC",
            (start.isoformat(timespec="minutes"),),
        ).fetchall()
        latest = c.execute(
            "SELECT ts, kwh FROM readings ORDER BY ts DESC LIMIT 1"
        ).fetchone()

    total = sum(r["delta"] for r in rows if r["delta"] is not None and r["delta"] > 0)
    digits, dec = [], ""
    if latest:
        integer, dec = f"{latest['kwh']:07.1f}".split(".")
        digits = list(integer)
    return {
        "days": days, "rows": rows, "total": total, "avg": total / days,
        "latest": latest, "digits": digits, "dec": dec,
        "chart": build_chart(rows, start, end, days),
    }


def message(request: Request, items: list[tuple[str, str]], headers: dict | None = None):
    return templates.TemplateResponse(request, "message.html", {"items": items}, headers=headers)


# ---------- 页面 ----------
@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    ctx = dashboard(DEFAULT_DAYS) | {
        "oob": False,
        "now": datetime.now().isoformat(timespec="minutes"),
        "today": datetime.now().strftime("%Y 年 %m 月 %d 日"),
        "day_options": DAY_OPTIONS,
    }
    return templates.TemplateResponse(request, "meter.html", ctx)


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


# ---------- 2) 历史记录（可选天数）：同时刷新当前读数、统计、图表 ----------
@router.get("/history", response_class=HTMLResponse)
async def history(request: Request, days: int = Query(DEFAULT_DAYS, ge=1, le=3650)):
    return templates.TemplateResponse(
        request, "history.html", dashboard(days) | {"oob": True}
    )
