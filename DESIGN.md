# Il Passaporto Italiano — Design

A game that teaches an English-speaking user some Italian vocabulary. The user moves between a
series of scenes, each built around an image and the items in it, and learns the Italian word
for each item. A separate part of the game tests vocabulary across all scenes with
multiple-choice translation tasks. Built for the owner's family around a real trip to Italy.

This file records **how the project is built and why**. `README.md` covers how to run it, and
`CLAUDE.md` is the short briefing for AI-assisted sessions. Last reviewed: 2026-11-10.

## Current architecture

**Runtime.** One `index.html` (~2100 lines of HTML/CSS/JS): no build step, no framework, no
backend. At startup it `fetch()`es `scenes.json` and builds the game from it. Hosted as static
files on GitHub Pages; a `git push` to `main` updates the live site. The only third-party
runtime dependency is Google Fonts. Speech is live via the browser's Web Speech API
(`window.speechSynthesis`), with an Italian-voice picker on the page.

**Two scene types, one data contract.** Every scene is `{ id, eyebrow, words[] }` where each
word is `{ id, article, it, en }` (the game displays `it`; `article` is carried in the data but
never read by game logic).
- *Illustrated* (the 5 original scenes) — no `type` field in the data. Hotspots are hand-drawn
  `<g class="hotspot" data-word=…>` SVG shapes inline in `index.html`, so their geometry lives in
  the markup, not the JSON.
- *Photo* (`type: "photo"`) — carries `image` and, on every word, `x/y/w/h` as percentages of the
  image. The renderer builds an `<img>` plus one absolutely-positioned `<div class="hotspot">` per
  word at runtime.

**Game modes.**
- *Esplora* — tap anything in the scene to discover its Italian name; discovered items get a
  border.
- *Ascolta e tocca* — the game names an Italian word ("Trova: …"); tap the matching item.
- *Abbina* — drag word chips from the pool at the bottom of the scene onto the matching hotspot;
  placed words get a tag with a connector line.
- *Traduci* — separate page: multiple-choice translation over the words of **all** scenes, with a
  direction toggle (Italian→English / English→Italian).

Hit-testing uses real DOM elements and CSS state classes (`learned`, `correct-flash`,
`wrong-flash`, `target-hint`), not coordinate math. Progress (discovered / identified / matched
sets and the last-used mode, per scene) lives in page memory only and resets on reload.

**Unlock rules.** Moving between scenes is always free. *Ascolta e tocca* and *Abbina* stay
locked in a scene until every word in it has been discovered in *Esplora*; hovering a locked tab
shows a bilingual tooltip.

**Content pipeline (three data files + two photo folders).**

| File / folder | Role | In git? |
|---|---|---|
| `scenes_db.json` | Permanent database of every scene ever made: `id`, `display_name`, `type`, `image`, `words` | yes |
| `manifest.txt` | Hand-edited ordered list of scene ids that are live; `#` comments hide a scene | yes |
| `scenes.json` | **Generated** by `--publish`: database filtered/ordered by the manifest, with `eyebrow = "Tappa N: " + display_name` computed from position. This is what `index.html` fetches | yes |
| `photos/` | Published images | yes (public) |
| `source-photos/` | Original photos plus `word_lists.txt` (`photo-name: item, item, …` per line) | **no** (gitignored) |

`agent/build_scenes.py` turns a photo plus a word list into a scene via one Claude vision call
(`claude-opus-5`): a tight bounding box (percent) and an Italian translation per item, plus a
suggested Italian scene title. Modes: normal add/extend, `--force <name>` / `--forceall`,
`--remove <name>`, `--publish <manifest>`, `-h`. `agent/generate_scene.py` holds the shared
`Hotspot` model and image-resize code and is also a standalone single-photo debug CLI (writes a
`_words.json` and an annotated image next to the photo).

## Decisions

