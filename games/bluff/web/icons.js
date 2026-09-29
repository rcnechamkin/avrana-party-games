/* Lucide icons for the BLUFF table chrome, vendored from lucide-static 1.48.0 (only these 16).
   Lucide: ISC License. Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as
   part of Feather (MIT); all other copyright (c) for Lucide are held by Lucide Contributors 2022.
   https://lucide.dev/license  Game content (roles, coins, reactions) keeps its emoji. */
"use strict";

window.BluffIcons = (() => {
  const ICONS = {"house":[["path",{"d":"M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"}],["path",{"d":"M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"}]],"scroll-text":[["path",{"d":"M15 12h-5"}],["path",{"d":"M15 8h-5"}],["path",{"d":"M19 17V5a2 2 0 0 0-2-2H4"}],["path",{"d":"M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3"}]],"x":[["path",{"d":"M18 6 6 18"}],["path",{"d":"m6 6 12 12"}]],"log-out":[["path",{"d":"m16 17 5-5-5-5"}],["path",{"d":"M21 12H9"}],["path",{"d":"M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"}]],"circle-stop":[["circle",{"cx":"12","cy":"12","r":"10"}],["rect",{"x":"9","y":"9","width":"6","height":"6","rx":"1"}]],"play":[["path",{"d":"M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"}]],"check":[["path",{"d":"M20 6 9 17l-5-5"}]],"hand":[["path",{"d":"M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2"}],["path",{"d":"M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v2"}],["path",{"d":"M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8"}],["path",{"d":"M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"}]],"chevron-right":[["path",{"d":"m9 18 6-6-6-6"}]],"minus":[["path",{"d":"M5 12h14"}]],"plus":[["path",{"d":"M5 12h14"}],["path",{"d":"M12 5v14"}]],"timer":[["line",{"x1":"10","x2":"14","y1":"2","y2":"2"}],["line",{"x1":"12","x2":"15","y1":"14","y2":"11"}],["circle",{"cx":"12","cy":"14","r":"8"}]],"pause":[["rect",{"x":"14","y":"3","width":"5","height":"18","rx":"1"}],["rect",{"x":"5","y":"3","width":"5","height":"18","rx":"1"}]],"bot":[["path",{"d":"M12 8V4H8"}],["rect",{"width":"16","height":"12","x":"4","y":"8","rx":"2"}],["path",{"d":"M2 14h2"}],["path",{"d":"M20 14h2"}],["path",{"d":"M15 13v2"}],["path",{"d":"M9 13v2"}]],"circle-help":[["circle",{"cx":"12","cy":"12","r":"10"}],["path",{"d":"M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"}],["path",{"d":"M12 17h.01"}]],"chevron-left":[["path",{"d":"m15 18-6-6 6-6"}]]};
  const NS = "http://www.w3.org/2000/svg";
  // A decorative inline <svg> (the control around it carries the accessible name).
  return function icon(name) {
    const svg = document.createElementNS(NS, "svg");
    const attrs = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2",
      "stroke-linecap": "round", "stroke-linejoin": "round", class: "lucide", "aria-hidden": "true", focusable: "false" };
    for (const [k, val] of Object.entries(attrs)) svg.setAttribute(k, val);
    for (const [tag, props] of ICONS[name] || []) {
      const child = document.createElementNS(NS, tag);
      for (const [k, val] of Object.entries(props)) child.setAttribute(k, val);
      svg.appendChild(child);
    }
    return svg;
  };
})();
