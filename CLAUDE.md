# CLAUDE.md

Il Passaporto Italiano: a personal Italian-vocabulary game for the owner's family — a static site
(one `index.html`) on GitHub Pages from a **public** repo, plus a local Python pipeline that turns
photos into scenes with the Anthropic API. The owner is new to git, GitHub and APIs: explain in
plain language, and say what a command will do before running anything with side effects.

`DESIGN.md` has the architecture, the reasoning behind each decision, and the "Not done yet"
backlog — read it before proposing design changes, and don't re-derive decisions recorded there.
`README.md` has setup and day-to-day steps.

## Files

- `index.html` — the whole game (HTML/CSS/JS, no build step). Fetches `scenes.json`.
- `scenes_db.json` — permanent scene database; the source of truth for content.
- `manifest.txt` — hand-edited ordered list of live scene ids; `#` lines are skipped. Don't edit it
  unless asked — which scenes are live is the owner's editorial call.
- `scenes.json` — **generated** by `--publish`. Never hand-edit; regenerate it.
- `photos/` — published images (committed, public).
- `source-photos/` — original photos + `word_lists.txt`. **Gitignored; exists only on the owner's
  Mac. Never commit it.**
- `agent/build_scenes.py` — the pipeline CLI (`-h` prints full help). `agent/generate_scene.py` —
  shared model and image-resize code, plus a single-photo debug CLI.
- `environment.yml` — conda env `learn_italian`. `.env` — the Anthropic API key (gitignored);
  never read, print or commit it.

## Commands (run from the repo root; paths are relative)

```bash
PY=/Users/yaelbaran/anaconda3/envs/learn_italian/bin/python3
$PY agent/build_scenes.py source-photos/word_lists.txt            # add / extend scenes
$PY agent/build_scenes.py --force <photo-name> source-photos/word_lists.txt
$PY agent/build_scenes.py --remove <photo-name>                    # delete from the database
$PY agent/build_scenes.py --publish manifest.txt                   # rebuild scenes.json
python3 -m http.server <port>                                      # serve the game locally
```

- Use the env's Python by full path: `conda activate`/`conda run` fail in Claude's shell, and bare
  `python3` lacks the `anthropic` package.
- Calls to the API cost money. Unchanged word-list lines make no call; `--force`/`--forceall` always
  do. Run only what was asked.

## Working rules

- **Never commit or push unless asked.** When asked, show what will be committed first, and ask
  again before pushing. Commit one logical change at a time (describable without "and"), with a
  message that explains why. Keep scene data/photos commits separate from code commits.
- **Hold back `photos/` and scene data until the owner has reviewed the photos.** Never publish an
  unobscured face of a real person, especially a child.
- **When the owner says "don't change anything yet" or "wait", only discuss.** After a long design
  discussion, restate the design and get a go-ahead before implementing.
- Never change git config. A large push may fail with HTTP 400; use a one-off flag instead:
  `git -c http.postBuffer=524288000 push origin main`.
- Keep temp files in the session scratchpad, not `/tmp` or elsewhere. Back up a data file before an
  operation that rewrites it, and restore it after a throwaway test. Don't search the whole
  filesystem (`find /` once touched the owner's Google Drive mount and triggered prompts).
  `~/Downloads`, Documents and Desktop are blocked by macOS — ask the owner to copy files into the
  project instead.
- The repo is public: no secrets, personal details, or account information in any committed file.

## Testing UI changes

- Serve over http from the repo root on a **fresh port each time** (`python3 -m http.server <port>`)
  and open `http://localhost:<port>/`. Never `file://` — the in-app browser shows stale snapshots
  and the page's `fetch()` needs http. Kill the server afterwards.
- The browser caches `scenes.json` and photos across tabs. A fresh port avoids false "didn't
  update" results; for the owner's own browser the fix is a hard refresh (Cmd+Shift+R).
- Check both an illustrated scene (e.g. `castello2`) and a photo scene. For game-state tests the
  scene-navigation buttons are free, but Quiz/Match tabs unlock only after all words in a scene are
  discovered.

## Data gotchas

- Box coordinates are percentages (0–100). Out-of-range boxes are rejected and retried.
- A scene's `id` equals its photo filename stem and never changes; `display_name` is the in-game
  title. Word-list lines match scenes by photo name, and existing words by **English name** — give
  items with identical labels distinct names (e.g. "boy cousin" / "girl cousin").
- Items need not be nouns; for phrases and pronouns `article` is empty and `id` equals `it`.
- Photo hotspots are appended largest-area first so the smallest ends up on top. Don't use a
  stacked `drop-shadow` halo on SVG hotspots — it renders as an opaque block.
- Quiz/Match tabs use a `locked` class, not `disabled`, so the hover tooltip works.
