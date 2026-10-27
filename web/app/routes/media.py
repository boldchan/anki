import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.deps import session
from app.sessions import Session

router = APIRouter()

@router.get("/media/{name}")
def media(name: str, s: Annotated[Session, Depends(session)]):
    path = os.path.join(s.col.media.dir(), os.path.basename(name))
    if not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path)