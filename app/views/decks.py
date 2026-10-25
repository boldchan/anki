import html

from app.sessions import Session, list_users
from app.sync import sync_conf
from app.views.charts import stats_html


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

def sync_block(s: Session) -> str:
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