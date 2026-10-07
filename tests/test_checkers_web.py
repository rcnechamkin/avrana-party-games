"""The Checkers page (AVR-238): what it is made of, what it may and may not do, and how it behaves
against the real server.

  * The files in checkers/web are checked as text and as markup: the page contract (language,
    viewport, one module script, no inline script or style), the accessibility basics a test can
    see (names, live regions, a safe default in the confirmation), the things the page must never
    use (cookies, storage, a Party API call of its own), and onboarding.json against the rules.
  * tests/checkers_board_test.mjs (the pure logic) and tests/checkers_page_test.mjs (the page, run
    on a fake DOM against this server with real tickets) run under Node, as the CI static job and
    this file both do. Without Node on the machine those tests are skipped here.

No browser is started. What a browser shows (layout, the bridge's iframe, a real finger) is the
Party-side browser test of the two phones, which waits for avrana-party#87.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import party_protocol as protocol
from checkers import party, rules, server

WEB = ROOT / "checkers" / "web"
GAME = "checkers"
BASE = party.BASE
SID, SID2 = "session-" + "a" * 32, "session-" + "b" * 32
ANA, BEN, CAL = ("participant-" + c * 32 for c in "abc")
PARTY_ORIGIN = "https://party.example"
NODE = shutil.which("node")


def text(name):
    return (WEB / name).read_text(encoding="utf-8")


SOURCES = {name: text(name) for name in ("index.html", "checkers.js", "app.mjs", "board.mjs", "checkers.css", "icon.svg")}
SCRIPTS = {name: SOURCES[name] for name in ("checkers.js", "app.mjs", "board.mjs")}


# ---- the page ----------------------------------------------------------------------------------

class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []           # (tag, attributes) in document order
        self.inside = []
        self.inline_script = ""
        self.titles = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))
        self.inside.append(tag)

    def handle_endtag(self, tag):
        if tag in self.inside:
            while self.inside.pop() != tag:
                pass

    def handle_data(self, data):
        if self.inside and self.inside[-1] == "script":
            self.inline_script += data
        if self.inside and self.inside[-1] == "title":
            self.titles.append(data)

    def all(self, tag):
        return [attrs for name, attrs in self.elements if name == tag]

    @property
    def ids(self):
        return [attrs["id"] for _, attrs in self.elements if "id" in attrs]


PAGE = Page(SOURCES["index.html"])


def exported_ids():
    match = re.search(r"export const IDS = \[(.*?)\];", SOURCES["app.mjs"], re.S)
    return re.findall(r"'([^']+)'", match.group(1))


def test_the_page_states_its_language_viewport_title_and_one_heading():
    assert SOURCES["index.html"].lstrip().lower().startswith("<!doctype html>")
    assert PAGE.all("html")[0]["lang"] == "en"
    assert PAGE.all("meta")[0].get("charset", "").lower() == "utf-8"
    viewport = [m for m in PAGE.all("meta") if m.get("name") == "viewport"][0]["content"]
    assert "width=device-width" in viewport and "initial-scale=1" in viewport and "maximum-scale" not in viewport
    assert "".join(PAGE.titles).strip() == "Checkers"
    assert len(PAGE.all("h1")) == 1


def test_the_page_runs_one_module_script_and_has_no_inline_code_or_style():
    scripts = PAGE.all("script")
    assert [(s.get("type"), s.get("src")) for s in scripts] == [("module", "web/checkers.js")]
    assert PAGE.inline_script.strip() == ""
    assert not PAGE.all("style") and not PAGE.all("form") and not PAGE.all("input") and not PAGE.all("iframe")
    for tag, attrs in PAGE.elements:
        assert "style" not in attrs, tag
        assert not [a for a in attrs if a.startswith("on")], (tag, attrs)
    for tag, attrs in PAGE.elements:
        for attribute in ("src", "href"):
            if attribute in attrs:
                assert re.fullmatch(r"web/[a-z.]+", attrs[attribute]), (tag, attrs[attribute])      # its own files, relative


def test_every_element_the_script_asks_for_is_on_the_page_once():
    ids = PAGE.ids
    assert len(ids) == len(set(ids))
    assert set(exported_ids()) <= set(ids)
    assert len(exported_ids()) == len(set(exported_ids()))
    for tag, attrs in PAGE.elements:
        for attribute in ("aria-labelledby", "aria-describedby", "for"):
            for target in attrs.get(attribute, "").split():
                assert target in ids, (tag, attribute, target)


def test_what_a_screen_reader_needs_is_there():
    by_id = {attrs["id"]: (tag, attrs) for tag, attrs in PAGE.elements if "id" in attrs}
    assert by_id["status"][1]["role"] == "status"
    assert by_id["live"][1]["aria-live"] == "polite"
    assert by_id["board"][1]["role"] == "group" and by_id["board"][1]["aria-label"]
    assert by_id["board"][1]["aria-describedby"] == "summary"
    for dialog in ("rules", "confirm"):
        assert by_id[dialog][0] == "dialog" and by_id[dialog][1]["aria-labelledby"]
    for tag, attrs in PAGE.elements:
        if tag == "button":
            assert attrs.get("type") == "button", attrs
    # The confirmation's safe choice comes first and has the focus; the destructive one does not.
    order = [attrs["id"] for tag, attrs in PAGE.elements if tag == "button" and attrs.get("id", "").startswith("confirm-")]
    assert order == ["confirm-no", "confirm-yes"]
    assert "autofocus" in by_id["confirm-no"][1] and "autofocus" not in by_id["confirm-yes"][1]
    assert "danger" in by_id["confirm-yes"][1]["class"] and "danger" in by_id["resign"][1]["class"]


def test_there_is_a_place_for_everything_the_script_shows_and_the_rest_starts_hidden():
    by_id = {attrs["id"]: attrs for _, attrs in PAGE.elements if "id" in attrs}
    for hidden in ("end", "table", "result", "result-actions", "resign", "top-turn", "bottom-turn"):
        assert "hidden" in by_id[hidden], hidden
    assert "hidden" not in by_id["rules-open"] and "hidden" not in by_id["status"]


# ---- what the page may not do ------------------------------------------------------------------

FORBIDDEN = ("document.cookie", "localStorage", "sessionStorage", "indexedDB", "XMLHttpRequest", "WebSocket",
             "EventSource", "sendBeacon", "eval(", "new Function", "innerHTML", "outerHTML", "insertAdjacentHTML",
             "document.write", "importScripts", "serviceWorker", "postMessage", "window.open", "location.href",
             "location.assign", "location.replace", ".style.", "setAttribute('style'", 'setAttribute("style"')


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_the_scripts_use_no_cookie_storage_markup_injection_or_navigation(name):
    for word in FORBIDDEN:
        assert word not in SCRIPTS[name], (name, word)


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_nothing_is_loaded_from_anywhere_but_this_server(name):
    for url in re.findall(r"""(?:https?:)?//[^\s"'<>)]+""", SOURCES[name]):
        assert url in ("http://www.w3.org/2000/svg",), (name, url)           # an XML namespace, not a request


