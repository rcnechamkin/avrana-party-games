# NOTICE: Avrana Party Games

Avrana Party Games is the source of Avrana Party's native, browser-based
multiplayer games. It is a fork of **LAN Games** by **BEACNpool**
(https://github.com/BEACNpool/LAN-Games; upstream retired in September 2026).

## Licence

Everything in this repository is licensed under the **MIT License**, see
[`LICENSE`](LICENSE) (unchanged from upstream):

- Upstream LAN Games code, docs and media: © 2026 BEACNpool.
- Modifications and new files by Avrana Party Games: © 2026 Avrana Party Games,
  offered under the same MIT terms.

## Third-party components

| Component | Licence | How it's used |
|---|---|---|
| FastAPI | MIT | runtime dependency |
| Uvicorn | BSD-3-Clause | runtime dependency |
| websockets | BSD-3-Clause | runtime dependency |
| Pillow | MIT-CMU | runtime dependency |
| python-chess | GPL-3.0-or-later | runtime dependency of the upstream chess/duel games (installed from PyPI, not bundled) |
| **Sora** font (`web/fonts/sora-var.woff2`, `games/wordclash/web/fonts/sora-var.woff2`) | SIL OFL 1.1, © 2019 The Sora Project Authors | **bundled**; licence in `OFL-Sora.txt` beside each copy |
| **JetBrains Mono** font (`web/fonts/jbmono-var.woff2`, `games/wordclash/web/fonts/jbmono-var.woff2`) | SIL OFL 1.1, © 2020 The JetBrains Mono Project Authors | **bundled**; licence in `OFL-JetBrainsMono.txt` beside each copy |

The OFL licence texts were added by Avrana Party Games. Upstream LAN Games
bundled these fonts without them.

## Game designs

Avrana games may take mechanical inspiration from existing tabletop games. Game
mechanics aren't protected, but names, artwork and rules text are. Avrana games use
their own names, text and assets, and don't reproduce any publisher's branding or
artwork.
