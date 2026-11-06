from __future__ import annotations

import datetime as dt
import hashlib

ONE = dt.timedelta(days=1)


def td(n: int) -> dt.timedelta:
    return dt.timedelta(days=n)


def daterange(a: dt.date, b: dt.date):
    return [a + td(i) for i in range((b - a).days + 1)]


def next_bd(d: dt.date) -> dt.date:
    while d.weekday() >= 5:
        d += ONE
    return d


def prev_bd(d: dt.date) -> dt.date:
    while d.weekday() >= 5:
        d -= ONE
    return d


def bdays(a: dt.date, b: dt.date):
    return [d for d in daterange(a, b) if d.weekday() < 5]


def last_bd_of_month(y: int, m: int) -> dt.date:
    nxt = dt.date(y + (m == 12), (m % 12) + 1, 1)
    return prev_bd(nxt - ONE)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
