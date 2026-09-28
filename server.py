"""GAMEHUB server — the hub page plus every game in games/registry.py.

Per game <slug>:
    /games/<slug>/ws     WebSocket (core.net.GameBinding)
    /games/<slug>/       the game's static client
    /games/<slug>/avrana/session/v0/launch   Avrana party session launch (core/party_session.py;
                         only games with a key in $AVRANA_PARTY_KEYS; loopback, unproxied, signed)
    /games/<slug>/avrana/session/v0/end      ... and end for everyone (same guards)
    (the game's `ended` report goes out to $AVRANA_PARTY_URL; this server accepts none)
Shared:
    /                    hub page (web/hub.html)
    /api/games           registry for the hub cards
    /shared/*            shared css/js (design tokens, identity, qr)
    /health
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from core import avatars, chatmedia, party_protocol, party_session, venue
from core.chat import ChatHub
from core.net import GameBinding
from games.registry import REGISTRY, EXTERNAL, COMING_SOON
from games.wordclash.app import wc_app

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gamehub")

WEB = Path(__file__).parent / "web"
PORT = int(os.environ.get("LANGAMES_PORT", "8096"))   # override to run a second instance

app = FastAPI(title="GAMEHUB")
bindings: dict[str, GameBinding] = {}
# Avrana party sessions: both halves or neither (deploy/avrana-party-session.conf)
party_sides, party_url = party_session.configure(os.environ)

for entry in REGISTRY:
    slug = entry["slug"]
    binding = GameBinding(slug, entry["session"](), party=party_sides.get(slug),
                          party_url=party_url)
    bindings[slug] = binding

    def _make_ws(b: GameBinding):
        async def ws_endpoint(ws: WebSocket):
            await b.endpoint(ws)
        return ws_endpoint

    app.add_api_websocket_route("/games/%s/ws" % slug, _make_ws(binding))

# Private venue aliases preserve old bookmarks after a game is renamed, while
# the public repository remains generic. They are read at process start because
# routes themselves are part of the FastAPI application.
occupied_game_slugs = set(bindings) | {entry["slug"] for entry in EXTERNAL}
for old_slug, current_slug in venue.route_aliases(
        occupied_game_slugs, bindings).items():
    app.add_api_websocket_route(
        "/games/%s/ws" % old_slug, _make_ws(bindings[current_slug]),
        name="legacy-ws-%s" % old_slug)

    def _make_redirect(target_slug: str):
        async def redirect_to_current():
            return RedirectResponse("/games/%s/" % target_slug,
                                    status_code=307)
        return redirect_to_current

    redirect = _make_redirect(current_slug)
    app.add_api_route("/games/%s" % old_slug, redirect, methods=["GET"],
                      name="legacy-%s" % old_slug, include_in_schema=False)
    app.add_api_route("/games/%s/" % old_slug, redirect, methods=["GET"],
                      name="legacy-slash-%s" % old_slug,
                      include_in_schema=False)


@app.get("/api/games")
async def api_games():
    return JSONResponse({
        "avranaIntegration": "avrana.lan-launch/v1",
        "games": [{
            "slug": e["slug"],
            # venue.json may rename a game for this house (see core/venue.py);
            # the registry keeps the generic, public name.
            "title": venue.title_for(e["slug"], e["title"]),
            "icon": e["icon"],
            "blurb": e["blurb"], "players": e["players"],
            "category": e.get("category"), "accent": e.get("accent"),
            "art": e.get("art"),
            "tagline": e.get("tagline"), "tv": e.get("tv", False),
            "min_p": e.get("min_p"), "max_p": e.get("max_p"),
            "solo": e.get("solo", False),
            "hidden": e.get("hidden", False),
            # only where this server holds the game's key and can really verify its tickets
            **({"avranaSession": party_protocol.VERSION}
               if bindings[e["slug"]].party is not None else {}),
            "live": {
                "players": len(bindings[e["slug"]].session.humans()),
                "phase": bindings[e["slug"]].session.phase,
            },
        } for e in REGISTRY],
        "external": EXTERNAL,
        "coming_soon": COMING_SOON,
    })


def _refuse(status, error):
    return JSONResponse({"ok": False, "error": error}, status_code=status,
                        headers={"Cache-Control": "no-store"})


async def _party_message(slug, request, apply):
    """The shared guards of the party's server-to-server routes: a game with a party side,
    this machine only and never through nginx (phones cannot call it), 8 KiB, a JSON body
    {"message": …}; then `apply(binding, message)` verifies the signed message itself."""
    b = bindings.get(slug)
    if b is None or b.party is None:
        return _refuse(404, "no_party_session")
    client = request.client.host if request.client else None
    if not party_session.local_unproxied(client, request.headers):
        return _refuse(403, "not_local")
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        return _refuse(400, "bad_request")
    if declared > party_session.MAX_BODY:
        return _refuse(413, "too_large")
    raw = await request.body()
    if len(raw) > party_session.MAX_BODY:
        return _refuse(413, "too_large")
    try:
        body = json.loads(raw)
        message = body["message"]
    except (ValueError, TypeError, KeyError):
        return _refuse(400, "bad_request")
    try:
        await apply(b, message)
    except party_protocol.Invalid as e:
        return _refuse(403, "bad_message:%s" % e)
    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})


@app.post("/games/{slug}/avrana/session/v0/launch")
async def party_session_launch(slug: str, request: Request):
    """The party starts a session of this game with a signed roster (core/party_session.py)."""
    return await _party_message(slug, request, lambda b, m: b.party_launch(m))


@app.post("/games/{slug}/avrana/session/v0/end")
async def party_session_end(slug: str, request: Request):
    """The party ends this game's session for everyone: the room goes back to a non-running
    state and that session's tickets die (core/net.py GameBinding.party_end)."""
    return await _party_message(slug, request, lambda b, m: b.party_end(m))


