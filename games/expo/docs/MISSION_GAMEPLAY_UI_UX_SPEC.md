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
## Mission Gameplay UI/UX Design Spec

**Status:** Draft  
**Purpose:** Define the visual and interaction contract for the primary mission gameplay screen.

---

## 1. Core Experience

The game should remain unmistakably a cooperative trick-taking card game.

The wasteland setting, animation, audio, haptics, and mission presentation exist to make the card game feel like a dangerous expedition. They must never obscure the rules.

**Design principle:**

> The cards are the game. The wasteland is the experience.

The screen should always communicate three things clearly:

1. **Who is playing with me?**
2. **What is happening in the current trick?**
3. **What can I legally do right now?**

---

## 2. Screen Pillars

### 2.1 Multiplayer state is always obvious
The screen must never read like a solo card battler.

Players should always be able to identify:

- every active crew member
- the current Captain
- the Party Host, if relevant
- whose turn it is
- who led the current trick
- who is currently winning the trick
- each player's communication/radio state
- approximate hand size or remaining cards where useful

### 2.2 Cards remain literal and readable
Cards should stay visibly card-like.

Every card must clearly communicate:

- suit
- rank/value
- ownership
- whether it is currently legal to play
- whether it has been publicly communicated

Theme can decorate the cards, but should not replace their core information.

### 2.3 The world layer supports the game
The animated wasteland stage should provide atmosphere, mission context, and consequences.

It should not:

- replace the card table
- hide critical information
- delay ordinary play
- require players to decode mechanics from visual storytelling

### 2.4 Legal and losing are different
A hard-illegal action should look unavailable.

A legal action that may cause mission failure must still look playable.

The UI must never blur these states.

### 2.5 Private and shared information remain distinct
The player's hand is private.

The current trick, public communications, mission objectives, and resolved consequences are shared.

The interface should reinforce this boundary visually.

---

## 3. Primary Gameplay Layout

The primary mission screen is divided into five functional zones.

### Zone A — Mission Stage
Located at the top of the screen.

Contains:

- mission title
- short mission objective
- animated environment
- radiation/environment status
- radio status
- major mission-state changes

The stage should normally occupy roughly **15–25%** of the vertical screen.

During major events, it may temporarily expand downward.

Examples:

- mutant approaches
- bunker closes
- storm arrives
- radiation spikes
- extraction begins

### Zone B — Crew Strip
Persistent four-player squad bar.

Each crew slot should show:

- player name
- player avatar/character
- Captain marker if applicable
- Host marker if applicable
- radio/communication availability
- remaining hand size
- current turn emphasis
- disconnected/reconnecting state if needed

The strip should make the game visibly multiplayer before the player even examines the trick area.

### Zone C — Shared Trick Area
The visual center of gameplay.

Each played card must remain associated with the player who played it.

The trick area should show:

- player name/avatar
- played card
- lead suit
- play order
- current winning card/player
- resolved winner after all required cards are played

The winning card should be emphasized without obscuring the others.

### Zone D — Crew Objectives
Compact mission-task area.

Each objective should show:

- objective summary
- assigned player if applicable
- progress
- complete / active / failed state
- critical risk state only when that state is public information

Do not visually frame every objective as belonging to the local player.

### Zone E — Private Hand and Controls
The bottom interaction area.

Contains:

- player's hand
- current legal-play state
- communication control
- player identity
- optional chat/system control
- contextual rule explanation when needed

The player's hand should be large enough for reliable touch input, but not so dominant that the shared game state disappears.

---

## 4. Card Interaction States

Every card in the player's hand must be in one of these visual states.

### 4.1 Legal and available
The card may be played now.

Treatment:

- normal brightness
- subtle lift/highlight when selected
- normal touch response

### 4.2 Hard-illegal
The card cannot legally be played.

Examples:

- must follow suit
- mission prohibits leading with this rank
- not the player's turn
- mission-specific play restriction

Treatment:

- visibly muted
- still readable
- cannot be committed
- tap may show a short factual reason

Example:

> Must follow Blue.

or:

> 3s cannot lead a trick this mission.

### 4.3 Legal but strategically dangerous
The card is legal and must remain fully playable.

The UI must **not**:

- disable it
- tint it as dangerous
- warn that it causes failure
- ask for confirmation
- reveal hidden strategic consequences

The game is a referee, not an oracle.

### 4.4 Communicated card
A card that has been publicly communicated should retain a persistent marker.

The marker should identify the information that was shared:

- highest
- lowest
- only

It remains visible until the card leaves the hand.

---

## 5. Current Trick Presentation

### During play

When a player commits a card:

1. the card leaves their hand
2. the hand closes the gap
3. the card moves into that player's shared trick slot
4. the player's crew tile briefly reacts
5. turn emphasis moves to the next player

### Current winner
While the trick is unresolved, the UI may indicate the current winning card.

