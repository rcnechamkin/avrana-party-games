"""EXPERIMENTAL (AVR-38; see avrana_gamekit.__doc__). Core primitive: strict, bounded JSON.

A request body is exactly one JSON object with exactly the keys the route names, each passing a
check. Duplicate keys, NaN/Infinity, wrong shapes, lone surrogates and oversized numbers are all
refused with `Bad`.
"""

from __future__ import annotations

import json
from typing import NamedTuple

MAX_BODY = 16384                # bytes a request may declare; enforced by the server
MAX_INT = 2 ** 53               # what a JSON number holds exactly everywhere


class Bad(Exception):
    """A request that is not acceptable JSON of the expected shape."""


def STR(value):
    """A string that can be written out as UTF-8 (JSON allows a lone surrogate, which cannot)."""
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def bounded(limit):
    """A check for a string of at most `limit` characters."""
    return lambda value: STR(value) and len(value) <= limit


def INT(value):
    return type(value) is int and abs(value) <= MAX_INT


def INTS(value):
    return isinstance(value, list) and len(value) <= 64 and all(INT(item) for item in value)


def strict_json(raw, **fields):
    """The body as a dict with exactly the keys named in `fields`, each passing its check."""
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise Bad("duplicate key")
            out[key] = value
        return out

    def no_constant(name):
        raise Bad("bad number")
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=no_constant)
    except (ValueError, RecursionError):
        raise Bad("bad json")
    if not isinstance(body, dict) or set(body) != set(fields) \
            or not all(check(body[key]) for key, check in fields.items()):
        raise Bad("bad shape")
    return body


class Reply(NamedTuple):
    status: int
    ctype: str
    body: bytes
    headers: tuple = ()          # extra (name, value) pairs


def json_reply(status, body):
    return Reply(status, "application/json", json.dumps(body, sort_keys=True).encode())
