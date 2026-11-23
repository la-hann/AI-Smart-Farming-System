from hashlib import sha256
from time import time

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert

from models import LoginAttempt, db


def permit_request(scope, actor, maximum):
    window = int(time() // 900)
    key = sha256(f"{scope}:{actor}".encode()).hexdigest()
    table = LoginAttempt.__table__
    statement = insert(table).values(key=key, window=window, attempts=1)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.key, table.c.window],
        set_={"attempts": table.c.attempts + 1},
        where=table.c.attempts < maximum,
    ).returning(table.c.attempts)
    allowed = db.session.execute(statement).scalar_one_or_none() is not None
    db.session.execute(delete(LoginAttempt).where(LoginAttempt.window < window - 1))
    db.session.commit()
    return allowed
