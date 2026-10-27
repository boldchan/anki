# ---------- sync with your own anki-syncserver (optional, per user) ----------
#
# data/sync.json:
#   {"endpoint": "http://127.0.0.1:8080/",
#    "accounts": {"alice": {"user": "alice", "password": "secret"}}}
# Web users without an entry stay local-only.


import json
import time

from anki.collection import Collection

from app.config import FULL_DOWNLOAD, FULL_SYNC, FULL_UPLOAD, SYNC_FILE
from app.sessions import Session


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

def full_sync(s: Session, auth, upload: bool, usn) -> None:
    s.col.close_for_full_sync()
    try:
        s.col.full_upload_or_download(
            auth=auth, server_usn=usn if upload else None, upload=upload
        )
    finally:
        s.col.reopen(after_full_sync=True)


def sync_now(s: Session, media: bool = True, force: str | None = None) -> None:
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


def wait_media(col: Collection, timeout: float = 60) -> None:
    """sync_media() returns immediately; wait until the background transfer ends."""
    time.sleep(0.3)
    end = time.time() + timeout
    while col.media_sync_status().active and time.time() < end:
        time.sleep(0.2)
