import os
import re

from anki.scheduler.v3 import CardAnswer

DATA = os.getenv("ANKI_DATA", "data")
USERS_DIR = os.path.join(DATA, "users")
IDLE_SECONDS = 600  # close a user's collection after this much inactivity
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

RATINGS = {1: CardAnswer.AGAIN, 2: CardAnswer.HARD, 3: CardAnswer.GOOD, 4: CardAnswer.EASY}
LABELS = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}

SYNC_FILE = os.path.join(DATA, "sync.json")
FULL_SYNC, FULL_DOWNLOAD, FULL_UPLOAD = 2, 3, 4  # SyncCollectionResponse.ChangesRequired
PALETTE = ["#2d7d6a", "#c0562b", "#4a6fa5", "#a8478b", "#9a8420", "#6b6b6b"]