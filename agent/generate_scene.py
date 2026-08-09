"""Given a photo and a list of English item names, produce a ready-to-paste
`words` array for a scenes.json `type: 'photo'` scene entry: each item's
Italian translation (with article) and its hotspot as a percentage-based
bounding box.

Usage: python generate_scene.py <photo_path> <item1> <item2> ...
"""
import base64
import io
import json
import sys

import anthropic
from dotenv import load_dotenv
from PIL import Image, ImageDraw
from pydantic import BaseModel

load_dotenv()

MAX_DIMENSION = 1024  # phone photos are far larger than needed; downscale to save tokens


class Hotspot(BaseModel):
    id: str       # Italian noun/phrase without its leading article, e.g. "poltrona"
    article: str  # e.g. "la", "il", "lo", "le", "i", "l'", "una", "due"
    it: str       # full Italian phrase including the article, e.g. "la poltrona"
    en: str       # English gloss, matching the requested item
    x: float      # % of image width, left edge of box
    y: float      # % of image height, top edge of box
    w: float      # % of image width
    h: float      # % of image height


class DetectionResult(BaseModel):
    hotspots: list[Hotspot]


def load_and_resize(path: str) -> bytes:
    img = Image.open(path).convert("RGB")
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def detect_hotspots(client: anthropic.Anthropic, image_bytes: bytes, items: list[str]) -> DetectionResult:
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    items_list = "\n".join(f"- {item}" for item in items)
    response = client.messages.parse(
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
                    f"Items:\n{items_list}"
                )},
            ],
        }],
        output_format=DetectionResult,
    )
    return response


def draw_boxes(image_path: str, result: DetectionResult, out_path: str) -> None:
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    colors = ["red", "lime", "blue", "yellow", "magenta", "cyan", "orange", "white"]
    for i, hs in enumerate(result.hotspots):
        color = colors[i % len(colors)]
        left = hs.x / 100 * w
        top = hs.y / 100 * h
        right = left + hs.w / 100 * w
        bottom = top + hs.h / 100 * h
        draw.rectangle([left, top, right, bottom], outline=color, width=4)
        draw.text((left + 4, top + 4), f"{hs.en} / {hs.it}", fill=color)
    img.save(out_path)


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <photo_path> <item1> <item2> ...")
        sys.exit(1)

    photo_path = sys.argv[1]
    items = sys.argv[2:]

    client = anthropic.Anthropic()
    image_bytes = load_and_resize(photo_path)
    response = detect_hotspots(client, image_bytes, items)

    if response.stop_reason == "refusal":
        print("REFUSED: the model declined this request (stop_reason='refusal').")
        if response.stop_details:
            print(f"  category: {response.stop_details.category}")
            print(f"  explanation: {response.stop_details.explanation}")
        sys.exit(1)

    result = response.parsed_output
    if result is None:
        print(f"No structured output returned (stop_reason={response.stop_reason!r}). Nothing to draw.")
        sys.exit(1)

    for hs in result.hotspots:
        print(f"{hs.en:20s} -> {hs.it}")

    found_en = {hs.en for hs in result.hotspots}
    missing = [item for item in items if item not in found_en]
    if missing:
        print(f"\nWARNING: no box returned for: {', '.join(missing)}")
    if not result.hotspots:
        print("WARNING: zero hotspots returned — the annotated image will have no boxes at all. "
              "This can happen intermittently (e.g. on photos of people); try rerunning.")

    words_path = photo_path.rsplit(".", 1)[0] + "_words.json"
    with open(words_path, "w", encoding="utf-8") as f:
        json.dump([hs.model_dump() for hs in result.hotspots], f, ensure_ascii=False, indent=2)
    print(f"\nSaved words array to {words_path} — paste into scenes.json under the scene's \"words\" key.")

    out_path = photo_path.rsplit(".", 1)[0] + "_annotated.jpeg"
    draw_boxes(photo_path, result, out_path)
    print(f"Saved annotated image to {out_path}")


if __name__ == "__main__":
    main()
