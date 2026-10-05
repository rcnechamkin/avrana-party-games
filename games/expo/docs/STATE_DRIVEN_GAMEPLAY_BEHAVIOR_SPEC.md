> **NON-CANONICAL DRAFT. Design and product reference only.**
> This file is one of the two draft presentation specifications named by AVR-246, committed
> as written so that the intent behind the work is on record. It does not define EXPO.
> Where it differs from the code, from the tests, or from the canonical documents in this
> directory ([RULES_SPEC](RULES_SPEC.md), [MISSION_MODEL](MISSION_MODEL.md),
> [ACTIONS](ACTIONS.md), [GAME_STATE](GAME_STATE.md)), **they win and this file is wrong**.
> Names, identifiers, payload shapes, phases, card and suit names, timings and the client
> behaviour described here are illustrations, not contracts. What was built from it, and what
> was not, is in [RECONCILIATION](RECONCILIATION.md), entry E-X1. The draft uses the title
> "The Team II"; in this repository the game is EXPO. The example players are stand-in names
> (Alice, Bob, Carol). Do not implement from this file: start from the Linear issue.

# The Team II — Avrana Adaptation
## State-Driven Gameplay Behavior Spec

**Status:** Draft  
**Purpose:** Define how authoritative game state drives legal actions, UI behavior, audiovisual feedback, and cinematic events.

---

## 1. Fundamental Rule Boundary

The engine must distinguish between:

### Hard legality
Whether the player is allowed to perform an action.

### Mission outcome
Whether a legal action causes progress, failure, or eventual impossibility.

These must never be conflated.

**Core rule:**

> Illegal actions are prevented. Legal mistakes are allowed.

A player may be fully responsible for causing the mission to fail.

The game must not protect them from a legal strategic error.

---

## 2. Authoritative Flow

The game should conceptually resolve player actions in this order:

```text
PLAYER INTENT
    ↓
LEGALITY CHECK
    ↓
if illegal → reject
if legal   → apply action
                ↓
         resolve immediate game state
                ↓
         resolve trick if complete
                ↓
         evaluate objectives
                ↓
         evaluate mission state
                ↓
         emit gameplay events
                ↓
         clients present result
```

The UI is never authoritative.

Client-side disabling exists for usability.

The server must independently validate every submitted action.

---

## 3. Core Engine Interfaces

Conceptual interfaces:

```ts
getLegalActions(state, playerId)
getLegalCards(state, playerId)
canCommunicate(state, playerId, cardId)
getCommunicationModes(state, playerId, cardId)
applyAction(state, action)
resolveTrick(state)
evaluateObjectives(state)
evaluateMission(state)
derivePresentationEvents(previousState, nextState)
```

---

## 4. Action Legality

### 4.1 Play card
A card play may be rejected for reasons such as:

- not player's turn
- card not in player's hand
- required lead suit is available in hand and selected card does not follow it
- mission constraint forbids that card from leading
- mission constraint forbids that suit/rank/action in current phase
- game is not in card-play phase

Rejection response should contain a machine-readable reason.

Example:

```json
{
  "legal": false,
  "reason": "MUST_FOLLOW_SUIT",
  "requiredSuit": "blue"
}
```

### 4.2 Mission-specific action constraints
Mission constraints alter legal actions.

Examples:

```ts
cannotLeadRank(3)
cannotLeadSuit("red")
communicationDisabled()
communicationUnavailableUntilTrick(2)
captainOnlyTaskAssignment()
```

These are **constraints**, not objectives.

They determine whether an action may occur.

---

## 5. Mission Objectives

Objectives evaluate whether the mission's required conditions are satisfied.

Examples:

```ts
playerMustWinCard("alice", "blue-8")
playerMustWinAtLeast("bob", 3)
playerMustWinFewerThan("carol", "alice")
specificCardBefore("blue-8", "red-6")
noPlayerMoreThanTricksAhead(1)
```

Objectives do **not** normally change whether a card is legal.

A legal card may:

- progress an objective
- complete an objective
- make an objective impossible
- immediately fail an objective
- leave objective state unchanged

---

## 6. Example: Legal Mission Failure

State:

- Alice must win Blue 8.
- Carol leads Blue 4.
- Alice plays Blue 8.
- Bob has Blue 9.
- Bob must follow Blue.

Bob's Blue 9 is legal.

The engine must allow it.

After Bob plays Blue 9:

1. card is accepted
2. trick resolves
3. Bob wins
4. Alice's required Blue 8 has been captured by another player
5. objective becomes failed
6. mission failure is evaluated
7. causal event is emitted

