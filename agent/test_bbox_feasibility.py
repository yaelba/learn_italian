"""Isolated feasibility test: given a photo and a list of item names,
can the model localize each one as a bounding box accurately enough
to use as a hotspot region?

Usage: python test_bbox_feasibility.py <photo_path> <item1> <item2> ...
"""
import base64
import io
import sys

import anthropic
from dotenv import load_dotenv
from PIL import Image, ImageDraw
from pydantic import BaseModel

load_dotenv()

MAX_DIMENSION = 1024  # phone photos are far larger than needed; downscale to save tokens


class Hotspot(BaseModel):
    id: str
    x: float  # % of image width, left edge of box
    y: float  # % of image height, top edge of box
    w: float  # % of image width
    h: float  # % of image height


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
                    "Locate each of the following items in the photo. For each one, give a tight "
                    "bounding box as percentages of the image width/height (0-100). The origin (0,0) "
                    "is the top-left corner of the image; x increases rightward, y increases downward. "
                    "x,y is the box's top-left corner; w,h is its width/height.\n\n"
                    "If multiple instances of an item appear in the photo (e.g. several bananas in a "
                    "bunch, several lemons in a bowl), pick ONE single representative instance and draw "
                    "the tightest possible box around just that one instance. Never box a whole cluster "
                    "or group of instances together, even if they visually overlap or touch each other.\n\n"
                    f"Items:\n{items_list}"
                )},
            ],
        }],
        output_format=DetectionResult,
    )
    return response.parsed_output


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
        draw.text((left + 4, top + 4), hs.id, fill=color)
    img.save(out_path)


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <photo_path> <item1> <item2> ...")
        sys.exit(1)

    photo_path = sys.argv[1]
    items = sys.argv[2:]

    client = anthropic.Anthropic()
    image_bytes = load_and_resize(photo_path)
    result = detect_hotspots(client, image_bytes, items)

    for hs in result.hotspots:
        print(hs)

    out_path = photo_path.rsplit(".", 1)[0] + "_annotated.jpeg"
    draw_boxes(photo_path, result, out_path)
    print(f"\nSaved annotated image to {out_path}")


if __name__ == "__main__":
    main()
