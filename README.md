# Il Passaporto Italiano

An Italian vocabulary game built around a family trip to Italy. Each scene is an image with
tappable items; tap to learn the Italian word, then practise with a listening quiz, a drag-and-match
game, and a cross-scene translation quiz. The game is a single static page (`index.html`); scenes
are generated from photos by a small Python script that uses the Anthropic API.

For the architecture and the reasoning behind it, see [`DESIGN.md`](DESIGN.md).

## Play it locally

The page loads its scenes with `fetch()`, so open it over http (not by double-clicking the file):

```bash
python3 -m http.server 8000
```

Then visit <http://localhost:8000/>. After changing data, hard-refresh the browser (Cmd+Shift+R)
because it caches `scenes.json` and photos.

## What's in the repo

| Path | What it is |
|---|---|
| `index.html` | The whole game |
| `scenes_db.json` | Permanent database of every scene made |
| `manifest.txt` | Ordered list of which scenes are live (`#` hides a line) |
| `scenes.json` | Generated from the two above by `--publish`; what the game loads |
| `photos/` | Published images |
| `agent/` | `build_scenes.py` (the pipeline) and `generate_scene.py` (shared code) |
| `source-photos/` | Original photos and `word_lists.txt` — **not in git**, local only |

## One-time setup

```bash
conda env create -f environment.yml
conda activate learn_italian
```

Create a file named `.env` in the repo root containing your Anthropic API key as
`ANTHROPIC_API_KEY=...`. It is gitignored; never commit it.

## Add a scene

1. Put the photo in `source-photos/` (e.g. `kitchen-3.jpg`). Its name without the extension is the
   scene's permanent id.
2. Add a line to `source-photos/word_lists.txt`: `kitchen-3: kettle, toaster, bowl`. Use plain
   English; two items that would share a label need distinct names (e.g. "boy cousin" / "girl
   cousin").
3. From the repo root, generate it (this calls the API and costs a little):
   ```bash
   python agent/build_scenes.py source-photos/word_lists.txt
   ```
   Lines that haven't changed are skipped without an API call.
4. Add `kitchen-3` to `manifest.txt` wherever it should appear, then rebuild the live file:
   ```bash
   python agent/build_scenes.py --publish manifest.txt
   ```
5. Check it in the browser, then commit and push — GitHub Pages serves the repo, so a push to
   `main` updates the live site.

## Other operations

```bash
python agent/build_scenes.py --force <photo-name> source-photos/word_lists.txt   # redo one scene
python agent/build_scenes.py --forceall source-photos/word_lists.txt             # redo every line
python agent/build_scenes.py --remove <photo-name>      # permanently delete from the database
python agent/build_scenes.py -h                         # full help
```

To hide a scene without losing its data, put a `#` in front of its line in `manifest.txt` and
publish again.

## Troubleshooting

- **A change doesn't show up in the browser:** hard-refresh (Cmd+Shift+R) or use a private window.
- **`--publish` says ids have no matching scene:** the manifest names an id that isn't in
  `scenes_db.json`; fix the typo or the manifest. Nothing is written until it passes.
- **A scene came back with missing or odd boxes:** rerun it with `--force <photo-name>`. Results
  with out-of-range coordinates are retried automatically.
- **`git push` fails with HTTP 400:** `git -c http.postBuffer=524288000 push origin main`.
- **Before committing photos:** make sure no real person's face — especially a child's — is
  visible. The repo is public.