def test_the_page_reaches_the_party_only_through_the_bridge_and_its_own_server_only_by_relative_paths():
    app = SOURCES["app.mjs"]
    assert not re.search(r"^\s*import\b", app, re.M) and "import(" not in app           # it imports nothing: checkers.js does
    assert "env.connectParty" in app and "env.board" in app
    assert re.search(r"connect\(\{ partyOrigin: origin, game: GAME \}\)", app)
    assert "partyOrigin +" not in app and "+ partyOrigin" not in app and "${origin" not in app and "origin +" not in app
    assert "'/party" not in app and '"/party' not in app
    routes = set(re.findall(r"'(api/[a-z]+|onboarding\.json)'", app))
    assert routes == {"api/party", "api/redeem", "api/poll", "api/move", "api/resign", "onboarding.json"}
    served = {path.removeprefix(BASE + "/") for path in (server.PARTY, server.ONBOARDING, *server.POSTS)}
    assert routes == served                                                    # every route the page uses is one the server has
    assert "credentials: 'omit'" in app and app.count("credentials: 'omit'") == 3 and "cache: 'no-store'" in app
    boot = SOURCES["checkers.js"]
    assert re.findall(r"load\('(\./[a-z.-]+)'\)", boot) == ["./app.mjs", "./board.mjs", "./avrana-party-bridge.js"]
    assert "fetch(" not in boot and "?retry=" in boot and "shim.connectParty" in boot      # a failed import is tried again
    assert "document" not in SOURCES["board.mjs"] and "window" not in SOURCES["board.mjs"] and "fetch" not in SOURCES["board.mjs"]


