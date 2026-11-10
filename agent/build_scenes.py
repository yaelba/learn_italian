"""Manage the scene database and publish it to the live scenes.json.

Two files make up the pipeline:
  - scenes_db.json: the permanent database of every scene ever generated
    or hand-authored. Grows over time; nothing here is ever reordered or
    silently removed by this script's normal add/extend mode. Each
    scene has:
      - id: permanent, = the photo's filename stem (e.g. "library-1") for
        photo scenes, or a fixed slug for the hand-authored illustrated
        scenes. Never changes — it's the key used to match word-list
        lines and manifest entries.
      - display_name: the Italian title shown to the player in-game
        (e.g. "Il Soggiorno"). Defaults to a model-suggested scene title
        when a scene is first created.
      - type, image, words: as before.
  - A manifest file (any name, you choose it) — a plain list of scene
    ids, one per line, in the order they should appear on the site.
    Blank lines and lines starting with # are ignored.

For each `photo-name: item1, item2, ...` line in a word-list file
(matching the format of source-photos/word_lists.txt):
  - If the photo has no scene yet: detects + translates every item, adds
    a new scene to the database (id = photo name, display_name = a
    model-suggested Italian title), and copies the photo from
    source-photos/ into photos/.
  - If the photo already has a scene: compares against its existing
    words (by English name) and only detects the ones that are actually
    new, appending them. Words already present are never re-detected or
    duplicated. If nothing is new, skipped entirely, no API call.
  - A scene in the database with no matching line in the file is left
    completely untouched — this command only ever adds to or extends
    the database, never removes or reorders anything.

Retries automatically (a few times) if a result comes back empty/partial,
or if any box's coordinates fall outside 0-100 (i.e. the model returned
raw pixels instead of the requested percentages) — the offending box is
discarded and treated like a missing item, so a bad response never
silently ends up on disk. See DESIGN.md's note on intermittent empty
results on photos with people.

Pass --force <photo-name> to force re-detecting just that one scene from
scratch, even if it already has every requested word. Pass --forceall to
do that for every line in the file. Either way, the freshly detected
words replace (not append to) that scene's words[], and the photo is
re-copied from source-photos/ into photos/ — so swapping in a different
photo under the same filename actually takes effect too. display_name is
left untouched by a force refresh, in case you've customized it.

Pass --remove <photo-name-or-scene-id> to permanently delete a scene
from the database. This is real deletion, not just hiding it from the
site — to do that instead, remove (or comment out) its line in your
manifest file and re-publish; the data stays in the database either way.

Pass --publish <manifest_file> to render the live scenes.json that
index.html actually fetches, from the database + that manifest: each
listed id is pulled from the database, in the manifest's order, with
its "Tappa N" eyebrow computed fresh from its position (N is 1-based).
An id in the manifest with no matching database entry aborts the publish
with an error listing every missing id — nothing is written until the
manifest is fixed.

Usage: python build_scenes.py <word_list_file>
       python build_scenes.py --force <photo-name> <word_list_file>
       python build_scenes.py --forceall <word_list_file>
       python build_scenes.py --remove <photo-name-or-scene-id>
       python build_scenes.py --publish <manifest_file>
"""
import base64
import json
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from generate_scene import Hotspot, load_and_resize

load_dotenv()

PHOTOS_SRC_DIR = Path("source-photos")
PHOTOS_DEST_DIR = Path("photos")
DB_JSON = Path("scenes_db.json")
LIVE_SCENES_JSON = Path("scenes.json")
MAX_RETRIES_ON_BAD_RESULT = 2


class SceneResult(BaseModel):
    scene_title: str  # short Italian noun phrase with article, e.g. "La Cucina"
    hotspots: list[Hotspot]


def parse_word_list(path: Path) -> list[tuple[str, list[str]]]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip().rstrip("'").strip()
        if not line or ":" not in line:
            continue
        name, items_str = line.split(":", 1)
        items = [i.strip() for i in items_str.split(",") if i.strip()]
        if items:
            entries.append((name.strip(), items))
    return entries


