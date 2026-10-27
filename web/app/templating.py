from pathlib import Path

from fastapi.templating import Jinja2Templates

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=BASE / "templates")