def test_the_token_is_only_ever_sent_in_a_body():
    app = SOURCES["app.mjs"]
    for call in re.findall(r"post\('api/[a-z]+', (\{.*?\})\)", app):
        assert "token" in call or "ticket" in call, call
    assert "S.token" not in " ".join(re.findall(r"fetchFn\([^)]*\)", app))
    assert "?token" not in app and "token=" not in app and "Authorization" not in app


# ---- the styles --------------------------------------------------------------------------------

def test_the_styles_keep_to_what_the_ux_rules_ask_for():
    css = SOURCES["checkers.css"]
    assert "min-height: 44px" in css and "min-width: 44px" in css and "max(44px" in css      # targets, even on the board
    assert "prefers-reduced-motion" in css and "prefers-contrast" in css and "forced-colors" in css
    assert ":focus-visible" in css and "[hidden]" in css
    assert "color-scheme" in css and "env(safe-area-inset" in css
    for word in ("gradient", "backdrop-filter", "blur(", "@import", "url(", "!important;\n  animation", "font-size: 1px"):
        assert word not in css.replace("animation: none !important;", ""), word
    assert re.search(r"font-family:\s*Geist", css)
    assert not re.search(r"font-size:\s*\d+(\.\d+)?px", css)                    # text follows the phone's text size
    assert "overflow-x" not in css                                                # nothing is hidden to avoid a scroll bar
    # No colour alone: the things the board marks have shapes and outlines of their own.
    for mark in ('data-last="from"', 'data-last="to"', 'data-last="taken"', "data-movable", "data-sel", 'data-target="jump"', 'data-target="hop"'):
        assert mark in css, mark


def test_the_icon_is_a_small_plain_drawing():
    root = ET.fromstring(SOURCES["icon.svg"])
    assert root.tag == "{http://www.w3.org/2000/svg}svg" and root.get("viewBox")
    tags = {element.tag.split("}")[1] for element in root.iter()}
    assert tags <= {"svg", "rect", "circle", "path", "g", "clipPath", "defs", "title"}, tags
    assert len(SOURCES["icon.svg"].encode()) < 2048
    assert "href" not in SOURCES["icon.svg"] and "style" not in SOURCES["icon.svg"]


# ---- what the Party reads: onboarding.json ----------------------------------------------------

ONBOARDING = json.loads(text("onboarding.json"))


def test_the_onboarding_has_the_shape_the_party_reads():
    assert set(ONBOARDING) == {"schema", "game", "title", "premise", "ack", "facts", "rules"}
    assert (ONBOARDING["schema"], ONBOARDING["game"], ONBOARDING["title"]) == ("avrana.onboarding/v0", "checkers", "Checkers")
    assert ONBOARDING["ack"] == {"key": "checkers-briefed", "version": "1"}
    assert 0 < len(ONBOARDING["premise"]) <= 140


def test_the_onboarding_numbers_are_the_rules_numbers():
    assert ONBOARDING["facts"] == {"men": rules.MEN_PER_SIDE, "drawTurns": rules.DRAW_CLOCK}


def test_the_onboarding_is_one_short_sheet_with_no_bare_numbers():
    sheet = ONBOARDING["rules"]
    assert 3 <= len(sheet) <= 6
    used = set()
    for section in sheet:
        assert section["title"] and set(section) == {"title", "points"} and 1 <= len(section["points"]) <= 5
        for line in [section["title"], *section["points"]]:
            names = re.findall(r"\{(\w+)\}", line)
            assert set(names) <= set(ONBOARDING["facts"]), line
            used |= set(names)
            assert not re.search(r"\d", re.sub(r"\{\w+\}", "", line)), line      # a number is written once, as a fact
            assert len(line) <= 120, line
    assert used == set(ONBOARDING["facts"])                                       # and every fact is used


