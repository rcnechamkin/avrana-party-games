"use strict";
/* EXPO asset slots (AVR-267): the named places where human-made or licensed final art, audio
   and haptics go. NOTHING here is final art. Every visual slot is filled by a neutral geometric
   or procedural placeholder drawn in CSS or inline SVG; every audio slot is empty (silent).
   Documented in docs/ASSETS.md ("EXPO presentation slots") and games/expo/docs/PRESENTATION.md.

   art      a CSS custom property on .app (expo.css) or an SVG <symbol> id (index.html)
   audio    null = silent. To fill: {src: "audio/<file>", volume: 0..1}, a file served from this
            directory (the appliance is offline: no external URL)
   haptics  a navigator.vibrate pattern in milliseconds, or null

   Loaded as a plain script (window.ExpoSlots) and by the Node tests (module.exports). */
(function (root) {
  const placeholder = what => Object.freeze({status: "placeholder", ...what});
  const slots = Object.freeze({
    version: 1,
    art: Object.freeze({
      "stage.sky":        placeholder({css: "--slot-stage-sky", now: "CSS gradient"}),
      "stage.ridge":      placeholder({symbol: "expo-slot-ridge", now: "inline SVG polygon skyline"}),
      "stage.haze":       placeholder({css: "--slot-stage-haze", now: "CSS gradient bands, drifting at the high tier"}),
      "stage.glow":       placeholder({css: "--slot-stage-glow", now: "CSS radial gradient, tinted by the mission state"}),
      "board.ground":     placeholder({css: "--slot-board-ground", now: "CSS gradient"}),
      "card.face":        placeholder({css: "--slot-card-face", now: "CSS gradient; rank, symbol and suit are text"}),
      "radio.icon":       placeholder({symbol: "expo-slot-radio", now: "inline SVG arcs"}),
      "hazard.icon":      placeholder({symbol: "expo-slot-hazard", now: "inline SVG trefoil of circles"}),
      "result.failure":   placeholder({css: "--slot-result-failure", now: "CSS gradient"}),
      "result.success":   placeholder({css: "--slot-result-success", now: "CSS gradient"}),
      "crew.portrait":    placeholder({now: "none on the board: names only (the Party's avatars are the lobby's)"}),
    }),
    audio: Object.freeze({
      "card.play": null, "trick.resolve": null, "turn.mine": null,
      "radio.send": null, "radio.receive": null,
      "objective.complete": null, "objective.fail": null,
      "mission.brief": null, "mission.success": null, "mission.failure": null,
      "ambient.wasteland": null,
    }),
    haptics: Object.freeze({
      "card.play": null, "turn.mine": [12], "trick.resolve": [16],
      "radio.send": [8], "radio.receive": [8, 40, 8],
      "objective.complete": [14], "objective.fail": [24],
      "mission.brief": null, "mission.success": [12, 40, 12, 40, 24], "mission.failure": [30, 60, 30],
    }),
  });
  if (typeof module !== "undefined" && module.exports) module.exports = slots;
  else root.ExpoSlots = slots;
})(typeof window !== "undefined" ? window : globalThis);
