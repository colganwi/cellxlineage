from uuid import uuid4

from flask.sessions import SessionMixin

CXGUID = "cxguid"
CXG_ANNO_COLLECTION = "cxg_anno_collection"


def get_user_id(session: SessionMixin) -> str:
    """Gets a session-persistent user id. Creates one in the Flask session if non-extant"""
    if CXGUID not in session:
        session[CXGUID] = uuid4().hex
        session.permanent = True
    return session[CXGUID]


def reset_user_session(session: SessionMixin) -> None:
    """Drop the session's user id (and annotation collection) so the next
    get_user_id mints a fresh one. Used on each page (re)load in ephemeral
    hosting mode so user annotations reset on reload and never carry over
    between page loads (see server.app.app.dataset_index)."""
    session.pop(CXGUID, None)
    session.pop(CXG_ANNO_COLLECTION, None)
