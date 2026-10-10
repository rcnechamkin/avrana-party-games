"""avrana_gamekit: EXPERIMENTAL plumbing for a native Avrana game (AVR-38).

NOT an SDK. NOT "SDK v0". NOT frozen: no version promise, and names, signatures and module paths
here may change or vanish without notice. It exists so that the second and third native game do
not copy the Party boundary a third and fourth time, and so an outsider can read one small
package instead of Checkers and the stand-in side by side. Freeze gates (unmet): Checkers moved
onto it, review of the four-human BLUFF evidence (AVR-27), and Spades boundary validation (ADR 0014).

Standard library only. It builds ON the Party's contract-pinned files, vendored in this
repository and imported, never copied or changed: `core/party_protocol.py` (the signed session
protocol) and `core/party_result.py` (`avrana.game-result/v1`).

Core primitives (what any game needs; each is small and independent):

    jsonio    strict, bounded JSON in; Reply out
    party     the Party boundary: control messages, tickets, per-seat tokens, `ended`, results
    runtime   an HTTP server on the inherited fd 3 Unix socket (or a loopback port, for
              development only), the key, idle stop, clean shutdown
    app       the request router that joins the two: launch / end / redeem / poll / actions

Optional helpers (convenience; a game may ignore every one of them): `helpers`.
Development only (never imported by the runtime): `devparty`, a stand-in for the Party's half.

Nothing here exposes a device or member identity (a game never has one) or any Party internals:
a game sees participant ids, display names and roles from the launch roster, and nothing else.
"""

EXPERIMENTAL = True
