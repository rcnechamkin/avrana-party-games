"""The platform chrome's palette is the Avrana shell's (AVR-291), and stays pinned to it.

web/shared.css (the pre-game layer for every title's #scr-join and #scr-lobby) and
web/avrana-integration.css (the Back to Party bar, the ended status, the host's End and the Round
over panel that hubnet.js draws) carry a copy of the `avrana` theme in avrana-party
web/src/party.css, under the same --color-* names, until the two repositories share one source.
tests/shell_tokens_snapshot.json holds that theme's values at the Party commit it names. Here:

  * every token either file declares, in its normal and more-contrast forms, equals the snapshot,
    so a Games edit that drifts from the shell fails;
  * the snapshot equals Party's own web/src/party.css when $AVRANA_PARTY_REPO names a current Party
    checkout (opt in: a sibling ../avrana-party is often an old branch, so it is not assumed), so
    a Party change shows;
  * the chrome rules carry no colour literal, only tokens (a literal is how the old palette crept
    back in), and every token they use is declared in their own file;
  * the text, edge and focus pairs the chrome draws stay at WCAG AA (4.5:1 text, 3:1 edges and
    focus rings), in both the normal and the more-contrast forms.
Nothing here styles a game: a title's own colours are its own (docs/UI-DESIGN-SYSTEM.md in Party).
"""
import json
import math
import os
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = json.loads((ROOT / 'tests/shell_tokens_snapshot.json').read_text(encoding='utf-8'))
PARTY_REPO = os.environ.get('AVRANA_PARTY_REPO')
FILES = ('web/shared.css', 'web/avrana-integration.css')
LAYER_MARKER = '/* ---- Avrana pre-game shell'          # shared.css: everything from here is the layer


