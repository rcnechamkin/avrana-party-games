"""Immutable card rules. No transport, randomness, clock or presentation state."""
COLORS = ('blue', 'green', 'pink', 'yellow')
DECK = tuple(f'{s}:{r}' for s in COLORS for r in range(1, 10)) + tuple(
    f'submarine:{r}' for r in range(1, 5))


def suit(card):
    return card.split(':')[0]


def rank(card):
    return int(card.split(':')[1])


def legal_cards(hand, plays):
    if not plays:
        return list(hand)
    followed = [c for c in hand if suit(c) == suit(plays[0]['card'])]
    return followed or list(hand)


def winner(plays):
    led = suit(plays[0]['card'])
    eligible = [p for p in plays if suit(p['card']) == 'submarine']
    if not eligible:
        eligible = [p for p in plays if suit(p['card']) == led]
    return max(eligible, key=lambda p: rank(p['card']))['seat']


def assertions(hand, card):
    if card not in hand or suit(card) == 'submarine':
        return []
    same = [rank(c) for c in hand if suit(c) == suit(card)]
    return [name for name, ok in [('highest', rank(card) == max(same)),
                                ('only', len(same) == 1),
                                ('lowest', rank(card) == min(same))] if ok]


def matches(card, selector):
    return (('card' not in selector or card == selector['card'])
            and ('suits' not in selector or suit(card) in selector['suits'])
            and ('ranks' not in selector or rank(card) in selector['ranks']))
