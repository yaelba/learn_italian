# Learn Italian — Phase 2 Build Brief

This is a game that teaches an English-speaking user some Italian vocabulary.
The user can navigate between a series of scenes, each built around an image and the items it contains.
The user learns the Italian words for the items in the scene.
There's also a part of the game in which the user can test their vocabulary across scenes through multiple-choice translation tasks.

## Current state
- Single HTML file (`index.html`, ~2000 lines).
- Scene data lives in `scenes.json`, fetched at startup: `{ id, eyebrow, words: [{id, article, it, en}] }`.
  Other than that, self-contained: no external images, no base64, no audio files. All scenes
  are inline `<svg>`; all speech is live via `window.speechSynthesis` (Web Speech API).
- Each scene is a hand-authored vector illustration. Hotspots are `<g class="hotspot">`
  elements with `data-word` / `data-article` / `data-en` attributes.
- Game mechanics (Esplora / Ascolta e tocca / Abbina / Traduci) hit-test against real
  DOM elements and CSS state classes (`learned`, `correct-flash`, `wrong-flash`, etc.) —
  not coordinate math.

## Goals for phase 2
1. Light repo + hosting so updates don't require re-transferring the file to every device.
2. A content-generation agent: feed it a photo, get back a new playable scene.

## Key design decisions

**Photo scenes.** New scenes built from real trip photos should **not** try to reuse the
hand-illustrated SVG renderer — an agent can't realistically draw matching vector art.
Instead, add a second scene type:

- `type: 'illustrated'` (existing) — hotspots are hand-drawn SVG shapes.
- `type: 'photo'` (new) — background is a real `<img>`; hotspots are normalized
  `{x%, y%, w%, h%}` regions rendered as an absolutely-positioned overlay layer.

Both types share the same data contract (`id`, `words[]`, per-word article/it/en) and
the same quiz/match/translate logic. Only the hotspot rendering + hit-testing differs.

**Data loading: assume online, fail loudly.** Scene data now lives in `scenes.json` and is
loaded via `fetch()` on startup instead of being inlined in the HTML — this is what "light
repo + hosting" (goal 1) needs, since editing scene data no longer means editing a
2000-line HTML file. For now there is **no offline/local fallback**: the page assumes it's
served over http(s) with `scenes.json` reachable alongside it. If the fetch fails (bad path,
offline, wrong content type), the game replaces the page with a clear bilingual error message
rather than silently rendering a blank or broken game. This is a deliberate scope cut, not an
oversight — revisit if we ever need true offline support (e.g. a service worker or a reinstated
inline fallback copy).