**Photo scenes.** New scenes built from real trip photos should **not** try to reuse the
hand-illustrated SVG renderer — an agent can't realistically draw matching vector art. So a second
scene type exists (see above). Both types share the word data contract and the same
quiz/match/translate logic; only hotspot rendering and hit-testing differ.

**Photo hotspot overlap: smaller box on top.** Boxes from real photos routinely overlap (a cushion
nested inside an armchair; adjacent appliances with sliver overlaps) — that reflects real object
arrangement, not a detection error. Photo hotspots are flat rectangles, so only one can catch a
tap in a shared region. The renderer therefore appends hotspots **largest area first**: later DOM
siblings paint on top (no z-index in play), so the smallest/nested box ends up topmost and stays
tappable. (An early version sorted the other way and put the largest box on top.) This is a
heuristic — fine for nesting, arbitrary for two similar-sized items touching at an edge; revisit
if it causes real mis-taps. Click handling is delegated on the scene wrapper rather than attached
per element, because photo hotspots are created dynamically.

**Hover highlight.** The original 3px outline at 10% fill was nearly invisible on light objects
(a pale library shelf). Now: 5px gold outline with a 32% gold fill. Photo hotspots add a white
`box-shadow` ring for contrast on any background. A stacked `drop-shadow` halo was tried for the
SVG hotspots and removed: `drop-shadow` duplicates the whole rendered shape, including the
translucent fill, so four near-opaque copies compounded into a solid block that hid the object.

**Locked tabs use a CSS class, not `disabled`.** A natively disabled button suppresses hover
events in most browsers, so the only feedback was the OS "not-allowed" cursor. The locked tabs
keep the greyed-out look and `not-allowed` cursor via a `locked` class, which lets a custom
tooltip appear on hover; clicks are ignored in JS while locked.

**Match mode auto-scrolls near the viewport edges.** On tall photo scenes the chip pool (bottom)
and a target hotspot (top) can't both be on screen. Holding a dragged chip within ~70px of the top
or bottom edge scrolls the page (a `requestAnimationFrame` loop, up to 16px/frame, proportional to
closeness), so the chip and its target can both be reached in one drag.

**Hosting: GitHub Pages from a public repo.** Chosen so updates don't mean re-transferring files
to every device and there's nothing to run or pay for. Free GitHub Pages requires a public repo,
so everything in the repo — including `photos/` — is publicly viewable. See "Photo privacy" and
"Not done yet".

**Generation uses the Anthropic API only from the local script.** The key lives in `.env`
(gitignored) and never reaches a browser. A browser "New scene" form that merely packaged a photo
and word list into a command for the script was built, then removed once `build_scenes.py`
automated the whole pipeline.

**Box detection is a single shot; no crop-and-verify loop.** One request — the photo plus item
names, structured output via `client.messages.parse()` — located 18/18 items across the first three
test photos, including crowded objects. Prompting notes: (1) when an item has multiple instances
(several lemons in a bowl), tell the model to box **one** instance, or touching instances (a
banana bunch) get boxed as one cluster; (2) source resolution doesn't matter because coordinates
are percentages, so photos are downscaled to 1024px before sending (saves tokens, no accuracy
cost).

**Intermittent empty results on photos with people.** When a request localized a child and their
clothing, the model occasionally returned a validly-shaped but empty `hotspots: []` with no refusal
reason; immediate reruns succeeded. Likely cause: extra caution from safety classifiers when asked
to localize a minor's body or clothing, behaving probabilistically — not a problem with the photo
or request. The scripts never fail silently: they check `stop_reason` for a refusal and warn loudly
on empty or partial results, and `build_scenes.py` now retries automatically (up to 3 attempts)
before reporting the line as failed.

**Detection results are validated.** Every box must be a percentage (0–100). One real run for a
photo returned pixel coordinates instead (e.g. `h: 910`), which saved cleanly but rendered
hotspots hundreds of percent off-image. Out-of-range boxes are now discarded and treated like a
missing item, so they trigger a retry instead of landing on disk.

