from datetime import date, datetime

from sqlalchemy import inspect as sa_inspect


def jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def row(obj, exclude=()):
    """Serialise a SQLAlchemy row to a plain dict keyed by column name (handles attribute/column name
    differences such as Document.metadata_ -> "metadata")."""
    if obj is None:
        return None
    out = {}
    for attr in sa_inspect(obj).mapper.column_attrs:
        name = attr.columns[0].name
        if name in exclude or attr.key in exclude:
            continue
        out[name] = jsonable(getattr(obj, attr.key))
    return out
