"""
Image Generator - Generates scene images via Fal.ai Flux 2 Pro.
Includes retry logic and safety-aware prompt handling.
"""

import os
import json
import time
import requests
import fal_client
from pathlib import Path
from config import IMAGES_DIR, IMAGE_MODEL, IMAGE_SIZE

MAX_RETRIES = 3
RETRY_DELAY = 8  # seconds

# Words that trigger safety filters — map to safe synonyms
PROMPT_SANITIZE_MAP = {
    "sweat": "glistening",
    "yelling": "speaking loudly",
    "angrily": "intensely",
    "accusingly": "dramatically",
    "anxious": "worried",
    "trembling": "shaking slightly",
    "agape": "open wide",
    "fury": "intense",
    "furious": "intense",
}


def sanitize_prompt(prompt: str) -> str:
    """Replace trigger words that cause safety filter rejections."""
    import re
    result = prompt
    for word, replacement in PROMPT_SANITIZE_MAP.items():
        result = re.sub(rf'\b{re.escape(word)}\b', replacement, result, flags=re.IGNORECASE)
    return result


def generate_images(episode_num, script=None):
    """Generate images for all scenes with retry logic."""
    fal_key = os.environ.get("FAL_KEY")
    if not fal_key:
        raise ValueError("FAL_KEY not set")
    fal_client.api_key = fal_key

    if script is None:
        from config import SCRIPTS_DIR
        p = SCRIPTS_DIR / f"ep{episode_num}_script.json"
        if not p.exists():
            raise FileNotFoundError(f"No script at {p}")
        with open(p) as f:
            script = json.load(f)

    ep_dir = IMAGES_DIR / f"ep{episode_num}"
    ep_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    failed = []

    for scene in script["scenes"]:
        sn = scene["scene_number"]
        img_path = ep_dir / f"scene_{sn:02d}.png"

        if img_path.exists():
            print(f"   skip scene {sn}")
            generated.append(str(img_path))
            continue

        prompt = sanitize_prompt(scene["image_prompt"])
        print(f"   generating scene {sn}/{len(script['scenes'])}...")

        success = False
        for attempt in range(MAX_RETRIES):
            try:
                result = fal_client.subscribe(
                    IMAGE_MODEL,
                    arguments={
                        "prompt": prompt,
                        "image_size": IMAGE_SIZE,
                        "num_images": 1,
                        "num_inference_steps": 4,
                        "enable_safety_checker": False,
                        "safety_tolerance": "5",
                    },
                )

                if "images" in result and len(result["images"]) > 0:
                    img_data = requests.get(result["images"][0]["url"]).content
                    img_path.write_bytes(img_data)
                    print(f"      saved: {img_path}")
                    generated.append(str(img_path))
                    success = True
                    break
                else:
                    print(f"      no images in response (attempt {attempt + 1})")

            except Exception as e:
                print(f"      error attempt {attempt + 1}: {e}")
                if attempt < MAX_RETRIES - 1:
                    print(f"      retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)

        if not success:
            failed.append(sn)
            print(f"      [FAILED] scene {sn} after {MAX_RETRIES} attempts")

    print(f"Generated {len(generated)}/{len(script['scenes'])} images")
    if failed:
        print(f"⚠️  Failed scenes: {failed}")

    return generated


if __name__ == "__main__":
    import sys
    ep = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    generate_images(ep)
