"""Batch-add or extend scenes in scenes.json from a word-list file, end to end.

For each `photo-name: item1, item2, ...` line (matching the format of
test-photos/word_lists.txt):
  - If the photo has no scene yet: detects + translates every item, derives
    a scene id/eyebrow from a model-suggested Italian scene title
    (auto-numbering "Tappa N", auto-disambiguating id collisions), copies
    the photo from test-photos/ into photos/, and appends the new scene.
  - If the photo already has a scene: compares against its existing words
    (by English name) and only detects the ones that are actually new,
    appending them to that scene's words[]. Words already present are
    never re-detected or duplicated.
  - If every item in the line is already present: skipped entirely, no
    API call.

So word_lists.txt is meant to just grow over time — add new lines for new
photos, or add more items to an existing line — and re-running only ever
processes what's actually new. Retries automatically (a few times) if a
result comes back empty/partial before giving up on that line — see
brief.md's note on intermittent empty results on photos with people.

Pass -f/--force to ignore all of that and re-detect every line in the file
from scratch, even photos that already have a scene with every requested
word present. For an existing scene, the freshly detected words replace
its current words[] entirely (rather than appending), so nothing gets
duplicated.

Usage: python build_scenes.py [-f] <word_list_file>
"""
import base64
import json
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from generate_scene import Hotspot, load_and_resize

load_dotenv()

PHOTOS_SRC_DIR = Path("test-photos")
PHOTOS_DEST_DIR = Path("photos")
SCENES_JSON = Path("scenes.json")
MAX_RETRIES_ON_BAD_RESULT = 2
ARTICLES = ["l'", "lo ", "la ", "il ", "gli ", "le ", "i ", "un ", "una ", "uno "]


class SceneResult(BaseModel):
    scene_title: str  # short Italian noun phrase with article, e.g. "La Cucina"
    hotspots: list[Hotspot]


def strip_article(phrase: str) -> str:
    low = phrase.lower()
    for art in ARTICLES:
        if low.startswith(art):
            return phrase[len(art):].strip()
    return phrase.strip()


def slugify(phrase: str) -> str:
    return strip_article(phrase).lower()


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
                    "Also provide scene_title: a short Italian noun phrase (2-4 words) with its article, "
                    "naming the overall scene/room/setting shown in the whole photo (e.g. \"La Cucina\", "
                    "\"Il Soggiorno\", \"La Piscina\").\n\n"
                    f"Items:\n{items_list}"
                )},
            ],
        }],
        output_format=SceneResult,
    )


def next_tappa_number(scenes: list[dict]) -> int:
    max_n = 0
    for s in scenes:
        m = re.search(r"Tappa (\d+)", s.get("eyebrow", ""))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def unique_id(base_id: str, existing_ids: set) -> str:
    if base_id not in existing_ids:
        return base_id
    n = 2
    while f"{base_id}{n}" in existing_ids:
        n += 1
    return f"{base_id}{n}"


def main() -> None:
    args = sys.argv[1:]
    force = "-f" in args or "--force" in args
    args = [a for a in args if a not in ("-f", "--force")]

    if len(args) < 1:
        print(f"Usage: python {sys.argv[0]} [-f] <word_list_file>")
        sys.exit(1)

    entries = parse_word_list(Path(args[0]))
    if not entries:
        print("No entries found in word list file.")
        sys.exit(1)

    scenes = json.loads(SCENES_JSON.read_text(encoding="utf-8"))
    existing_ids = {s["id"] for s in scenes}

    client = anthropic.Anthropic()
    added, extended, skipped, failed = [], [], [], []

    for name, items in entries:
        existing_scene = next((s for s in scenes if Path(s.get("image", "")).stem == name), None)

        if existing_scene:
            have_en = {w["en"] for w in existing_scene["words"]}
            new_items = list(items) if force else [i for i in items if i not in have_en]
            if not new_items:
                skipped.append(name)
                print(f"[skip] {name}: no new words (scene '{existing_scene['id']}' already has all requested items)")
                continue
            label = (f"{name} (force re-detecting existing scene '{existing_scene['id']}')" if force
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
            if force:
                existing_scene["words"] = [hs.model_dump() for hs in result.hotspots]
                extended.append((name, existing_scene["id"], [hs.en for hs in result.hotspots]))
                print(f"[updated] {name}: re-detected {len(result.hotspots)} item(s) for '{existing_scene['id']}'")
            else:
                existing_scene["words"].extend([hs.model_dump() for hs in result.hotspots])
                extended.append((name, existing_scene["id"], [hs.en for hs in result.hotspots]))
                print(f"[extended] {name}: added {len(result.hotspots)} item(s) to '{existing_scene['id']}'")
            continue

        scene_id = unique_id(slugify(result.scene_title), existing_ids)
        existing_ids.add(scene_id)
        eyebrow = f"Tappa {next_tappa_number(scenes)}: {result.scene_title}"

        dest_path = PHOTOS_DEST_DIR / f"{name}{photo_path.suffix}"
        PHOTOS_DEST_DIR.mkdir(exist_ok=True)
        dest_path.write_bytes(photo_path.read_bytes())

        scenes.append({
            "id": scene_id,
            "eyebrow": eyebrow,
            "type": "photo",
            "image": f"photos/{dest_path.name}",
            "words": [hs.model_dump() for hs in result.hotspots],
        })
        added.append((name, scene_id, eyebrow))
        print(f"[added] {name} -> scene '{scene_id}' ({eyebrow})")

    SCENES_JSON.write_text(json.dumps(scenes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n=== Summary ===")
    print(f"New scenes added ({len(added)}):")
    for name, sid, eyebrow in added:
        print(f"  - {name} -> {sid} ({eyebrow})")
    print(f"Existing scenes extended ({len(extended)}):")
    for name, sid, new_en in extended:
        print(f"  - {name} ({sid}): + {', '.join(new_en)}")
    print(f"Skipped, nothing new ({len(skipped)}): {', '.join(skipped) or '-'}")
    print(f"Failed ({len(failed)}):")
    for name, reason in failed:
        print(f"  - {name}: {reason}")


if __name__ == "__main__":
    main()