Example event:

```json
{
  "type": "OBJECTIVE_FAILED",
  "objectiveId": "alice_win_blue_8",
  "triggerPlayerId": "bob",
  "affectedPlayerId": "alice",
  "triggerAction": {
    "type": "PLAY_CARD",
    "cardId": "blue-9"
  },
  "reason": "TARGET_CARD_WON_BY_OTHER_PLAYER"
}
```

No warning should appear before Bob commits the card.

---

## 7. Strategic Oracle Prohibition

The game must not reveal hidden strategic consequences before a legal action.

Do not show:

- “This will lose the mission.”
- “Dangerous move.”
- red warning glow on a legal card because the engine predicts failure
- confirmation dialog for a legal losing move
- hints derived from hidden information

Pre-action UI may show only:

- legal vs illegal
- public rule constraints
- public mission information

Consequences are resolved after commitment.

---

## 8. Objective State Model

Each objective should exist in one of these states:

```text
PENDING
ACTIVE
COMPLETED
FAILED
IMPOSSIBLE
```

### COMPLETED
The objective's required condition has been satisfied and can no longer fail.

### FAILED
A defined failure condition occurred.

### IMPOSSIBLE
The objective can no longer possibly be satisfied given authoritative state.

The engine may end the mission immediately when an objective is provably impossible, if consistent with the game's rules.

---

## 9. Causality Model

Every mission-ending failure should attempt to identify:

```ts
FailureCause {
  objectiveId
  triggerPlayerId?
  affectedPlayerId?
  triggerAction?
  failureType
  relevantCards?
  trickNumber?
  environmentalContext?
}
```

The triggering player and affected player may be different.

This causality information is used by presentation, debriefing, and replay.

It must not alter the underlying rules result.

---

## 10. Presentation Event Model

The authoritative engine should emit semantic events rather than animation instructions.

Examples:

```text
TURN_STARTED
CARD_PLAYED
TRICK_RESOLVED
COMMUNICATION_SENT
OBJECTIVE_PROGRESS
OBJECTIVE_COMPLETED
OBJECTIVE_FAILED
MISSION_MODIFIER_ACTIVATED
MISSION_SUCCESS
MISSION_FAILURE
PLAYER_RECONNECTED
```

Example:

```json
{
  "type": "TRICK_RESOLVED",
  "trickNumber": 4,
  "winnerPlayerId": "bob",
  "cards": [
    "blue-4",
    "blue-8",
    "blue-9",
    "yellow-2"
  ]
}
```

Clients decide how to render these events.

---

## 11. Director Layer

A non-authoritative **presentation director** chooses the intensity of audiovisual treatment.

Example mapping:

```text
CARD_PLAYED
→ microinteraction

TRICK_RESOLVED
→ gameplay beat

OBJECTIVE_COMPLETED
→ gameplay beat

OBJECTIVE_FAILED but mission continues
→ strong gameplay beat

MISSION_FAILURE
→ cinematic beat

MISSION_SUCCESS
→ cinematic beat
```

The director never changes game state.

---

## 12. Cinematic Failure Interpretation

The narrative/presentation layer receives causal context.

Example:

```json
{
  "type": "MISSION_FAILURE",
  "cause": {
    "triggerPlayerId": "bob",
    "affectedPlayerId": "alice",
    "failureType": "TARGET_CARD_LOST",
    "location": "bunker_gate"
  }
}
```

A cinematic template may translate this into fiction:

```text
BUNKER_LOCKOUT
triggerPlayer = Bob
affectedPlayer = Alice
```

Possible sequence:

1. Alice reaches bunker
2. Bob's action redirects the threat
3. bunker door closes
4. Alice is trapped outside
5. radio signal drops
6. mission failure title appears

Alternative templates may punish the triggering player instead.

The fiction is variable.

The causality is not.

---

## 13. Success and Assist Interpretation

The same system may record meaningful enabling actions.

Example:

- Alice completes required card objective
- Carol's prior low play made that result possible

This may produce:

```json
{
  "type": "OBJECTIVE_COMPLETED",
  "ownerPlayerId": "alice",
  "completedByPlayerId": "alice",
  "enabledByPlayerId": "carol"
}
```

This should be conservative.

Do not fabricate “assists” unless the relationship can be derived reliably from game state.

---

## 14. Turn State

The UI should derive turn presentation from authoritative state.

Example:

