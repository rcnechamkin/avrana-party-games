# Review instructions

Every pull request is reviewed by a session or subagent that did not write it
(`.claude/agents/reviewer.md`). The author never reviews their own change, and a reviewer who
fixes a finding is no longer that change's reviewer. Review informs the merge; it does not
perform it. [AGENTS.md](AGENTS.md) holds the rules this file checks against. The same policy
applies in [Party](https://github.com/rcnechamkin/avrana-party/blob/main/REVIEW.md).

## Passes

Run three passes and tag each finding with its pass.

- **Bugs**: logic errors, broken edge cases, regressions, a test that cannot fail, a test
  weakened to make a change pass, a rule that departs from the game's own rules documents.
- **Trust**: anything that moves a boundary in Party ADR
  [0006](https://github.com/rcnechamkin/avrana-party/blob/main/docs/adr/0006-party-session-protocol.md),
  [0013](https://github.com/rcnechamkin/avrana-party/blob/main/docs/adr/0013-party-and-game-browser-origins.md)
  or [0016](https://github.com/rcnechamkin/avrana-party/blob/main/docs/adr/0016-service-identities-and-local-trust-boundary.md):
  the session protocol and its key files, what a game reports to the Party, hidden information
  leaking into another seat's view, listeners and the service unit. Private or personal data
  in fixtures, logs or docs.
- **Fit**: the change does what the Linear issue's acceptance criteria and the approved plan
  say and nothing outside them; quarantined or disabled content stays that way unless the issue
  enables it; a contract change has its paired change in Party
  ([CROSS-REPO](https://github.com/rcnechamkin/avrana-party/blob/main/docs/CROSS-REPO.md)).

## What Important means here

Reserve Important for a finding that would break behavior, leak hidden or private information,
weaken a trust boundary, enable content no issue enabled, describe something as deployed or
validated that is not, or land one half of a paired cross-repo change. Naming, wording and
style are nits.

## Change class

End every review by naming the class, because it decides who merges.

- **Owner merges**: a security or trust change; a Party and Games protocol or contract change
  (`core/party_protocol.py`, `provider/avrana-contract.json`, `provider/catalog.json`, the
  session vectors); anything under `deploy/`; a product or rules decision; anything marked
  Needs Cody.
- **Routine**: everything else. Docs-only, current with `main` and green may merge without the
  owner once branch protection and required checks exist.

A paired change is one merge set: name both pull requests and say whether both are open, green
and current. Never call one half mergeable alone.

## Cap the nits

Report at most five nits; give the rest as a count.

## Do not report

Generated files (`provider/catalog.json` is checked by its exporter), anything CI already
enforces, and Windows-only test failures that Linux CI does not show.
