"""EXPERIMENTAL (AVR-38; see avrana_gamekit.__doc__). OPTIONAL helpers: nothing in the core
primitives imports this module, and a game may serve its page any way it likes.

What is here is what two native games wrote identically: serving a fixed set of files from the
game's own origin, and the Content-Security-Policy of a game page that embeds the Party's bridge.
"""

from __future__ import annotations

from pathlib import Path

JS, CSS = "text/javascript; charset=utf-8", "text/css; charset=utf-8"
HTML, JSON, SVG = "text/html; charset=utf-8", "application/json", "image/svg+xml"


def load_files(table):
    """{path under /games/<slug>: (Path, content type)} -> {path: (bytes, content type)}. Read once
    at start: exactly these files, and nothing else, are ever served."""
    return {path: (Path(source).read_bytes(), ctype) for path, (source, ctype) in table.items()}


def page_policy(party_origin):
    """The Content-Security-Policy of a game page: its own scripts and style, requests to itself,
    and one frame, the Party's bridge, on the origin it was told (none when told nothing).
    `frame-ancestors 'none'` describes today's Party shell (the page is the top-level document);
    it is a property of that shell, not a rule of the protocol."""
    frame = party_origin or "'none'"
    return ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            f"connect-src 'self'; frame-src {frame}; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def page_headers(party_origin, page_path="/"):
    """A `page_headers` callable for GameApp: the page gets the policy, every other file the
    strictest one."""
    def headers(path):
        policy = page_policy(party_origin) if path == page_path else "default-src 'none'"
        return (("Content-Security-Policy", policy),)
    return headers