def strip_comments(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def read(path):
    return strip_comments((ROOT / path).read_text(encoding='utf-8'))


def norm(value):
    return re.sub(r'\s*/\s*', ' / ', re.sub(r'\s+', ' ', value.strip().lower()))


def declarations(body):
    return {name: norm(value) for name, value in re.findall(r'(--color-[a-z0-9-]+)\s*:\s*([^;]+);', body)}


def tokens_of(path):
    """(base, more, switch): the --color-* declared by the file's :root blocks, by its
    @media (prefers-contrast: more) :root block, and by its .lg-high-contrast rule."""
    css = read(path)
    base = {}
    for body in re.findall(r'(?m)^:root\s*\{([^}]*)\}', css):
        base.update(declarations(body))
    more = {}
    for body in re.findall(r'@media\s*\(prefers-contrast:\s*more\)\s*\{\s*:root\s*\{([^}]*)\}\s*\}', css):
        more.update(declarations(body))
    switch = {}
    for body in re.findall(r'(?m)^\.lg-high-contrast\s*\{([^}]*)\}', css):
        switch.update(declarations(body))
    return base, more, switch


EXPECTED = {name: norm(value) for name, value in SNAPSHOT['tokens'].items()}
EXPECTED_MORE = {name: norm(value) for name, value in SNAPSHOT['more_contrast'].items()}


@pytest.mark.parametrize('path', FILES)
def test_the_files_declare_the_shell_tokens_and_only_those(path):
    base, more, switch = tokens_of(path)
    assert base, f'{path} declares no --color-* tokens'
    for name, value in base.items():
        assert name in EXPECTED, f'{path}: {name} is not a shell token in tests/shell_tokens_snapshot.json'
        assert value == EXPECTED[name], f'{path}: {name} is {value}, the shell says {EXPECTED[name]}'
    for label, group in (('prefers-contrast: more', more), ('.lg-high-contrast', switch)):
        assert group, f'{path} has no {label} values'
        for name, value in group.items():
            assert name in base, f'{path}: {name} has a {label} value but no normal one'
            assert value == EXPECTED_MORE.get(name), f'{path}: {name} under {label} is {value}, the shell says {EXPECTED_MORE.get(name)}'
    assert more == switch, f'{path}: prefers-contrast: more and .lg-high-contrast must carry the same values'


def test_the_two_files_agree_on_every_token_they_share():
    shared, integration = tokens_of(FILES[0])[0], tokens_of(FILES[1])[0]
    for name in shared.keys() & integration.keys():
        assert shared[name] == integration[name], name


def test_the_snapshot_still_matches_party():
    if not PARTY_REPO:
        pytest.skip('set AVRANA_PARTY_REPO to a current avrana-party checkout: the snapshot is NOT checked against Party')
    source = Path(PARTY_REPO) / 'web/src/party.css'
    assert source.exists(), f'AVRANA_PARTY_REPO={PARTY_REPO} has no web/src/party.css'
    css = strip_comments(source.read_text(encoding='utf-8'))
    theme = declarations(css.split('@layer base', 1)[0])            # the daisyUI theme and @theme tokens
    contrast = re.search(r'@media\s*\(prefers-contrast:\s*more\)\s*\{\s*:root\s*\{([^}]*)\}', css)
    assert contrast, 'party.css has no prefers-contrast: more block'
    party_more = declarations(contrast.group(1))
    hint = f' (checkout {PARTY_REPO}; if it is an old branch, update it)'
    for name, value in EXPECTED.items():
        assert theme.get(name) == value, f'{name}: Games copies {value}, Party has {theme.get(name)}{hint}'
    for name, value in EXPECTED_MORE.items():
        assert party_more.get(name) == value, (
            f'{name} (more contrast): Games copies {value}, Party has {party_more.get(name)}{hint}')


LITERAL = re.compile(r'#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(|(?<![\w-])(?:white|black)(?![\w-])')


def chrome_rules(path):
    """The chrome's own rules: all of avrana-integration.css, and shared.css's pre-game layer,
    each without the token blocks."""
    raw = (ROOT / path).read_text(encoding='utf-8')
    if path == FILES[0]:
        raw = raw[raw.index(LAYER_MARKER):]
    css = strip_comments(raw)
    css = re.sub(r'(?m)^:root\s*\{[^}]*\}', '', css)
    css = re.sub(r'@media\s*\(prefers-contrast:\s*more\)\s*\{\s*:root\s*\{[^}]*\}\s*\}', '', css)
    css = re.sub(r'(?m)^\.lg-high-contrast\s*\{[^}]*\}', '', css)
    return css


@pytest.mark.parametrize('path', FILES)
def test_the_chrome_rules_hold_no_colour_literal_only_tokens(path):
    found = sorted(set(m.group(0) for m in LITERAL.finditer(chrome_rules(path))))
    assert not found, f'{path}: colour literal(s) {found} in a rule: use a --color-* token'


@pytest.mark.parametrize('path', FILES)
def test_every_token_the_file_uses_it_declares(path):
    used = set(re.findall(r'var\((--color-[a-z0-9-]+)', read(path)))
    declared = set(tokens_of(path)[0])
    assert used <= declared, f'{path} uses {sorted(used - declared)} without declaring it'
    assert declared <= used, f'{path} declares {sorted(declared - used)} but nothing uses it'


# ---- contrast: WCAG 2.x, computed from the values the files declare ---------------------------------
def channel(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def colour(value):
    """'#rrggbb', 'rgb(r g b / a)' or 'oklch(L% C h)' -> (r, g, b, alpha), channels in 0..255."""
    if value.startswith('#'):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)) + (1.0,)
    match = re.fullmatch(r'rgb\((\d+) (\d+) (\d+)(?: / ([\d.]+))?\)', value)
    if match:
        return (*(float(match.group(i)) for i in (1, 2, 3)), float(match.group(4) or 1))
    match = re.fullmatch(r'oklch\(([\d.]+)% ([\d.]+) ([\d.]+)\)', value)
    assert match, f'cannot read {value}'
    lightness, chroma, hue = float(match.group(1)) / 100, float(match.group(2)), math.radians(float(match.group(3)))
    a, b = chroma * math.cos(hue), chroma * math.sin(hue)
    l, m, s = ((lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3,
               (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3,
               (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3)
    linear = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
              -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
              -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    return (*(255 * (12.92 * x if x <= 0.0031308 else 1.055 * max(x, 0) ** (1 / 2.4) - 0.055) for x in linear), 1.0)


def over(top, under):
    """A translucent colour laid over an opaque one."""
    return tuple(top[i] * top[3] + under[i] * (1 - top[3]) for i in range(3)) + (1.0,)


def luminance(rgb):
    r, g, b = (channel(c / 255) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg, bg):
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


GROUNDS = ('--color-base-100', '--color-base-200', '--color-base-300')
CHOSEN = ('--color-select', '--color-base-200')      # the chosen segment: the tint over its tray
# (foreground, background, floor, what it is). A background may be (tint, what it lies on).
PAIRS = (
    [('--color-base-content', g, 4.5, 'body text') for g in GROUNDS]
    + [('--color-muted', g, 4.5, 'secondary text') for g in GROUNDS]
    + [('--color-faint', g, 4.5, 'quiet labels and placeholders') for g in GROUNDS]
    + [('--color-accent', g, 4.5, 'accent text and icons') for g in GROUNDS]
    + [('--color-success', g, 4.5, 'READY text') for g in GROUNDS[:2]]
    + [('--color-error', g, 4.5, 'error text') for g in GROUNDS[:2]]
    + [('--color-primary-content', '--color-primary', 4.5, 'ink button text')]
    + [('--color-error-content', '--color-error', 4.5, 'connection banner text')]
    + [('--color-base-content', CHOSEN, 4.5, 'chosen segment text')]
    + [('--color-control', g, 3.0, 'control edge') for g in GROUNDS[:2]]
    + [('--color-accent', g, 3.0, 'focus ring') for g in GROUNDS[:2]]
    + [('--color-success', GROUNDS[0], 3.0, 'READY outline')]
    + [('--color-error', GROUNDS[0], 3.0, 'End control edge')]
    + [('--color-primary', GROUNDS[0], 3.0, 'ink button against the ground')]
    + [('--color-base-content', CHOSEN[1], 3.0, 'chosen segment edge against its tray')]
)


def resolve(values, spec):
    if isinstance(spec, tuple):
        return over(colour(values[spec[0]]), colour(values[spec[1]]))
    return colour(values[spec])


def needs(spec):
    return spec if isinstance(spec, tuple) else (spec,)


@pytest.mark.parametrize('path', FILES)
@pytest.mark.parametrize('more_contrast', (False, True), ids=('normal', 'more-contrast'))
def test_the_chrome_pairs_stay_at_wcag_aa(path, more_contrast):
    base, more, _ = tokens_of(path)
    values = {**base, **(more if more_contrast else {})}
    checked = 0
    for fg, bg, floor, what in PAIRS:
        if all(name in values for name in needs(fg) + needs(bg)):
            got = ratio(resolve(values, fg), resolve(values, bg))
            assert got >= floor, f'{path}: {what}, {fg} on {bg} is {got:.2f}:1, needs {floor}:1'
            checked += 1
    assert checked >= 10, f'{path}: only {checked} pairs could be checked'