def parse_manifest(path: Path) -> list[str]:
    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ids.append(line)
    return ids


def find_photo_file(name: str) -> Path | None:
    for ext in (".jpeg", ".jpg", ".png"):
        p = PHOTOS_SRC_DIR / f"{name}{ext}"
        if p.exists():
            return p
    return None


def detect_scene(client: anthropic.Anthropic, image_bytes: bytes, items: list[str]):
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    items_list = "\n".join(f"- {item}" for item in items)
    return client.messages.parse(
        model="claude-opus-5",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": (
                    "Locate each of the following items in the photo, and translate each one to Italian. "
                    "For each item, give a tight bounding box as percentages of the image width/height "
                    "(0-100). The origin (0,0) is the top-left corner of the image; x increases rightward, "
                    "y increases downward. x,y is the box's top-left corner; w,h is its width/height.\n\n"
                    "If multiple instances of an item appear in the photo (e.g. several bananas in a "
                    "bunch, several lemons in a bowl), pick ONE single representative instance and draw "
                    "the tightest possible box around just that one instance. Never box a whole cluster "
                    "or group of instances together, even if they visually overlap or touch each other.\n\n"
                    "For each item also provide:\n"
                    "- en: the English name, matching the requested item below\n"
                    "- it: the Italian translation including its article (e.g. \"la torre\")\n"
                    "- article: just the article alone (e.g. \"la\")\n"
                    "- id: the Italian noun/phrase from 'it' with the leading article removed "
                    "(e.g. \"la torre\" -> \"torre\"; \"l'albero\" -> \"albero\")\n\n"
                    "Not every item is a simple noun — some may be directions, actions, or other "
                    "phrases with no natural article (e.g. \"go straight\" -> \"vai dritto\"). In "
                    "that case, leave article as an empty string and set id equal to it verbatim. "
                    "Never force an article onto a phrase that doesn't take one.\n\n"
                    "Also provide scene_title: a short Italian noun phrase (2-4 words) with its article, "
                    "naming the overall scene/room/setting shown in the whole photo (e.g. \"La Cucina\", "
                    "\"Il Soggiorno\", \"La Piscina\").\n\n"
                    f"Items:\n{items_list}"
                )},
            ],
        }],
        output_format=SceneResult,
    )


def is_valid_pct_box(hs: Hotspot) -> bool:
    """A well-formed box is a percentage of the image (0-100), not a raw
    pixel coordinate — guards against the occasional bad response where the
    model returns pixel values instead (e.g. w=258, h=910)."""
    return all(-1 <= v <= 101 for v in (hs.x, hs.y, hs.w, hs.h)) and hs.w > 0 and hs.h > 0


def unique_id(base_id: str, existing_ids: set) -> str:
    if base_id not in existing_ids:
        return base_id
    n = 2
    while f"{base_id}{n}" in existing_ids:
        n += 1
    return f"{base_id}{n}"


def load_db() -> list[dict]:
    return json.loads(DB_JSON.read_text(encoding="utf-8"))


