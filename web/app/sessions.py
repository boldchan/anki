import os
import threading
import time

from anki.collection import Collection

from .config import IDLE_SECONDS, NAME_RE, USERS_DIR


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
    
def close_all_sessions() -> None:
    for s in SESSIONS.values():
        s.col.close()

def valid_user(name: str) -> bool:
    return bool(NAME_RE.match(name)) and os.path.isdir(os.path.join(USERS_DIR, name))


def list_users() -> list[str]:
    if not os.path.isdir(USERS_DIR):
        return []
    return sorted(n for n in os.listdir(USERS_DIR) if valid_user(n))