```ts
TurnState {
  leaderPlayerId
  activePlayerId
  trickNumber
  leadSuit?
  cardsPlayed
}
```

UI behavior:

- active player's crew tile emphasized
- legal hand cards interactive
- illegal cards muted
- non-active players cannot commit cards
- current trick remains visible

---

## 15. Trick Resolution State

Before trick completion:

```text
status = IN_PROGRESS
```

After all required cards are played:

```text
status = RESOLVING
```

During `RESOLVING`:

- new player actions are temporarily blocked
- trick winner is calculated
- mission/task state is evaluated
- presentation events are queued

After resolution:

```text
status = COMPLETE
```

Then next trick begins unless mission has ended.

---

## 16. Communication State

Conceptual model:

```ts
CommunicationState {
  available: boolean
  usedByPlayer: Record<PlayerId, boolean>
  missionMode: "normal" | "restricted" | "disabled"
}
```

For a selected card:

```ts
CommunicationOption {
  cardId
  allowed: boolean
  modes: ("highest" | "lowest" | "only")[]
}
```

Submarine/trump cards are not communicable under the base rule set.

Mission-specific restrictions may further reduce availability.

---

## 17. Task Selection State

Task selection should have its own explicit phase.

Example:

```text
MISSION_SETUP
TASK_SELECTION
PLAYING
RESOLVING_TRICK
MISSION_COMPLETE
MISSION_FAILED
```

During task selection:

- Captain starts where required
- passing is allowed only when rules permit
- no communication occurs before the rules allow it
- all assignments are authoritative

---

## 18. Reconnect Behavior

The server owns:

- player identity
- seat
- hand
- communicated card state
- assigned tasks
- current trick state
- used communication state
- Captain status
- mission state

On reconnect, the client receives an authoritative snapshot and reconstructs the current screen.

The client must never infer hidden/private state from stale local UI.

---

## 19. Synchronization

Presentation events should carry an event sequence and, where useful, a scheduled presentation time.

Example:

```json
{
  "eventId": 1842,
  "type": "MISSION_FAILURE",
  "executeAt": 1837312.500
}
```

Clients render locally.

The appliance does not stream rendered animation.

This allows:

- synchronized haptics
- synchronized trick resolution
- synchronized mission events
- synchronized environmental transitions

---

## 20. Rendering Responsibility

### Server / appliance
Responsible for:

- authoritative game state
- legal action validation
- task/objective evaluation
- mission modifiers
- trick resolution
- causal event generation
- event timing

### Phone client
Responsible for:

- card animation
- UI transitions
- world-stage animation
- audio
- haptics
- local sprite/video playback
- visual effects

The client may predict harmless UI transitions, but authoritative outcomes come from the server.

---

## 21. Performance Fallbacks

Presentation quality may scale by device capability.

Example:

```text
High:
WebGPU distortion + particles + layered animation

Medium:
Canvas particles + CSS transforms

Low:
Static scene + CSS transitions + reduced effects
```

The same authoritative events must work at every fidelity level.

No mission may require high-end rendering to remain understandable.

---

## 22. Replay and Event History

Because every accepted action and resolved event is deterministic, the game should maintain a short event history.

Useful for:

- review last trick
- mission debrief
- debugging
- reconnect
- rules disputes
- cinematic recap

Replay must never reveal information that was not public at the moment being replayed.

---

## 23. Required Test Classes

Every rule implementation should include tests for:

### Legality
- legal play accepted
- illegal play rejected
- follow-suit enforcement
- mission-specific play constraint
- turn enforcement

### Legal strategic failure
- losing card remains playable
- action commits successfully
- objective failure occurs afterward
- causal player recorded correctly

### Communication
- valid highest
- valid lowest
- valid only
- invalid middle card
- trump/submarine rejected
- second communication rejected
- timing restriction enforced

### Objective evaluation
- progress
- completion
- immediate failure
- impossibility detection
- simultaneous objective changes

### Reconnect
- private hand restored
- current trick restored
- communication state restored
- task ownership restored

### Presentation events
- semantic events emitted once
- deterministic ordering
- no presentation event changes rules state

---

## 24. Acceptance Contract

The system is behaving correctly when:

- players can never perform a truly illegal action
- players can still make legal mistakes
- legal mistakes are never pre-warned through hidden strategic analysis
- mission failure can identify the causal action where determinable
- UI state is derived from authoritative game state
- cinematic presentation is driven by semantic events, not embedded in rules logic
- reconnect restores the same game reality
- low-end clients remain fully playable