@app.get("/api/venue")
async def api_venue():
    """This venue's personalization: branding + optional guest Wi-Fi.

    Generic defaults live in core/venue.py; your own values go in the gitignored
    data/venue.json (copy venue.example.json). A public clone with no venue.json
    gets the generic "LAN GAMES" brand and no Wi-Fi block, so the hub shows a
    blank Wi-Fi button that opens setup instructions.

    NOTE: the Wi-Fi password is served to anyone who can reach this endpoint —
    that is deliberate (guests scan the QR), but put your GUEST SSID here, not
    your admin network."""
    config = venue.load()
    brand = config.get("brand") if isinstance(config.get("brand"), dict) else {}
    wifi = config.get("wifi") if isinstance(config.get("wifi"), dict) else None
    return JSONResponse({
        "brand": {
            "name": brand.get("name") or venue.DEFAULTS["brand"]["name"],
            "presents": (brand.get("presents")
                         or venue.DEFAULTS["brand"]["presents"]),
        },
        "wifi": ({
            "ssid": wifi.get("ssid") or "",
            "password": wifi.get("password") or "",
            "security": wifi.get("security") or "",
            "hidden": bool(wifi.get("hidden")),
        } if wifi else None),
    })


def _valid_token(token):
    return (isinstance(token, str) and 8 <= len(token) <= 64
            and not token.startswith("bot:")
            and token.replace("-", "").replace("_", "").isalnum())


@app.post("/api/avatar")
async def upload_avatar(request: Request):
    token = request.headers.get("x-wc-token", "")
    if not _valid_token(token):
        return JSONResponse({"error": "bad token"}, status_code=400)
    if int(request.headers.get("content-length") or 0) > avatars.MAX_BYTES:
        return JSONResponse({"error": "image too large (8MB max)"},
                            status_code=413)
    body = await request.body()
    try:
        url = avatars.save(token, body)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=415)
    return JSONResponse({"url": url})


@app.delete("/api/avatar")
async def delete_avatar(request: Request):
    token = request.headers.get("x-wc-token", "")
    if not _valid_token(token):
        return JSONResponse({"error": "bad token"}, status_code=400)
    avatars.remove(token)
    return JSONResponse({"ok": True})


chat = ChatHub()


@app.websocket("/chat/ws")
async def chat_ws(ws: WebSocket):
    await chat.endpoint(ws)


@app.post("/api/chatmedia")
async def upload_chatmedia(request: Request):
    token = request.headers.get("x-wc-token", "")
    if not _valid_token(token):
        return JSONResponse({"error": "bad token"}, status_code=400)
    if int(request.headers.get("content-length") or 0) > chatmedia.MAX_BYTES:
        return JSONResponse({"error": "image too large (16MB max)"},
                            status_code=413)
    body = await request.body()
    try:
        return JSONResponse(chatmedia.save(body))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=415)


@app.get("/api/charades/decks")
async def charades_decks():
    from games.charades.decks import deck_list
    return JSONResponse({"decks": deck_list()})


@app.get("/health")
async def health():
    return JSONResponse({"ok": True, "games": {
        s: {"phase": b.session.phase, "players": len(b.session.players)}
        for s, b in bindings.items()}})


@app.get("/")
async def hub():
    return FileResponse(WEB / "hub.html", headers={"Cache-Control": "no-cache"})


@app.get("/offline")
async def offline():
    return FileResponse(WEB / "offline.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
async def service_worker():
    return FileResponse(WEB / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache",
                                 "Service-Worker-Allowed": "/"})


@app.get("/app.webmanifest")
async def app_manifest():
    """Install metadata with this venue's private wordmark when configured."""
    manifest = json.loads((WEB / "app.webmanifest").read_text(encoding="utf-8"))
    name = str(venue.brand().get("name") or manifest["name"]).strip()
    manifest["name"] = name
    manifest["short_name"] = name
    return JSONResponse(manifest, media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.middleware("http")
async def cache_headers(request, call_next):
    resp = await call_next(request)
    p = request.url.path
    if "/fonts/" in p:
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif p.startswith("/chatmedia/"):
        # content-addressed filenames -> safe to cache hard
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif p.startswith("/avatars/"):
        # URLs carry ?v=<mtime>, so long caching is safe
        resp.headers["Cache-Control"] = "public, max-age=86400"
    else:
        resp.headers["Cache-Control"] = "no-cache"
    return resp


# WORDCLASH runs as a mounted sub-app (its own Room engine + WS), sharing this
# process, venv, origin, and — via core.avatars — the same photo store.
app.mount("/games/wordclash", wc_app)

# static mounts LAST so /api, /health, and the ws routes win
for entry in REGISTRY:
    app.mount("/games/%s" % entry["slug"],
              StaticFiles(directory=entry["web"], html=True),
              name="game-%s" % entry["slug"])
app.mount("/shared", StaticFiles(directory=WEB), name="shared")
avatars.AVATAR_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=avatars.AVATAR_DIR), name="avatars")
chatmedia.CHAT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/chatmedia", StaticFiles(directory=chatmedia.CHAT_DIR), name="chatmedia")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