def test_the_onboarding_says_what_the_rules_do():
    words = " ".join(p for s in ONBOARDING["rules"] for p in s["points"]).lower()
    for claim in ("compulsory", "king", "resign", "draw", "white moves first", "forward"):
        assert claim in words, claim
    assert rules.legal_moves(rules.new_game()) and rules.new_game()["turn"] == "w"          # white moves first
    assert "forward only" in words and rules._MAN_DIRS["w"] == ((-1, -1), (-1, 1))


# ---- Node: the pure logic and the page, against this server ------------------------------------

# Where Node is missing these are skipped on a developer's machine; CI (which sets CI) has Node, and
# a missing one there is an error, not a skip.
needs_node = pytest.mark.skipif(NODE is None and not os.environ.get("CI"), reason="node is not installed")


def run_node(*args, env=None, timeout=90):
    done = subprocess.run([NODE or "node", *args], cwd=str(ROOT), env=dict(os.environ, **(env or {})), capture_output=True,
                          text=True, timeout=timeout)
    return done.returncode, done.stdout + done.stderr


@needs_node
def test_the_board_logic_passes_its_node_tests():
    code, output = run_node("--test", "tests/checkers_board_test.mjs")
    assert code == 0, output


class Table:
    """The real server on loopback TCP with a session launched: ana (white) and ben (black) play,
    cal watches. `setup` is what tests/checkers_page_test.mjs is given."""

    def __init__(self):
        self.key = protocol.new_key()
        self.app = server.App(protocol.GameSide(self.key, GAME), lambda message: (200, "accepted"), party_origin=PARTY_ORIGIN)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.httpd = party.make_server(self.sock, self.app, families=(socket.AF_INET,))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        roster = [{"participant": ANA, "name": "Ana", "role": "player"}, {"participant": BEN, "name": "Ben", "role": "player"},
                  {"participant": CAL, "name": "Cal", "role": "spectator"}]
        self.launch(SID, roster)

    def launch(self, sid, roster):
        message = protocol.launch_message(self.key, GAME, sid, roster)
        reply = self.app.handle("POST", party.LAUNCH, {}, json.dumps({"message": message}).encode())
        assert reply.status == 200, reply.body

    def ticket(self, pid, role, sid):
        return protocol.mint_ticket(self.key, GAME, sid, pid, role)

    def setup(self):
        people = {"ana": (ANA, "player"), "ben": (BEN, "player"), "cal": (CAL, "spectator")}
        swapped = [{"participant": BEN, "name": "Ben", "role": "player"}, {"participant": ANA, "name": "Ana", "role": "player"},
                   {"participant": CAL, "name": "Cal", "role": "spectator"}]
        return {
            "tickets": {name: {"one": [self.ticket(pid, role, SID)],
                               "again": [self.ticket(pid, role, SID) for _ in range(2)],
                               "next": [self.ticket(pid, role, SID2)]}
                        for name, (pid, role) in people.items()},
            "launch2": protocol.launch_message(self.key, GAME, SID2, swapped),
            "end": protocol.end_message(self.key, GAME, SID2),
        }

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


SCENARIOS = ("play", "reload", "spectator", "resign", "host", "rules", "replaced", "stale", "link", "noparty")


@needs_node
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_the_page_behaves_on_a_phone(scenario):
    table = Table()
    try:
        code, output = run_node("tests/checkers_page_test.mjs", scenario, env={
            "CHECKERS_ORIGIN": f"http://127.0.0.1:{table.port}", "CHECKERS_SETUP": json.dumps(table.setup())})
    finally:
        table.close()
    assert code == 0, output
    assert f"ok {scenario}" in output


@needs_node
def test_every_scenario_the_wrapper_runs_exists_and_none_is_left_out():
    source = (ROOT / "tests" / "checkers_page_test.mjs").read_text(encoding="utf-8")
    defined = re.findall(r"^  async (\w+)\(\) \{$", source, re.M)
    assert sorted(defined) == sorted(SCENARIOS)