def save_db(scenes: list[dict]) -> None:
    DB_JSON.write_text(json.dumps(scenes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_scene(target: str) -> None:
    scenes = load_db()
    match = next(
        (s for s in scenes if s.get("id") == target or Path(s.get("image", "")).stem == target),
        None,
    )
    if not match:
        print(f"No scene found matching '{target}' (checked scene id and photo filename).")
        sys.exit(1)

    scenes.remove(match)
    save_db(scenes)

    print(f"Removed scene '{match['id']}' ({match.get('display_name', '')}) from {DB_JSON}.")
    photo = match.get("image", "")
    if photo:
        print(f"Note: {photo} was NOT deleted, nor was any matching file under {PHOTOS_SRC_DIR}/ — "
              f"remove those manually if you no longer need them.")
    print("If this id is still listed in a manifest file, remove it from there too — the next "
          "--publish using that manifest will otherwise fail with a missing-id error.")


def publish(manifest_path: Path) -> None:
    scenes = load_db()
    by_id = {s["id"]: s for s in scenes}
    ids = parse_manifest(manifest_path)

    if not ids:
        print(f"No scene ids found in {manifest_path}.")
        sys.exit(1)

    published = []
    missing = []
    for i, scene_id in enumerate(ids, start=1):
        scene = by_id.get(scene_id)
        if not scene:
            missing.append(scene_id)
            continue
        out = dict(scene)
        out["eyebrow"] = f"Tappa {i}: {scene.get('display_name', scene_id)}"
        del out["display_name"]
        published.append(out)

    if missing:
        print(f"[fail] {len(missing)} id(s) in {manifest_path} have no matching scene in {DB_JSON}: "
              f"{', '.join(missing)}")
        print("Nothing was published. Fix the manifest or the database, then try again.")
        sys.exit(1)

    LIVE_SCENES_JSON.write_text(json.dumps(published, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Published {len(published)} scene(s) from {DB_JSON} to {LIVE_SCENES_JSON}, ordered by {manifest_path}.")


def main() -> None:
    args = sys.argv[1:]

    if "-h" in args or "--help" in args:
        print(__doc__)
        return

    if "--remove" in args:
        idx = args.index("--remove")
        if idx + 1 >= len(args):
            print(f"Usage: python {sys.argv[0]} --remove <photo-name-or-scene-id>")
            sys.exit(1)
        remove_scene(args[idx + 1])
        return

    if "--publish" in args:
        idx = args.index("--publish")
        if idx + 1 >= len(args):
            print(f"Usage: python {sys.argv[0]} --publish <manifest_file>")
            sys.exit(1)
        publish(Path(args[idx + 1]))
        return

    force_all = "--forceall" in args
    args = [a for a in args if a != "--forceall"]

    force_target = None
    if "--force" in args:
        idx = args.index("--force")
        if idx + 1 >= len(args):
            print(f"Usage: python {sys.argv[0]} --force <photo-name> <word_list_file>")
            sys.exit(1)
        force_target = args[idx + 1]
        del args[idx:idx + 2]

    if len(args) < 1:
        print(f"Usage: python {sys.argv[0]} <word_list_file>\n"
              f"       python {sys.argv[0]} --force <photo-name> <word_list_file>\n"
              f"       python {sys.argv[0]} --forceall <word_list_file>\n"
              f"       python {sys.argv[0]} --remove <photo-name-or-scene-id>\n"
              f"       python {sys.argv[0]} --publish <manifest_file>\n"
              f"Run with -h/--help for the full explanation.")
        sys.exit(1)

    entries = parse_word_list(Path(args[0]))
    if not entries:
        print("No entries found in word list file.")
        sys.exit(1)

    scenes = load_db()
    used_ids = {s["id"] for s in scenes}

    client = anthropic.Anthropic()
    added, extended, skipped, failed = [], [], [], []

    for name, items in entries:
        existing_scene = next((s for s in scenes if Path(s.get("image", "")).stem == name), None)
        force_this = force_all or name == force_target

        if existing_scene:
            have_en = {w["en"] for w in existing_scene["words"]}
            new_items = list(items) if force_this else [i for i in items if i not in have_en]
            if not new_items:
                skipped.append(name)
                print(f"[skip] {name}: no new words (scene '{existing_scene['id']}' already has all requested items)")
                continue
            label = (f"{name} (force re-detecting existing scene '{existing_scene['id']}')" if force_this
                      else f"{name} (adding to existing scene '{existing_scene['id']}')")
        else:
            new_items = items
            label = name

        photo_path = find_photo_file(name)
        if not photo_path:
            failed.append((name, "photo file not found"))
            print(f"[fail] {name}: no matching file in {PHOTOS_SRC_DIR}/")
            continue

        print(f"\n=== {label}: {', '.join(new_items)} ===")
        image_bytes = load_and_resize(str(photo_path))

        result = None
        for attempt in range(1, MAX_RETRIES_ON_BAD_RESULT + 2):
            response = detect_scene(client, image_bytes, new_items)
            if response.stop_reason == "refusal":
                print(f"  attempt {attempt}: REFUSED "
                      f"({response.stop_details.category if response.stop_details else '?'})")
                continue
            parsed = response.parsed_output
            if parsed is None or not parsed.hotspots:
                print(f"  attempt {attempt}: empty result")
                continue

            valid = [h for h in parsed.hotspots if is_valid_pct_box(h)]
            invalid = [h for h in parsed.hotspots if h not in valid]
            if invalid:
                bad = ", ".join(f"{h.en} (x={h.x:.0f} y={h.y:.0f} w={h.w:.0f} h={h.h:.0f})" for h in invalid)
                print(f"  attempt {attempt}: discarding out-of-range box(es): {bad}")
            parsed.hotspots = valid
            if not parsed.hotspots:
                print(f"  attempt {attempt}: no valid boxes left after filtering")
                continue

            missing = [i for i in new_items if i not in {h.en for h in parsed.hotspots}]
            result = parsed  # keep as a fallback even if incomplete
            if missing:
                print(f"  attempt {attempt}: missing {missing}")
                continue
            break  # complete result, stop retrying

        if result is None:
            failed.append((name, "no usable result after retries"))
            print(f"[fail] {name}: giving up after retries")
            continue

        for hs in result.hotspots:
            print(f"  {hs.en:20s} -> {hs.it}")

        if existing_scene:
            if force_this:
                existing_scene["words"] = [hs.model_dump() for hs in result.hotspots]

                PHOTOS_DEST_DIR.mkdir(exist_ok=True)
                old_dest_path = PHOTOS_DEST_DIR / Path(existing_scene.get("image", "")).name
                new_dest_path = PHOTOS_DEST_DIR / f"{name}{photo_path.suffix}"
                new_dest_path.write_bytes(photo_path.read_bytes())
                if old_dest_path != new_dest_path and old_dest_path.exists():
                    old_dest_path.unlink()
                existing_scene["image"] = f"photos/{new_dest_path.name}"

                extended.append((name, existing_scene["id"], [hs.en for hs in result.hotspots]))
                print(f"[updated] {name}: re-detected {len(result.hotspots)} item(s) and refreshed "
                      f"the photo for '{existing_scene['id']}'")
            else:
                existing_scene["words"].extend([hs.model_dump() for hs in result.hotspots])
                extended.append((name, existing_scene["id"], [hs.en for hs in result.hotspots]))
                print(f"[extended] {name}: added {len(result.hotspots)} item(s) to '{existing_scene['id']}'")
            continue

        scene_id = unique_id(name, used_ids)
        used_ids.add(scene_id)

        dest_path = PHOTOS_DEST_DIR / f"{name}{photo_path.suffix}"
        PHOTOS_DEST_DIR.mkdir(exist_ok=True)
        dest_path.write_bytes(photo_path.read_bytes())

        scenes.append({
            "id": scene_id,
            "display_name": result.scene_title,
            "type": "photo",
            "image": f"photos/{dest_path.name}",
            "words": [hs.model_dump() for hs in result.hotspots],
        })
        added.append((name, scene_id, result.scene_title))
        print(f"[added] {name} -> scene '{scene_id}' ({result.scene_title})")

    save_db(scenes)

    print("\n=== Summary ===")
    print(f"New scenes added ({len(added)}):")
    for name, sid, title in added:
        print(f"  - {name} -> {sid} ({title})")
    print(f"Existing scenes extended ({len(extended)}):")
    for name, sid, new_en in extended:
        print(f"  - {name} ({sid}): + {', '.join(new_en)}")
    print(f"Skipped, nothing new ({len(skipped)}): {', '.join(skipped) or '-'}")
    print(f"Failed ({len(failed)}):")
    for name, reason in failed:
        print(f"  - {name}: {reason}")


if __name__ == "__main__":
    main()
