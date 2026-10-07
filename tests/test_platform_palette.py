"""The platform chrome's palette is the Avrana shell's (AVR-291), and stays pinned to it.

web/shared.css (the pre-game layer for every title's #scr-join and #scr-lobby) and
web/avrana-integration.css (the Back to Party bar, the ended status, the host's End and the Round
over panel that hubnet.js draws) carry a copy of the `avrana` theme in avrana-party
web/src/party.css, under the same --color-* names, until the two repositories share one source.
tests/shell_tokens_snapshot.json holds that theme's values at the Party commit it names. Here:

  * every token either file declares, in its normal and more-contrast forms, equals the snapshot,
    so a Games edit that drifts from the shell fails; a token the shell writes in oklch carries its
    hex in :root and the shell's own value behind an @supports test;
  * the snapshot equals Party's own web/src/party.css when $AVRANA_PARTY_REPO names a current Party
    checkout (opt in: a sibling ../avrana-party is often an old branch, so it is not assumed), so
    a Party change shows;
  * the chrome rules carry no colour literal, only tokens (a literal is how the old palette crept
    back in), and every token they use is declared in their own file;
  * every color-mix() and oklch() in the two files sits behind an @supports test with a plain value
    outside it, so a browser that cannot read them keeps the colours it had (a declaration that
    holds a var() is accepted whole at parse time, so a plain line written before it is no
    fallback); the check is itself checked against that pattern;
  * the chrome's main rules use the tokens they should (control edges, focus rings, the chosen
    choice, the ink fill, READY, the End control and its disabled look, the Round over panel):
    token values alone do not say which token a rule reads;
  * the text, edge and focus pairs the chrome draws stay at WCAG AA (4.5:1 text, 3:1 edges and
    focus rings), in the normal and the more-contrast forms, with and without oklch.
Nothing here styles a game: a title's own colours are its own (docs/UI-DESIGN-SYSTEM.md in Party).
"""
import json
import math
import os
from pathlib import Path
import re
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = json.loads((ROOT / 'tests/shell_tokens_snapshot.json').read_text(encoding='utf-8'))
PARTY_REPO = os.environ.get('AVRANA_PARTY_REPO')
FILES = ('web/shared.css', 'web/avrana-integration.css')
SHARED, INTEGRATION = FILES
LAYER_MARKER = '/* ---- Avrana pre-game shell'          # shared.css: everything from here is the layer


