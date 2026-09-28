"""Avrana player avatars (core/looks.py): a chosen gaze-NN travels as a picture, with the emoji at
the same position for text-only views; legacy emoji and junk behave exactly as before."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import looks
from core.chat import ChatHub, _uid
from core.session import AVATARS, GameSession

WEB = Path(__file__).parent.parent / "web"


def test_every_avatar_is_bundled_locally():
    assert len(looks.GAZE) == 32
    for gid in looks.GAZE:
        svg = (WEB / "avatars" / (gid + ".svg")).read_text(encoding="utf-8")
        assert svg.startswith("<svg") and "<script" not in svg
    assert looks.picture("gaze-17") == "/shared/avatars/gaze-17.svg"
    for junk in ("gaze-33", "gaze-1", "../x", "", None, 17, "🦊"):
        assert looks.picture(junk) is None


def test_join_with_a_gaze_avatar_sends_a_picture_and_a_text_fallback():
    s = GameSession()
    p, _ = s.join("tok-a-000000000001", "Robin", "gaze-18")
    assert p.look == "gaze-18"
    assert p.avatar == AVATARS[17 % len(AVATARS)] == "🐸"    # position 18 wraps the 16 emoji
    assert p.picture(None) == "/shared/avatars/gaze-18.svg"
    assert p.picture("/avatars/abc.webp?v=1") == "/avatars/abc.webp?v=1"   # a photo still wins
    # a later profile change to a legacy emoji clears the picture choice
    s.set_profile("tok-a-000000000001", avatar="🐙")
    assert (p.avatar, p.look, p.picture(None)) == ("🐙", None, None)
    s.set_profile("tok-a-000000000001", avatar="gaze-02")
    assert (p.avatar, p.look) == ("🐸", "gaze-02")


def test_legacy_and_junk_avatars_behave_as_before():
    s = GameSession()
    p, _ = s.join("tok-b-000000000001", "Casey", "🐼")
    assert (p.avatar, p.look) == ("🐼", None)
    q, _ = s.join("tok-c-000000000001", "Dana", "<img src=x>")
    assert q.avatar in AVATARS and q.look is None
    s.set_profile("tok-c-000000000001", avatar="gaze-99")
    assert q.look is None
    assert "look" not in p.public()                      # the wire format is unchanged


def test_chat_carries_a_gaze_avatar_as_its_picture():
    hub = ChatHub()
    tok = "tok-chat-0000000001"
    out = hub._build(tok, _uid(tok), {"name": "Ava", "avatar": "gaze-05"}, {"text": "hi"})
    assert out["pfp"] == "/shared/avatars/gaze-05.svg"
    assert out["avatar"] == AVATARS[4]
    legacy = hub._build(tok, _uid(tok), {"name": "Ava", "avatar": "🦊"}, {"text": "hi"})
    assert legacy["avatar"] == "🦊" and legacy["pfp"] is None