**Items need not be nouns.** The prompt tells the model that directions, actions and pronouns
(e.g. "go straight" → "vai dritto", "me" → "io") have no article: `article` stays empty and `id`
equals `it`. This was safe to add because nothing in the game reads `article`; the decision is left
to the model per item rather than coded as a rule. Because existing words are matched **by English
name**, two items that would share a label must be disambiguated in the word list (the family-tree
image's two "COUSIN"s became "boy cousin" / "girl cousin", which also gets the Italian genders
right).

**Data loading: assume online, fail loudly.** Scene data is loaded via `fetch()` instead of being
inlined in the HTML, so editing scenes never means editing a 2000-line file. There is **no
offline/local fallback**: the page assumes it is served over http(s) with `scenes.json` beside it.
If the fetch fails, the page replaces itself with a clear bilingual error message rather than
rendering a blank or broken game. Deliberate scope cut — revisit if true offline support is wanted
(service worker or an inline fallback copy). Locally, serve over http, never `file://`.

**Database vs. published site: three files instead of one.** `scenes.json` used to do two
unrelated jobs — "every scene ever generated" and "what's live, in what order." An early
`build_scenes.py` kept them in sync by treating `word_lists.txt` as the single source of truth,
deleting any scene whose line was missing and reordering to match the file. That was the wrong
call: destructive by default (running it against a partial word list to fix one scene silently
wiped every other scene), and it conflated "not generating this right now" with "don't want this
anymore", losing real generated data (translations, hand-checked boxes).

The fix is three files with one job each: `scenes_db.json` is the permanent database (normal runs
only ever add or extend; a scene absent from the word list is left alone; array order is
cosmetic); `manifest.txt` is the hand-edited, ordered list of what is live (curating the site is an
editorial choice, so it is deliberately not automated); `scenes.json` is generated by `--publish`.
If the manifest names an id the database lacks, publish aborts and writes nothing, listing every
missing id — a bad manifest must never silently produce a half-broken site. `--remove` permanently
deletes from the database and is distinct from hiding a scene via the manifest.

**Scene `id` = photo filename stem, forever; `display_name` is the in-game title.** Ids were first
derived from the model's Italian scene title; they now equal the photo's filename stem so the
word-list line, the photo file and the manifest entry all share one key. `display_name` (the
Italian title, defaulting to the model's suggestion) is a separate field so it can change without
touching any matching logic; a force refresh leaves it alone. "Tappa N" is no longer stored — it is
computed at publish time from manifest position. Renaming `display_name` via the CLI is not built
yet.

**Photo privacy.** The repo is public, so originals stay in the gitignored `source-photos/` and
only reviewed copies go into `photos/`. Photos of children are published only with faces covered
(`pool-2` has emoji baked into the image file — JPEG is a flat raster, so nothing underneath
survives). `.env` is gitignored.

## Not done yet

- **Private hosting.** Under consideration: a Cloudflare Worker serving the static files
  (`*.workers.dev`, which isn't indexed or listed) and a private GitHub repo. The goal is "not
  publicly discoverable", not a login wall. Trade-offs: deploys become a manual `wrangler deploy`
  unless GitHub Actions is set up; the URL changes; making only the repo private would *not* hide
  the site, since Pages stays public on a free plan.
- **Installable phone app (PWA):** web app manifest, a minimal service worker and icons. Android
  Chrome offers an install prompt; iOS needs Share → Add to Home Screen. Full offline caching would
  reverse the "assume online" decision.
- **Saving progress between visits** (e.g. `localStorage`) — progress is in memory only today.
- **CLI to rename `display_name`** — the field split already leaves room for it.
- **Adding scenes from a phone with no laptop** — deferred; would need the API call to run
  somewhere with the key kept server-side.
- **API cost tuning.** Detection calls use the model's defaults (no `thinking` or effort settings);
  lowering effort may cut cost and latency for this fairly simple task. Untested.
- **Back up `source-photos/`** — gitignored, so it exists only on the owner's Mac.
- **Revisit the overlap heuristic** if real mis-taps show up.
