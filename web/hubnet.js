/* hubnet.js — shared client plumbing for every hub game.
   Identity (same localStorage keys as WORDCLASH so names carry over),
   reconnecting WebSocket, server-clock offset, toasts, confetti. */
"use strict";

const Hub = (() => {
  const AVATARS = ["🦊", "🐸", "🦖", "🐙", "🦉", "🐯", "🐼", "🦄",
                   "👾", "🤖", "🐲", "😈", "🦈", "🐝", "🦩", "🐢"];
  const integrated = window.AvranaIntegration?.integrated === true;
  const gameSlug = (location.pathname.match(/^\/games\/([^/]+)/) || [])[1] || "";

  // Every game loads this file, so nested game pages get the same home-screen
  // identity without copying manifest markup into every client.
  if (!integrated && !document.querySelector('link[rel="manifest"]')) {
    const manifest = document.createElement("link");
    manifest.rel = "manifest";
    manifest.href = "/app.webmanifest";
    document.head.appendChild(manifest);
  }
  if (!document.querySelector('link[rel="apple-touch-icon"]')) {
    const icon = document.createElement("link");
    icon.rel = "apple-touch-icon";
    icon.sizes = "180x180";
    icon.href = "/shared/app-icon-180.png";
    document.head.appendChild(icon);
  }
  if (!document.querySelector('link[rel~="icon"]')) {
    const favicon = document.createElement("link");
    favicon.rel = "icon";
    favicon.type = "image/svg+xml";
    favicon.href = "/shared/app-icon.svg";
    document.head.appendChild(favicon);
  }
  if (!integrated && "serviceWorker" in navigator && window.isSecureContext) {
    addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    }, { once: true });
  }

  // The suite art direction is delivered from one shared runtime so every
  // mounted game gets the same polish without duplicating it in 25 clients.
  if (gameSlug && !document.querySelector('link[href="/shared/gameart.css"]')) {
    const artCss = document.createElement("link");
    artCss.rel = "stylesheet";
    artCss.href = "/shared/gameart.css";
    document.head.appendChild(artCss);
  }
  if (!document.querySelector('script[src^="/shared/brand.js"]')) {
    const brandScript = document.createElement("script");
    brandScript.src = "/shared/brand.js?v=avrana1";
    document.head.appendChild(brandScript);
  }

  const identity = {
    get token() { return localStorage.getItem("wc-token") || ""; },
    set token(v) { localStorage.setItem("wc-token", v); },
    get name() { return localStorage.getItem("wc-name") || ""; },
    set name(v) { localStorage.setItem("wc-name", v); },
    get avatar() { return localStorage.getItem("wc-avatar") || ""; },
    set avatar(v) { localStorage.setItem("wc-avatar", v); },
    // the device's uploaded photo URL, remembered so the hub can show it
    // without a live game connection
    get pfp() { return localStorage.getItem("wc-pfp") || ""; },
    set pfp(v) { if (v) localStorage.setItem("wc-pfp", v); else localStorage.removeItem("wc-pfp"); },
    ensureToken() {
      // uploads can happen before the first WS welcome assigns a token —
      // mint one client-side (server accepts well-formed client tokens)
      if (!this.token) {
        const b = crypto.getRandomValues(new Uint8Array(16));
        this.token = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
      }
      return this.token;
    },
  };

  const systemReduced = matchMedia("(prefers-reduced-motion: reduce)");
  const prefs = {
    get sound() { return localStorage.getItem("wc-muted") !== "1"; },
    set sound(v) { localStorage.setItem("wc-muted", v ? "0" : "1"); },
    get haptics() { return localStorage.getItem("lg-haptics") !== "0"; },
    set haptics(v) { localStorage.setItem("lg-haptics", v ? "1" : "0"); },
    get reducedFx() {
      const value = localStorage.getItem("lg-motion");
      return value === "reduced" || (value !== "full" && systemReduced.matches);
    },
    set reducedFx(v) { localStorage.setItem("lg-motion", v ? "reduced" : "full"); applyPrefs(); },
    get contrast() { return localStorage.getItem("lg-contrast") === "1"; },
    set contrast(v) { localStorage.setItem("lg-contrast", v ? "1" : "0"); applyPrefs(); },
  };

  function applyPrefs() {
    document.documentElement.classList.toggle("lg-reduced-fx", prefs.reducedFx);
    document.documentElement.classList.toggle("lg-high-contrast", prefs.contrast);
  }
  applyPrefs();
  systemReduced.addEventListener?.("change", applyPrefs);

  // Existing games call navigator.vibrate directly. Respect the suite-level
  // haptics setting without forcing every mature client to duplicate a guard.
  if (typeof navigator.vibrate === "function" && !navigator.vibrate.__lanGamesWrapped) {
    const nativeVibrate = navigator.vibrate.bind(navigator);
    const wrapped = (pattern) => prefs.haptics ? nativeVibrate(pattern) : false;
    wrapped.__lanGamesWrapped = true;
    try { navigator.vibrate = wrapped; } catch (error) { /* readonly browser API */ }
  }

  const feedback = (() => {
    let ctx = null;
    const tone = (frequency, duration = .055, volume = .018, type = "sine", delay = 0) => {
      if (!prefs.sound) return;
      try {
        if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
        if (ctx.state === "suspended") ctx.resume();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        const at = ctx.currentTime + delay;
        osc.type = type;
        osc.frequency.setValueAtTime(frequency, at);
        gain.gain.setValueAtTime(.0001, at);
        gain.gain.exponentialRampToValueAtTime(volume, at + .01);
        gain.gain.exponentialRampToValueAtTime(.0001, at + duration);
        osc.connect(gain); gain.connect(ctx.destination);
        osc.start(at); osc.stop(at + duration + .02);
      } catch (error) { /* audio is optional */ }
    };
    return {
      tap() { tone(470); },
      select() { tone(520, .07, .022); tone(740, .06, .016, "sine", .045); },
      success() { tone(523, .18, .025); tone(659, .17, .022, "sine", .08); tone(784, .2, .02, "sine", .16); },
      error() { tone(145, .18, .028, "sawtooth"); },
      haptic(pattern = 18) {
        try { if (prefs.haptics) navigator.vibrate?.(pattern); } catch (error) { /* optional */ }
      },
    };
  })();

  /* render a player's avatar into `el`: custom photo if they have one (the server
     also sends a chosen Avrana avatar as `pfp`, core/looks.py), else their own chosen
     Avrana avatar id (gaze-NN, e.g. your local identity), else their emoji.
     Sizing is em-based, so it scales with the host. */
  const LOOK = /^gaze-(0[1-9]|[12]\d|3[0-2])$/;
  function fillAvatar(el, p) {
    el.textContent = "";
    const picture = p && (p.pfp || (LOOK.test(p.avatar || "") ? "/shared/avatars/" + p.avatar + ".svg" : ""));
    if (picture) {
      const img = document.createElement("img");
      img.className = "pfp";
      img.src = picture;
      img.alt = "";
      img.draggable = false;
      el.appendChild(img);
    } else {
      el.textContent = p ? p.avatar : "?";
    }
  }

  async function uploadPfp(file) {
    const res = await fetch("/api/avatar", {
      method: "POST",
      headers: { "x-wc-token": identity.ensureToken() },
      body: file,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || "upload failed");
    }
    const url = (await res.json()).url;
    identity.pfp = url;
    return url;
  }

  async function removePfp() {
    await fetch("/api/avatar", {
      method: "DELETE",
      headers: { "x-wc-token": identity.ensureToken() },
    }).catch(() => {});
    identity.pfp = "";
  }

  /* editPhoto(file) -> Promise<Blob|null>: a crop+zoom modal. The user pans
     (drag), zooms (pinch / slider), frames their face in the circle, and we
     render the framed square to a 512px canvas. Resolves null if cancelled.
     Respects EXIF orientation so phone photos aren't sideways. */
  function editPhoto(file) {
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "crop-ov";
      ov.innerHTML =
        '<div class="crop-card">'
        + '<p class="crop-title">FRAME YOUR FACE</p>'
        + '<div class="crop-stage"><canvas class="crop-cv"></canvas>'
        + '<div class="crop-ring"></div></div>'
        + '<div class="crop-zoom"><span>👤</span>'
        + '<input type="range" class="crop-slider" min="1" max="4" step="0.01" value="1">'
        + '<span>🔍</span></div>'
        + '<p class="crop-hint">drag to move · pinch or slide to zoom</p>'
        + '<div class="crop-btns"><button class="btn crop-cancel">CANCEL</button>'
        + '<button class="btn btn-primary crop-ok">USE PHOTO</button></div></div>';
      document.body.appendChild(ov);
      const cv = ov.querySelector(".crop-cv");
      const ctx = cv.getContext("2d");
      const slider = ov.querySelector(".crop-slider");
      let img = null, V = 0, iw = 0, ih = 0, base = 1, zoom = 1, ox = 0, oy = 0;

      function fit() {
        const stage = ov.querySelector(".crop-stage");
        V = stage.clientWidth || 260;
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        cv.width = V * dpr; cv.height = V * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
      function draw() {
        const s = base * zoom, dw = iw * s, dh = ih * s;
        ox = Math.min(0, Math.max(V - dw, ox));   // image always covers the frame
        oy = Math.min(0, Math.max(V - dh, oy));
        ctx.clearRect(0, 0, V, V);
        ctx.drawImage(img, ox, oy, dw, dh);
      }
      function loaded(im) {
        img = im; iw = im.width || im.naturalWidth; ih = im.height || im.naturalHeight;
        fit();
        base = Math.max(V / iw, V / ih);
        zoom = 1; slider.value = 1;
        ox = (V - iw * base) / 2; oy = (V - ih * base) / 2;
        draw();
      }
      (async () => {
        try {
          if (window.createImageBitmap) {
            loaded(await createImageBitmap(file, { imageOrientation: "from-image" }));
            return;
          }
        } catch (e) { /* fall through to <img> */ }
        const im = new Image();
        im.onload = () => loaded(im);
        im.onerror = () => { ov.remove(); toast("couldn't read that image", "err"); resolve(null); };
        im.src = URL.createObjectURL(file);
      })();

      function setZoom(z, fx, fy) {
        z = Math.min(4, Math.max(1, z));
        const rect = cv.getBoundingClientRect();
        const px = fx == null ? V / 2 : fx - rect.left;
        const py = fy == null ? V / 2 : fy - rect.top;
        const s0 = base * zoom, s1 = base * z;
        ox = px - (px - ox) * (s1 / s0);          // keep focal point steady
        oy = py - (py - oy) * (s1 / s0);
        zoom = z; slider.value = z;
        draw();
      }
      slider.addEventListener("input", () => setZoom(parseFloat(slider.value)));

      const pts = new Map();
      let drag = null, pinch = null;
      cv.addEventListener("pointerdown", (e) => {
        cv.setPointerCapture(e.pointerId);
        pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (pts.size === 1) drag = { x: e.clientX, y: e.clientY };
        else if (pts.size === 2) {
          const [a, b] = [...pts.values()];
          pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), z: zoom }; drag = null;
        }
      });
      cv.addEventListener("pointermove", (e) => {
        if (!pts.has(e.pointerId) || !img) return;
        pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (pinch && pts.size >= 2) {
          const [a, b] = [...pts.values()];
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          setZoom(pinch.z * (d / pinch.d), (a.x + b.x) / 2, (a.y + b.y) / 2);
        } else if (drag && pts.size === 1) {
          ox += e.clientX - drag.x; oy += e.clientY - drag.y;
          drag = { x: e.clientX, y: e.clientY }; draw();
        }
      });
      const endPtr = (e) => {
        pts.delete(e.pointerId);
        if (pts.size < 2) pinch = null;
        if (pts.size === 0) drag = null;
      };
      cv.addEventListener("pointerup", endPtr);
      cv.addEventListener("pointercancel", endPtr);

      const close = (val) => { ov.remove(); resolve(val); };
      ov.querySelector(".crop-cancel").onclick = () => close(null);
      ov.addEventListener("click", (e) => { if (e.target === ov) close(null); });
      ov.querySelector(".crop-ok").onclick = () => {
        if (!img) return close(null);
        const E = 512, out = document.createElement("canvas");
        out.width = E; out.height = E;
        const f = E / V, s = base * zoom;
        out.getContext("2d").drawImage(img, ox * f, oy * f, iw * s * f, ih * s * f);
        out.toBlob((blob) => close(blob), "image/webp", 0.9);
      };
    });
  }

  /* one-tap photo picker: file input -> crop/zoom -> upload -> notify the
     server via {t:"profile"} so game state refreshes */
  function wirePfpButton(btn, getConn, onDone) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.hidden = true;
    document.body.appendChild(input);
    btn.addEventListener("click", () => input.click());
    input.addEventListener("change", async () => {
      const f = input.files && input.files[0];
      input.value = "";
      if (!f) return;
      try {
        const blob = await editPhoto(f);
        if (!blob) return;                        // cancelled
        const url = await uploadPfp(blob);
        const conn = getConn && getConn();
        if (conn) conn.send({ t: "profile" });
        toast("📷 picture saved");
        onDone && onDone(url);
      } catch (e) {
        toast(e.message || "upload failed", "err");
      }
    });
  }

  function buildAvatarGrid(host, current, onPick) {
    host.textContent = "";
    for (const a of AVATARS) {
      const c = document.createElement("button");
      c.className = "avatar-cell" + (a === current ? " sel" : "");
      c.textContent = a;
      c.onclick = () => {
        host.querySelectorAll(".avatar-cell").forEach((x) => x.classList.remove("sel"));
        c.classList.add("sel");
        onPick(a);
      };
      host.appendChild(c);
    }
  }

  /* System icons for the shared game shell (Avrana system language): Lucide line icons,
     from lucide-static 1.48.0 (ISC licence, https://lucide.dev/license; docs/ASSETS.md).
     Markup opts in with <span data-icon="name"></span>; a few controls whose games still
     write an emoji glyph into them (sound, photo, back) are upgraded in place, so no game
     script has to change. Game artwork is never touched here. */
  const UI_ICONS = {"camera":[["path",{"d":"M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z"}],["circle",{"cx":"12","cy":"13","r":"3"}]],"volume-2":[["path",{"d":"M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"}],["path",{"d":"M16 9a5 5 0 0 1 0 6"}],["path",{"d":"M19.364 18.364a9 9 0 0 0 0-12.728"}]],"volume-x":[["path",{"d":"M11 4.702a.7.7 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.7.7 0 0 0 11 19.298z"}],["path",{"d":"m16.5 14.5 5-5"}],["path",{"d":"m16.5 9.5 5 5"}]],"house":[["path",{"d":"M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"}],["path",{"d":"M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"}]],"tv":[["path",{"d":"m17 2-5 5-5-5"}],["rect",{"width":"20","height":"15","x":"2","y":"7","rx":"2"}]],"arrow-up-right":[["path",{"d":"M7 7h10v10"}],["path",{"d":"M7 17 17 7"}]],"circle-user-round":[["path",{"d":"M17.925 20.056a6 6 0 0 0-11.851.001"}],["circle",{"cx":"12","cy":"11","r":"4"}],["circle",{"cx":"12","cy":"12","r":"10"}]],"sparkles":[["path",{"d":"M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"}],["path",{"d":"M20 2v4"}],["path",{"d":"M22 4h-4"}],["circle",{"cx":"4","cy":"20","r":"2"}]],"target":[["circle",{"cx":"12","cy":"12","r":"10"}],["circle",{"cx":"12","cy":"12","r":"6"}],["circle",{"cx":"12","cy":"12","r":"2"}]],"moon":[["path",{"d":"M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"}]],"sun":[["circle",{"cx":"12","cy":"12","r":"4"}],["path",{"d":"M12 2v2"}],["path",{"d":"M12 20v2"}],["path",{"d":"m4.93 4.93 1.41 1.41"}],["path",{"d":"m17.66 17.66 1.41 1.41"}],["path",{"d":"M2 12h2"}],["path",{"d":"M20 12h2"}],["path",{"d":"m6.34 17.66-1.41 1.41"}],["path",{"d":"m19.07 4.93-1.41 1.41"}]],"trophy":[["path",{"d":"M10 14.66V17a1 1 0 0 1-1 1 2 2 0 0 0-2 2v2"}],["path",{"d":"M14 14.66V17a1 1 0 0 0 1 1 2 2 0 0 1 2 2v2"}],["path",{"d":"M17.916 10H19.5A2.5 2.5 0 0 0 22 7.5V5a1 1 0 0 0-1-1h-3"}],["path",{"d":"M4 22h16"}],["path",{"d":"M6 9a6 6 0 0 0 12 0V3a1 1 0 0 0-1-1H7a1 1 0 0 0-1 1z"}],["path",{"d":"M6.084 10H4.5A2.5 2.5 0 0 1 2 7.5V5a1 1 0 0 1 1-1h3"}]],"a-large-small":[["path",{"d":"m15 16 2.536-7.328a1.02 1.02 1 0 1 1.928 0L22 16"}],["path",{"d":"M15.697 14h5.606"}],["path",{"d":"m2 16 4.039-9.69a.5.5 0 0 1 .923 0L11 16"}],["path",{"d":"M3.304 13h6.392"}]],"compass":[["circle",{"cx":"12","cy":"12","r":"10"}],["path",{"d":"m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z"}]],"zap":[["path",{"d":"M15.914 4a1.5 1.5 0 00-2.474-1.561l-9 9A1.5 1.5 0 005.5 14h4.002a.5.5 0 01.471.666L8.086 20a1.5 1.5 0 002.475 1.56l9-9A1.5 1.5 0 0018.5 10h-3.997a.5.5 0 01-.472-.667z"}]],"radio-tower":[["path",{"d":"M4.9 16.1C1 12.2 1 5.8 4.9 1.9"}],["path",{"d":"M7.8 4.7a6.14 6.14 0 0 0-.8 7.5"}],["circle",{"cx":"12","cy":"9","r":"2"}],["path",{"d":"M16.2 4.8c2 2 2.26 5.11.8 7.47"}],["path",{"d":"M19.1 1.9a9.96 9.96 0 0 1 0 14.1"}],["path",{"d":"M9.5 18h5"}],["path",{"d":"m8 22 4-11 4 11"}]],"heart-pulse":[["path",{"d":"M2 9.5a5.5 5.5 0 0 1 9.591-3.676.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5"}],["path",{"d":"M3.22 13H9.5l.5-1 2 4.5 2-7 1.5 3.5h5.27"}]],"layout-grid":[["rect",{"width":"7","height":"7","x":"3","y":"3","rx":"1"}],["rect",{"width":"7","height":"7","x":"14","y":"3","rx":"1"}],["rect",{"width":"7","height":"7","x":"14","y":"14","rx":"1"}],["rect",{"width":"7","height":"7","x":"3","y":"14","rx":"1"}]]};
  const SVG_NS = "http://www.w3.org/2000/svg";
  function icon(name) {
    const svg = document.createElementNS(SVG_NS, "svg");
    for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
      "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", class: "ui-ic",
      "aria-hidden": "true", focusable: "false" })) svg.setAttribute(k, v);
    for (const [tag, props] of UI_ICONS[name] || []) {
      const child = document.createElementNS(SVG_NS, tag);
      for (const [k, v] of Object.entries(props)) child.setAttribute(k, v);
      svg.appendChild(child);
    }
    return svg;
  }
  // glyph -> [icon, accessible name when the control shows only the icon]
  const CONTROL_GLYPHS = [["\u{1F50A}", "volume-2", "Sound on"], ["\u{1F507}", "volume-x", "Sound off"],
    ["\u{1F4F7}", "camera", "Your photo"], ["\u{1F579}", "house", "All games"], ["\u25CE", "circle-user-round", "Your photo"]];
  function upgradeControl(el) {
    const text = (el.textContent || "").trim();
    const hit = CONTROL_GLYPHS.find(([glyph]) => text.startsWith(glyph));
    if (!hit) return;
    const [glyph, name, label] = hit;
    const rest = text.slice(glyph.length).replace(/^\uFE0F/, "").trim();
    el.replaceChildren(icon(name), ...(rest ? [document.createTextNode(" " + rest)] : []));
    // sound toggles say their state; other icon-only controls keep a name they already have
    if (!rest && (name.startsWith("volume") || !el.getAttribute("aria-label"))) el.setAttribute("aria-label", label);
  }
  function installIcons() {
    document.querySelectorAll("[data-icon]:empty").forEach((slot) => slot.appendChild(icon(slot.dataset.icon)));
    document.querySelectorAll("#mute-btn, #mute-btn2, #pfp-btn, #pfp-btn2, .pfp-btn, [data-avrana-return]")
      .forEach((el) => {
        upgradeControl(el);
        new MutationObserver(() => upgradeControl(el))
          .observe(el, { childList: true, characterData: true, subtree: true });
      });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", installIcons, { once: true });
  else installIcons();

  function toast(msg, cls = "") {
    let holder = document.getElementById("toasts");
    if (!holder) {
      holder = document.createElement("div");
      holder.id = "toasts";
      holder.className = "toasts";
      document.body.appendChild(holder);
    }
    const t = document.createElement("div");
    t.className = "toast " + cls;
    t.textContent = msg;
    holder.appendChild(t);
    setTimeout(() => t.remove(), 3200);
  }

  /* Avrana party session v0 (AVR-22): in an integrated page, ask the party for a ticket for this
     game before every connect. The party cookie (Path=/party/) authenticates the request; the
     ticket travels only in the WebSocket hello, never in a URL. null = no party session for
     this page (no party service, not a member, another game): use today's hello, which the game
     server treats as a watcher while a party session runs. */
  async function partyTicket() {
    try {
      const res = await fetch("/party/api/session/ticket", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json" }, body: "{}",
      });
      if (!res.ok) return null;
      const body = await res.json();
      return body && body.game === gameSlug && typeof body.ticket === "string" ? body.ticket : null;
    } catch (error) {
      return null;
    }
  }

  /* connect(gamePath, handlers, opts) -> conn
     handlers: onState(st), onFx(fx), onWelcome(msg)
     opts.watch: connect as a read-only spectator (the big-screen / TV view) —
       no token, no join; the server pushes the masked spectator state.
     conn: send(obj), now() (server-synced ms), alive */
  function connect(wsPath, handlers, opts = {}) {
    const conn = { ws: null, offset: 0, retry: 0, closedByUs: false,
                   send(obj) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj)); },
                   now() { return Date.now() + this.offset; } };
    let banner = document.getElementById("conn-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "conn-banner";
      banner.className = "conn-banner";
      banner.textContent = "RECONNECTING…";
      banner.hidden = true;
      document.body.appendChild(banner);
    }
    let rejects = 0, gaveUp = false, timer = null, fetching = false;
    function schedule(wait) {
      clearTimeout(timer);
      timer = setTimeout(() => { timer = null; open(); }, wait);
    }
    function open() {
      if (!integrated || opts.watch) { start(null); return; }
      if (fetching) return;                 // a wake-up while the ticket is on its way
      fetching = true;
      partyTicket().then((ticket) => {
        fetching = false;
        if (!conn.closedByUs) start(ticket);
      });
    }
    function start(ticket) {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}${wsPath}`);
      conn.ws = ws;
      let welcomed = false, opened = false;
      ws.onopen = () => {
        opened = true;
        conn.retry = 0;
        banner.hidden = true;
        if (opts.watch) {
          ws.send(JSON.stringify({ t: "hello", watch: true }));
        } else if (ticket) {
          ws.send(JSON.stringify({ t: "hello", ticket, avatar: identity.avatar || undefined }));
        } else {
          ws.send(JSON.stringify({
            t: "hello", token: identity.token || undefined,
            name: identity.name || undefined,
            avatar: identity.avatar || undefined,
          }));
        }
      };
      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        if (msg.type === "welcome") {
          welcomed = true;
          rejects = 0;
          if (msg.token) identity.token = msg.token;
          handlers.onWelcome && handlers.onWelcome(msg);
        } else if (msg.type === "fx" && !welcomed) {
          // pre-welcome fx = join rejection reason (e.g. room full)
          if (msg.msg) toast(msg.msg, "err");
        } else if (msg.type === "state") {
          const off = msg.now - Date.now();
          conn.offset = conn.offset === 0 ? off : conn.offset * 0.8 + off * 0.2;
          handlers.onState(msg);
        } else if (msg.type === "fx") {
          handlers.onFx && handlers.onFx(msg);
        }
      };
      ws.onclose = () => {
        if (conn.closedByUs) return;
        if (!welcomed && opened) {
          // the server accepted the socket but refused this join (room full /
          // socket cap) — do NOT hammer it forever. A socket that never opened
          // is a network failure (sleep, airplane mode, Wi-Fi rejoining): keep
          // retrying, or a phone that was offline for ~5 s would never recover.
          rejects++;
          if (rejects >= 3) {
            gaveUp = true;
            banner.hidden = true;
            toast("can't join right now — the room is full", "err");
            return;
          }
        }
        banner.hidden = false;
        const wait = Math.min(5000, 600 + conn.retry * 800);
        conn.retry++;
        schedule(wait);
      };
      ws.onerror = () => { try { ws.close(); } catch (e) {} };
    }
    open();
    // A phone waking up or getting its network back should not wait out the
    // backoff: reconnect at once if the socket is neither open nor connecting.
    const kick = () => {
      if (conn.closedByUs || gaveUp || fetching) return;
      const s = conn.ws && conn.ws.readyState;
      if (s === 0 || s === 1) return;
      conn.retry = 0;
      schedule(0);
    };
    addEventListener("online", kick);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") kick();
    });
    setInterval(() => conn.send({ t: "ping" }), 25000);
    return conn;
  }

  /* tiny confetti (canvas #confetti must exist) */
  function confettiBurst(n = 160) {
    if (prefs.reducedFx) return;
    const cv = document.getElementById("confetti");
    if (!cv) return;
    if (!cv._parts) {
      cv._parts = [];
      const fit = () => { cv.width = innerWidth; cv.height = innerHeight; };
      addEventListener("resize", fit); fit();
    }
    const COLS = ["#22d3ee", "#a78bfa", "#f472b6", "#10c96e", "#eab308"];
    for (let i = 0; i < n; i++) {
      cv._parts.push({
        x: Math.random() * innerWidth, y: -20 - Math.random() * 80,
        vx: (Math.random() - 0.5) * 3, vy: 2 + Math.random() * 4,
        rot: Math.random() * 6.28, vr: (Math.random() - 0.5) * 0.3,
        w: 6 + Math.random() * 7, h: 4 + Math.random() * 5,
        c: COLS[(Math.random() * COLS.length) | 0], life: 250,
      });
    }
    if (!cv._raf) {
      const cx = cv.getContext("2d");
      const loop = () => {
        cv._raf = requestAnimationFrame(loop);
        cx.clearRect(0, 0, cv.width, cv.height);
        cv._parts = cv._parts.filter((p) => p.life > 0 && p.y < cv.height + 30);
        if (!cv._parts.length) { cancelAnimationFrame(cv._raf); cv._raf = null; return; }
        for (const p of cv._parts) {
          p.x += p.vx; p.y += p.vy; p.rot += p.vr; p.vy += 0.02; p.life--;
          cx.save(); cx.translate(p.x, p.y); cx.rotate(p.rot);
          cx.fillStyle = p.c; cx.globalAlpha = Math.min(1, p.life / 60);
          cx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); cx.restore();
        }
      };
      loop();
    }
  }

  async function installGameShell() {
    if (!gameSlug) return;

    // A consistent escape hatch matters once the suite runs standalone from a
    // home-screen icon: browser chrome is no longer there to rescue the user.
    const join = document.getElementById("scr-join");
    if (!integrated && join && !join.querySelector(".suite-home")) {
      const home = document.createElement("a");
      home.className = "suite-home";
      home.href = "/";
      home.setAttribute("aria-label", "Back to all games");
      home.innerHTML = '<span aria-hidden="true">‹</span><b>ALL GAMES</b>';
      join.appendChild(home);
    }

    const decorate = async () => {
      try {
        const payload = await (await fetch("/api/games")).json();
        const all = [...(payload.games || []), ...(payload.external || [])];
        const game = all.find((entry) => entry.slug === gameSlug);
        if (game && window.GameArt) window.GameArt.installJoinArt(game);
      } catch (error) { /* the game remains fully usable without decoration */ }
    };
    if (window.GameArt) {
      decorate();
    } else {
      const script = document.createElement("script");
      script.src = "/shared/gameart.js";
      script.onload = decorate;
      document.head.appendChild(script);
    }
  }
  queueMicrotask(installGameShell);

  return { AVATARS, identity, buildAvatarGrid, toast, connect, confettiBurst, icon,
           fillAvatar, uploadPfp, removePfp, editPhoto, wirePfpButton,
           prefs, feedback, applyPrefs };
})();
