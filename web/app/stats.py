

import json
import os
import threading
import time
from datetime import date

from app.config import DATA
from app.sessions import REGISTRY, SESSIONS, Session, list_users

STATS_FILE = os.path.join(DATA, "stats.json")


def load_stats() -> dict:
    try:
        with open(STATS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


STATS_LOCK = threading.Lock()
KEEP_DAYS = 30
SHOW_DAYS = 7


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