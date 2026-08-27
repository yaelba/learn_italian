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

**Photo hotspot overlap: smaller box on top.** Bounding boxes from real photos routinely
overlap (a cushion box nested inside an armchair box; adjacent appliances with sliver
overlaps) — this isn't a detection error, it reflects real object arrangement. Since
`type: 'photo'` hotspots are flat rectangles, only one can catch a tap in a shared
region, so the renderer needs a deterministic stacking rule: render hotspots smallest-area-first,
so smaller/nested boxes always render on top and stay tappable. This is a heuristic (it
assumes smaller area correlates with "more specific," which holds for nesting but is
arbitrary for two similar-sized items that merely touch at an edge) — acceptable for now,
revisit if it causes real mis-taps.

**Content-generation agent: box-detection feasibility confirmed.** A single-shot request to
`claude-opus-5` — the photo plus a list of item names, structured output via
`output_config.format`/`client.messages.parse()` returning `{id, x, y, w, h}` per item —
correctly located 18/18 test items across three photos (living room, two kitchen counters),
including crowded/adjacent objects. No iterative crop-and-verify loop needed. Two prompting
notes from testing: (1) when a scene has multiple instances of the same item (several lemons
in a bowl), explicitly instruct the model to pick **one** instance and box only it — without
this, entangled/touching instances (a banana bunch) get boxed as one big cluster instead of
a single item. (2) Source photo resolution/quality doesn't matter — hotspot coordinates are
percentage-based, so phone photos should be downscaled before sending (saves tokens, no
accuracy cost). Feasibility script (since renamed/extended, see below): `agent/generate_scene.py`.

**Content-generation agent: intermittent empty results on photos with people.** When a
scene includes real people — specifically, a request localizing a child ("boy") and pieces
of their clothing — the model occasionally returned a validly-shaped but empty `hotspots: []`
result instead of the expected boxes, with no error or refusal reason surfaced. Two immediate
reruns of the identical input both succeeded fully. Likely cause: Claude's safety classifiers
apply extra caution to requests that precisely localize a minor's body/clothing in an image,
even for completely benign photos (here, a family photo of kids at a pool), and can behave
probabilistically rather than deterministically — not a reflection of anything wrong with the
photo or the request. The script (then still named `test_bbox_feasibility.py`) was updated to
never fail silently: it checks `stop_reason` for a hard refusal, and separately warns loudly
whenever any requested item — or all of them — comes back with no box, instead of just saving a
boxless image with no indication anything went wrong. Practical implication: since source photos
for this project will likely often include people, expect this to recur occasionally; the
workaround is simply to rerun. Not designing further around it for now — revisit if it turns out
to happen often enough to be disruptive.

**Content-generation agent: script now also produces translations.** Renamed
`test_bbox_feasibility.py` → `agent/generate_scene.py` to reflect its evolved role — no longer
just a localization test, but the actual per-scene generation step. The same single API call now
also returns each item's Italian translation and article (`{id, article, it, en, x, y, w, h}`
per hotspot), matching the existing word data contract exactly (`id` is the Italian noun/phrase
with its leading article stripped, e.g. `"la torre"` → `"torre"`, mirroring the convention already
used by hand-authored illustrated scenes). Output is now a `<photo>_words.json` file — a
ready-to-paste `words` array — alongside the existing annotated debug image. Still not produced:
the wrapping scene object (`id`, `eyebrow`, `image` path) and the `type: 'photo'` renderer itself
— both remain open next steps.

**Data loading: assume online, fail loudly.** Scene data now lives in `scenes.json` and is
loaded via `fetch()` on startup instead of being inlined in the HTML — this is what "light
repo + hosting" (goal 1) needs, since editing scene data no longer means editing a
2000-line HTML file. For now there is **no offline/local fallback**: the page assumes it's
served over http(s) with `scenes.json` reachable alongside it. If the fetch fails (bad path,
offline, wrong content type), the game replaces the page with a clear bilingual error message
rather than silently rendering a blank or broken game. This is a deliberate scope cut, not an
oversight — revisit if we ever need true offline support (e.g. a service worker or a reinstated
inline fallback copy).

**Scene database vs. published site: three files instead of one.** As the content-generation
agent matured, `scenes.json` started being asked to do two unrelated jobs at once — "every
scene ever generated" and "what's live on the site right now, in what order." An early version
of `agent/build_scenes.py` tried to keep those in sync automatically by treating
`word_lists.txt` as the single source of truth: any run would delete a scene from `scenes.json`
if its line was missing from the file, and reorder everything to match the file's line order.
That turned out to be the wrong call — it's destructive by default (running the script against
a partial/scoped word-list file, e.g. to fix just one scene, would silently wipe out every
other scene), and it conflates "not currently generating this" with "don't want this anymore,"
losing real generated data (translations, hand-checked bounding boxes) for no good reason.

The fix: split the one file into three, each with a single job.
- `scenes_db.json` — the permanent database. Every scene ever generated or hand-authored lives
  here forever. `build_scenes.py`'s normal add/extend mode only ever adds to or extends this
  file; a scene missing from the word list on a given run is left completely untouched, and
  there's no ordering concept here at all (array order is cosmetic).
- `manifest.txt` — a short, hand-edited, ordered list of scene ids to actually publish, one per
  line. Lines starting with `#` are comments, so a scene can be temporarily hidden from the
  site (comment out its line) without losing anything — the data stays in the database either
  way. This file is intentionally not automated; curating the site's contents and order is a
  deliberate editorial choice, not something to infer from generation history.
- `scenes.json` — the file `index.html` actually fetches. It's a generated artifact: `python
  agent/build_scenes.py --publish manifest.txt` filters and reorders `scenes_db.json` by the
  manifest, computing each scene's `"Tappa N"` eyebrow fresh from its position. If the manifest
  references an id that isn't in the database (typo, or removed without updating the manifest),
  publish aborts and writes nothing, listing every missing id — a broken manifest should never
  silently produce a half-broken site.

This also meant separating a scene's permanent `id` (= its photo's filename stem, e.g.
`"library-1"` — never changes, since it's the key used to match `word_lists.txt` lines and
manifest entries) from its `display_name` (the Italian title shown to the player in-game, e.g.
`"La Biblioteca"` — defaults to a model-suggested title, but is a separate field precisely so it
could later be edited without touching the id, the photo file, or anything's matching logic).
Renaming `display_name` via the CLI is deliberately out of scope for now (revisit later; the
field split already leaves room for it).

`build_scenes.py` ended up with four modes instead of one implicit behavior: the normal
add/extend run against a word-list file; `--force <name>` / `--forceall` to force a fresh
re-detection (of one scene or every scene in the file) even when nothing looks new — also
re-copying the photo from `source-photos/`, so swapping in a different photo under the same
filename actually takes effect; `--remove <name>` to permanently delete a scene from the
database (distinct from hiding it via the manifest); and `--publish <manifest_file>` as
described above. Also renamed `test-photos/` → `source-photos/`, since that directory stopped
being about "testing" once it became the permanent source-of-truth folder for the photos the
whole pipeline is built from.

