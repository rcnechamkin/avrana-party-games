"""Avrana player avatars ("gaze-01" .. "gaze-32"): the DiceBear Gaze set the Avrana Party profile
offers (CC0; generated in avrana-party by tools/build-avatars.mjs, vendored here in web/avatars/,
served at /shared/avatars/).

A game never has to know about them: a player who chose one gets
  * ``pfp``    = the bundled SVG, which every lobby, card and chat already draws as a picture
                 (an uploaded photo still wins), and
  * ``avatar`` = the former emoji at the same position, for the places that print the avatar as
                 text or draw it on a canvas.
Nothing else in the protocol changes.
"""

COUNT = 32
GAZE = tuple("gaze-%02d" % i for i in range(1, COUNT + 1))
_GAZE = frozenset(GAZE)


def is_gaze(value) -> bool:
    return isinstance(value, str) and value in _GAZE


def picture(value):
    """The bundled picture URL for a Gaze id, else None."""
    return "/shared/avatars/%s.svg" % value if is_gaze(value) else None


def text_fallback(value, emoji):
    """The emoji a text-only view shows for a Gaze id (the one at the same position)."""
    return emoji[(GAZE.index(value)) % len(emoji)]