def strip_comments(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def read(path):
    return strip_comments((ROOT / path).read_text(encoding='utf-8'))


def norm(value):
    return re.sub(r'\s*/\s*', ' / ', re.sub(r'\s+', ' ', value.strip().lower()))


def declarations(body):
    return {name: norm(value) for name, value in re.findall(r'(--color-[a-z0-9-]+)\s*:\s*([^;]+);', body)}


class Tokens(NamedTuple):
    base: dict       # the --color-* of the file's :root blocks
    more: dict       # ... of its @media (prefers-contrast: more) :root block
    switch: dict     # ... of its .lg-high-contrast rule
    gated: dict      # name -> (the @supports test, value), from `@supports (...) { :root { ... } }`


def tokens_of(path):
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
    gated = {}
    for test, body in re.findall(r'@supports\s*([^{]*?)\s*\{\s*:root\s*\{([^}]*)\}\s*\}', css):
        for name, value in declarations(body).items():
            gated[name] = (re.sub(r'\s+', '', test), value)
    return Tokens(base, more, switch, gated)


def modern(tokens):
    """The values in a browser that reads every colour function: the gated ones over the plain."""
    return {**tokens.base, **{name: value for name, (_, value) in tokens.gated.items()}}


EXPECTED = {name: norm(value) for name, value in SNAPSHOT['tokens'].items()}
EXPECTED_MORE = {name: norm(value) for name, value in SNAPSHOT['more_contrast'].items()}
FALLBACKS = {name: norm(value) for name, value in SNAPSHOT['fallbacks'].items()}

# Colour functions that a browser older than the shell's own build target (Chrome 111, Safari 16.4,
# Firefox 113) cannot read, and the @supports test that is true exactly where each one is read.
MODERN_FUNCTION = re.compile(r'(?<![\w-])(color-mix|oklch|oklab|lab|lch|hwb|light-dark|color)\(')
GATES = {
    'color-mix': '(color: color-mix(in srgb, red 50%, blue))',
    'oklch': '(color: oklch(0% 0 0))',
}


def squeeze(text):
    return re.sub(r'\s+', '', text)


@pytest.mark.parametrize('path', FILES)
def test_the_files_declare_the_shell_tokens_and_only_those(path):
    base, more, switch, gated = tokens_of(path)
    assert base, f'{path} declares no --color-* tokens'
    for name, value in base.items():
        assert name in EXPECTED, f'{path}: {name} is not a shell token in tests/shell_tokens_snapshot.json'
        want = FALLBACKS.get(name, EXPECTED[name])
        note = f' (the plain value for a browser without {MODERN_FUNCTION.search(EXPECTED[name]).group(1)}())' if name in FALLBACKS else ''
        assert value == want, f'{path}: {name} is {value}, the shell says {want}{note}'
    for label, group in (('prefers-contrast: more', more), ('.lg-high-contrast', switch)):
        assert group, f'{path} has no {label} values'
        for name, value in group.items():
            assert name in base, f'{path}: {name} has a {label} value but no normal one'
            assert value == EXPECTED_MORE.get(name), f'{path}: {name} under {label} is {value}, the shell says {EXPECTED_MORE.get(name)}'
    assert more == switch, f'{path}: prefers-contrast: more and .lg-high-contrast must carry the same values'


@pytest.mark.parametrize('path', FILES)
def test_a_token_the_shell_writes_in_oklch_has_a_plain_default_and_a_gate(path):
    base, _, _, gated = tokens_of(path)
    for name, value in EXPECTED.items():
        function = MODERN_FUNCTION.search(value)
        if not function or name not in base:
            continue
        assert name in gated, (f'{path}: the shell writes {name} as {value}; a custom property is never rejected at '
                               f'parse time, so declare it again inside `@supports {GATES[function.group(1)]}`')
        test, enhanced = gated[name]
        assert test == squeeze(GATES[function.group(1)]), f'{path}: {name} is gated by {test}, which does not test {function.group(1)}()'
        assert enhanced == value, f'{path}: {name} is {enhanced} behind the gate, the shell says {value}'
    for name in gated:
        assert name in FALLBACKS, f'{path}: {name} is declared behind a gate but the snapshot has no fallback for it'


def test_each_fallback_is_the_shell_value_to_the_nearest_channel():
    assert FALLBACKS, 'the snapshot lists no fallbacks'
    for name, plain in FALLBACKS.items():
        assert MODERN_FUNCTION.search(EXPECTED.get(name, '')), f'{name} has a fallback but the shell does not write it in a colour function'
        assert plain == to_hex(colour(EXPECTED[name])), f'{name}: the fallback {plain} is not {EXPECTED[name]} ({to_hex(colour(EXPECTED[name]))})'


def test_the_two_files_agree_on_every_token_they_share():
    shared, integration = tokens_of(SHARED), tokens_of(INTEGRATION)
    for name in shared.base.keys() & integration.base.keys():
        assert shared.base[name] == integration.base[name], name
    modern_shared, modern_integration = modern(shared), modern(integration)
    for name in modern_shared.keys() & modern_integration.keys():
        assert modern_shared[name] == modern_integration[name], name


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
    if path == SHARED:
        raw = raw[raw.index(LAYER_MARKER):]
    css = strip_comments(raw)
    css = re.sub(r'(?m)^:root\s*\{[^}]*\}', '', css)
    css = re.sub(r'@media\s*\(prefers-contrast:\s*more\)\s*\{\s*:root\s*\{[^}]*\}\s*\}', '', css)
    css = re.sub(r'@supports[^{]*\{\s*:root\s*\{[^}]*\}\s*\}', '', css)
    css = re.sub(r'(?m)^\.lg-high-contrast\s*\{[^}]*\}', '', css)
    return css


@pytest.mark.parametrize('path', FILES)
def test_the_chrome_rules_hold_no_colour_literal_only_tokens(path):
    css = re.sub(r'@supports[^{]*\{', '@supports {', chrome_rules(path))      # a gate's own test is no colour
    found = sorted(set(m.group(0) for m in LITERAL.finditer(css)))
    assert not found, f'{path}: colour literal(s) {found} in a rule: use a --color-* token'


@pytest.mark.parametrize('path', FILES)
def test_every_token_the_file_uses_it_declares(path):
    used = set(re.findall(r'var\((--color-[a-z0-9-]+)', read(path)))
    declared = set(tokens_of(path).base)
    assert used <= declared, f'{path} uses {sorted(used - declared)} without declaring it'
    assert declared <= used, f'{path} declares {sorted(declared - used)} but nothing uses it'


# ---- the rules, read as rules ------------------------------------------------------------------------
class Rule(NamedTuple):
    selector: str        # as written, whitespace collapsed
    context: tuple       # the at-rules it sits in, outermost first: ('@supports (color: oklch(0% 0 0))',)
    declarations: tuple  # ((property, value), ...) in source order, whitespace collapsed


def parse_rules(css):
    """The style rules of comment-free CSS in source order, each with the at-rules around it."""
    rules, stack, text, depth, quote = [], [], '', 0, None

    def end_declaration():
        name, colon, value = text.partition(':')
        if stack and colon and name.strip():
            stack[-1][1].append((name.strip().lower(), ' '.join(value.split())))

    for ch in css:
        if quote:
            text += ch
            if ch == quote:
                quote = None
            continue
        if ch in '"\'':
            quote = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and ch == '{':
            stack.append([' '.join(text.split()), []])
            text = ''
            continue
        elif depth == 0 and ch in ';}':
            end_declaration()
            text = ''
            if ch == '}':
                prelude, found = stack.pop()
                if not prelude.startswith('@'):
                    rules.append(Rule(prelude, tuple(p for p, _ in stack if p.startswith('@')), tuple(found)))
            continue
        text += ch
    assert not stack and depth == 0 and quote is None, 'unbalanced CSS'
    return rules


SHORTHANDS = {'border-color': ('border',), 'background-color': ('background',), 'outline-color': ('outline',)}


def plain_default(rules, index, prop):
    """Before rules[index], outside every @supports and in the same media: a rule for the same
    selector that gives `prop` (or the shorthand that sets it) a value with no modern colour function?"""
    rule = rules[index]
    media = tuple(c for c in rule.context if not c.startswith('@supports'))
    for other in rules[:index]:
        if other.selector != rule.selector or other.context != media:
            continue
        if any(p in (prop, *SHORTHANDS.get(prop, ())) and not MODERN_FUNCTION.search(v) for p, v in other.declarations):
            return True
    return False


def gating_problems(css):
    """What is wrong with the modern colour functions in `css`: an empty list is fine.

    Each one is behind the @supports test that names it, with a plain value for the same property
    and selector outside the gate; or, where nothing in the declaration is a var() and it is not a
    custom property (so a browser that cannot read it drops it at parse time), it comes after a
    plain declaration of the same property in the same rule."""
    rules = parse_rules(css)
    problems = []
    for index, rule in enumerate(rules):
        for position, (prop, value) in enumerate(rule.declarations):
            for function in sorted(set(MODERN_FUNCTION.findall(value))):
                what = f'`{prop}: {value}` in `{rule.selector}`'
                gate = squeeze(f'@supports {GATES[function]}') if function in GATES else None
                if gate and gate in [squeeze(c) for c in rule.context]:
                    if not plain_default(rules, index, prop):
                        problems.append(f'{what}: gated, but no plain {prop} for this selector outside the gate')
                elif any(c.startswith('@supports') for c in rule.context):
                    problems.append(f'{what}: inside an @supports that does not test {function}()')
                elif prop.startswith('--') or 'var(' in value:
                    problems.append(f'{what}: not gated; a custom property or a declaration with var() is accepted at '
                                    f'parse time, so a plain line before it is never the fallback')
                elif not any(p == prop and not MODERN_FUNCTION.search(v) for p, v in rule.declarations[:position]):
                    problems.append(f'{what}: not gated, and no plain {prop} before it in the rule')
    return problems


@pytest.mark.parametrize('path', FILES)
def test_every_modern_colour_function_is_gated_or_has_a_plain_default(path):
    assert gating_problems(read(path)) == []


GATED = (
    ':root { --c: #70c696; }\n'
    '@supports (color: oklch(0% 0 0)) { :root { --c: oklch(76% 0.11 158); } }\n'
    '.chip { border: 1px solid rgba(0, 0, 0, .3); background: rgba(0, 0, 0, .7); }\n'
    '@supports (color: color-mix(in srgb, red 50%, blue)) {\n'
    '  .chip { border-color: color-mix(in srgb, var(--m) 28%, transparent); background: color-mix(in srgb, var(--b) 72%, transparent); }\n'
    '}\n'
)
PARSED_AT_ONCE = '.a { color: #fff; color: color-mix(in srgb, #fff 40%, transparent); }'
NOT_FALLBACKS = {
    'a plain line, then a color-mix that holds var() (the inert fallback)':
        '.a { color: #fff; color: color-mix(in srgb, var(--x) 40%, transparent); }',
    'an ungated oklch custom property': ':root { --c: oklch(76% 0.11 158); }',
    'a gated token with no plain value': '@supports (color: oklch(0% 0 0)) { :root { --c: oklch(76% 0.11 158); } }',
    'oklch behind the color-mix test':
        ':root { --c: #70c696; }\n@supports (color: color-mix(in srgb, red 50%, blue)) { :root { --c: oklch(76% 0.11 158); } }',
    'a color-mix behind `@supports not`':
        '.a { color: #fff; }\n@supports not (color: color-mix(in srgb, red 50%, blue)) { .a { color: color-mix(in srgb, #fff 40%, transparent); } }',
    'a color-mix with nothing before it': '.a { color: color-mix(in srgb, #fff 40%, transparent); }',
    'a gated rule whose plain value is for another selector':
        '.b { color: #fff; }\n@supports (color: color-mix(in srgb, red 50%, blue)) { .a { color: color-mix(in srgb, #fff 40%, transparent); } }',
}


def test_the_gating_check_accepts_the_pattern_it_asks_for():
    assert gating_problems(GATED) == []
    assert gating_problems(PARSED_AT_ONCE) == []


@pytest.mark.parametrize('css', NOT_FALLBACKS.values(), ids=list(NOT_FALLBACKS))
def test_the_gating_check_refuses_what_is_not_a_fallback(css):
    assert gating_problems(css), 'the check let it through'


def split_selector(selector):
    """The parts of a selector list, split on the commas outside parentheses and brackets."""
    parts, depth, part = [], 0, ''
    for ch in selector:
        depth += (ch in '([') - (ch in ')]')
        if ch == ',' and depth == 0:
            parts.append(part)
            part = ''
        else:
            part += ch
    return parts + [part]


def norm_selector(selector):
    return ' '.join(re.sub(r'\s*,\s*', ', ', selector).split())


def given(path, selector):
    """What the file gives a rule written with exactly this selector, alone or in a list: its rules
    outside every @media and @supports, later over earlier."""
    wanted, result = norm_selector(selector), {}
    for rule in parse_rules(read(path)):
        if not rule.context and wanted in (norm_selector(part) for part in split_selector(rule.selector)):
            result.update(rule.declarations)
    return result


SCREENS = ':root :is(#scr-join, #scr-lobby)'
ON_SCREEN = 'body:has(:is(#scr-join, #scr-lobby):not([hidden]))'
EDGE = '1px solid var(--color-control)'                 # the edge of anything you can press or type in
RING = '3px solid var(--color-accent)'                  # the focus ring, everywhere
PINS = (
    # (what, file, selector, {property: exact value, or a pattern the whole value must match})
    ('the pre-game screens re-point the old names to the shell', SHARED, SCREENS, {
        'background': 'var(--color-base-100)', '--bg': 'var(--color-base-100)', '--surface': 'var(--color-base-200)',
        '--raised': 'var(--color-base-300)', '--line': 'var(--color-line-strong)', '--text': 'var(--color-base-content)',
        '--muted': 'var(--color-muted)', '--faint': 'var(--color-faint)', '--cyan': 'var(--color-accent)',
        '--violet': 'var(--color-accent)', '--green': 'var(--color-success)', '--danger': 'var(--color-error)'}),
    ('a button\'s edge is the control edge', SHARED, f'{SCREENS} .btn', {
        'border': EDGE, 'background': 'var(--raised)', 'color': 'var(--text)'}),
    ('an icon button\'s edge is the control edge', SHARED, f'{SCREENS} .icon-btn', {'border': EDGE}),
    ('a field\'s edge is the control edge', SHARED, f'{SCREENS} :is(input[type="text"], input:not([type]))', {'border': EDGE}),
    ('a segmented choice\'s edge is the control edge', SHARED, f'{SCREENS} .seg', {'border': EDGE}),
    ('a stepper button\'s edge is the control edge', SHARED, f'{SCREENS} .stepper button', {'border': EDGE}),
    ('the photo button\'s edge is the control edge', SHARED, f'{SCREENS} .pfp-btn', {'border-color': 'var(--color-control)'}),
    ('the focus ring on the pre-game screens', SHARED, f'{SCREENS} :is(input, button, a):focus-visible', {
        'outline': RING, 'outline-offset': '2px'}),
    ('the ink button', SHARED, f'{SCREENS} :is(.btn-primary, .btn-ready, .btn-go)', {
        'background': 'var(--color-primary)', 'border-color': 'transparent', 'color': 'var(--color-primary-content)'}),
    ('READY, once pressed: outlined in success', SHARED, f'{SCREENS} .btn-ready.is-ready', {
        'background': 'transparent', 'border': '2px solid var(--green)', 'color': 'var(--green)'}),
    ('a ready player\'s card has the green edge by default', SHARED, f'{SCREENS} .player-card.is-ready', {
        'border-color': 'var(--green)'}),
    ('the ready status is success', SHARED, f'{SCREENS} .pc-status.rdy', {'color': 'var(--green)'}),
    ('the chosen segment: a tint, a light edge', SHARED, f'{SCREENS} .seg button.sel', {
        'background': 'var(--color-select)', 'color': 'var(--color-base-content)',
        'box-shadow': 'inset 0 0 0 1px var(--color-base-content)'}),
    ('a notice over a pre-game screen', SHARED, f'{ON_SCREEN} .toast', {
        'background': 'var(--color-base-200)', 'border-color': 'var(--color-line-strong)', 'color': 'var(--color-base-content)'}),
    ('an error notice over a pre-game screen', SHARED, f'{ON_SCREEN} .toast.err', {
        'border-color': 'var(--color-error)', 'color': 'var(--color-error)'}),
    ('the connection line over a pre-game screen', SHARED, f'{ON_SCREEN} .conn-banner', {
        'background': 'var(--color-error)', 'color': 'var(--color-error-content)'}),
    ('the Back to Party bar', INTEGRATION, '#avrana-navigation', {
        'background': 'var(--color-base-100)', 'border-bottom': '1px solid var(--color-line-strong)',
        'color': 'var(--color-base-content)'}),
    ('the Back to Party link', INTEGRATION, '#avrana-navigation a', {'color': 'var(--color-base-content)'}),
    ('the Back to Party chevron', INTEGRATION, '#avrana-navigation a::before', {
        'border-left': '2px solid var(--color-accent)', 'border-bottom': '2px solid var(--color-accent)'}),
    ('the Back to Party hover', INTEGRATION, '#avrana-navigation a:hover', {'background': 'var(--color-base-300)'}),
    ('the Back to Party focus ring', INTEGRATION, '#avrana-navigation a:focus-visible', {
        'outline': RING, 'outline-offset': '2px'}),
    ('the ended status', INTEGRATION, '.party-ended', {
        'background': 'var(--color-base-200)', 'color': 'var(--color-base-content)'}),
    ('the host\'s End control: an error edge on the ground', INTEGRATION, '#avrana-party-end', {
        'border': '1px solid var(--color-error)', 'background': 'transparent', 'color': 'var(--color-base-content)'}),
    ('the End control says so while it is disabled', INTEGRATION, '#avrana-party-end:disabled', {
        'opacity': re.compile(r'0?\.\d+'), 'cursor': 'not-allowed'}),
    ('the End control\'s focus ring', INTEGRATION, '#avrana-party-end:focus-visible', {
        'outline': RING, 'outline-offset': '2px'}),
    ('the Round over panel', INTEGRATION, '.party-round-over', {
        'background': 'var(--color-base-100)', 'color': 'var(--color-base-content)'}),
    ('the Round over text', INTEGRATION, '.party-round-over p', {'color': 'var(--color-muted)'}),
    ('a Round over button: control edge, base-300 fill', INTEGRATION, '.party-round-over button', {
        'border': EDGE, 'background': 'var(--color-base-300)', 'color': 'var(--color-base-content)'}),
    ('the Round over ink button', INTEGRATION, '.party-round-over button.primary', {
        'background': 'var(--color-primary)', 'border-color': 'var(--color-primary)', 'color': 'var(--color-primary-content)'}),
    ('a Round over button\'s focus ring', INTEGRATION, '.party-round-over button:focus-visible', {
        'outline': RING, 'outline-offset': '2px'}),
)


@pytest.mark.parametrize('what, path, selector, expected', PINS, ids=[pin[0] for pin in PINS])
def test_the_rule_reads_the_token_it_should(what, path, selector, expected):
    found = given(path, selector)
    assert found, f'{path}: there is no rule for `{selector}`'
    for prop, want in expected.items():
        got = found.get(prop)
        assert got is not None, f'{path}: `{selector}` no longer sets {prop}'
        matches = want.fullmatch(got) if isinstance(want, re.Pattern) else got == want
        assert matches, f'{path}: `{selector}` has {prop}: {got}; the palette needs {getattr(want, "pattern", want)}'


def test_the_chosen_segment_changes_colour_and_edge_only():
    # type stays as it was: weight, size and family come from `.seg button`, not from `.sel`
    assert set(given(SHARED, f'{SCREENS} .seg button.sel')) == {'background', 'color', 'box-shadow'}


@pytest.mark.parametrize('path', FILES)
def test_every_focus_ring_in_the_chrome_is_the_shells(path):
    rings = [rule for rule in parse_rules(chrome_rules(path)) if ':focus-visible' in rule.selector]
    assert rings, f'{path} has no :focus-visible rule'
    for rule in rings:
        found = dict(rule.declarations)
        assert found.get('outline') == RING, f'{path}: `{rule.selector}` outline is {found.get("outline")}, not {RING}'
        assert found.get('outline-offset') == '2px', f'{path}: `{rule.selector}` outline-offset is {found.get("outline-offset")}'


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


def to_hex(rgba):
    return '#' + ''.join(f'{round(c):02x}' for c in rgba[:3])


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
@pytest.mark.parametrize('browser', ('without-oklch', 'with-oklch'))
@pytest.mark.parametrize('more_contrast', (False, True), ids=('normal', 'more-contrast'))
def test_the_chrome_pairs_stay_at_wcag_aa(path, browser, more_contrast):
    tokens = tokens_of(path)
    values = modern(tokens) if browser == 'with-oklch' else dict(tokens.base)
    if more_contrast:
        values.update(tokens.more)
    checked = 0
    for fg, bg, floor, what in PAIRS:
        if all(name in values for name in needs(fg) + needs(bg)):
            got = ratio(resolve(values, fg), resolve(values, bg))
            assert got >= floor, f'{path}: {what}, {fg} on {bg} is {got:.2f}:1, needs {floor}:1'
            checked += 1
    assert checked >= 10, f'{path}: only {checked} pairs could be checked'
