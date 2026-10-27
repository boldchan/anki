from fastapi import Request

from app.sessions import Session, open_session, valid_user


class NeedUser(Exception):
    pass

def session(request: Request) -> Session:
    name = request.cookies.get("user", "")
    if not valid_user(name):
        raise NeedUser()
    return open_session(name)