This must not imply the trick is final.

### Trick resolution
When the last card lands:

1. brief pause
2. lead suit is reinforced visually
3. cards unable to win de-emphasize slightly
4. trump behavior resolves if relevant
5. winner moves forward visually
6. winner's crew tile reacts
7. haptic/audio cue plays
8. trick is collected
9. objective state is evaluated
10. next leader becomes active

Target duration for ordinary resolution: **under 1 second**.

---

## 6. Communication UX

Communication should be presented as an in-world helmet/radio transmission.

### Entry
Player activates **Burst Transmission**.

The UI should:

- dim nonessential elements slightly
- spread the hand
- highlight only cards that are legally communicable
- preserve the underlying card information

### Card selection
After choosing an eligible card, the engine determines whether the player may legally communicate it as:

- highest
- lowest
- only

The UI should present only valid communication states.

### Transmission
On commit:

- local card gains a communication marker
- crew members receive a short radio pulse
- sender portrait briefly activates
- public communication appears in shared UI
- the player's communication resource is marked used if appropriate

### Restricted communication
Mission-specific states should alter presentation:

- **clear**: clean signal
- **degraded**: visual/audio distortion
- **disabled**: radio unavailable with factual reason

The fiction may explain the rule, but the mechanical rule must still be stated plainly.

---

## 7. Mission Stage Behavior

The top world stage should feel alive even during ordinary thinking time.

Low-cost ambient motion can include:

- drifting toxic fog
- distant creature movement
- blowing dust
- flickering lights
- radiation shimmer
- subtle parallax
- broken signage
- radio interference

These should never interfere with card readability.

The world stage becomes more active when a meaningful state change occurs.

---

## 8. Animation Tiers

### Tier 1 — Microinteraction
**100–400 ms**

Examples:

- card tap
- card lift
- turn highlight
- radio pulse
- crew tile activation
- legal-card emphasis

### Tier 2 — Gameplay event
**500–1500 ms**

Examples:

- trick resolution
- objective completion
- objective failure
- communication received
- Captain identification

### Tier 3 — Cinematic beat
**2–6 seconds**

Examples:

- mission start
- mission-ending failure
- mission victory
- major hazard escalation
- extraction event

Tier 3 events should remain rare.

---

## 9. Failure Presentation

Mission failure should explain:

- **what failed**
- **whose action triggered it**
- **who or what suffered the consequence**

These roles may be different.

Example:

- Alice needed to win Blue 8
- Alice played Blue 8
- Bob legally played Blue 9
- Bob won the trick
- Alice's objective became impossible

The presentation system may interpret that as:

- Alice trapped outside a bunker
- Bob overextends and is taken by a creature
- the team loses the beacon
- the convoy is cut off
- a character becomes contaminated or separated

The rules engine supplies causality.

The cinematic layer supplies fiction.

---

## 10. Success Presentation

The same causal system should support success.

The game may recognize:

- objective owner
- player who directly completed it
- player whose prior action enabled it

This may be acknowledged visually or in debriefing without creating a separate scoring system.

---

## 11. Mission Briefing

Mission start should be theatrical but short.

Suggested sequence:

1. black / radio noise
2. mission title
3. environment reveal
4. crew strip populates
5. cards deal
6. Captain is identified
7. mission objectives appear
8. task selection begins
9. gameplay starts

Target duration: **5–7 seconds**, skippable or accelerable after repeated attempts if desired.

---

## 12. Mission Debrief

Debriefing should summarize the mission without becoming a statistics dashboard.

Useful items:

- mission success/failure
- completed objectives
- failed objective
- triggering player/action when relevant
- notable assist or close call
- crew outcome
- attempt number

A compact replay of the final critical trick may be available after resolution.

---

## 13. Performance and Rendering Principles

The baseline visual system should not depend on realtime 3D.

Preferred stack:

- DOM/CSS for UI
- Web Animations API for card movement
- SVG for icons/HUD
- Canvas 2D for particles and simple scene effects
- sprite sheets / layered images for character and world animation
- optional WebGL/WebGPU for enhanced effects
- cached video snippets only where they provide clear value

WebGPU should be progressive enhancement, not a gameplay dependency.

The Avrana appliance determines authoritative state.

Phones render presentation locally.

---

## 14. Non-Goals

Do not:

- convert the game into a hidden cardless tactical interface
- prevent legal strategic mistakes
- make every trick cinematic
- bury rules inside lore
- use long animations that interrupt planning
- expose hidden information through UI hints
- make the optional TV required for understanding play

---

## 15. Design Test

A successful screen should allow a new observer to answer, within a few seconds:

- Who are the four players?
- Whose turn is it?
- What suit was led?
- Who is currently winning?
- What are the crew trying to accomplish?
- Which cards can the local player legally play?
- Is the radio available?

If those answers require explanation, the screen is too decorative.
