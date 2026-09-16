"""
Fix Episode 2 - Regenerate missing scenes 2 & 5, animate, rebuild video, add BGM.
"""

import os
import json
import time
import requests
import fal_client
from pathlib import Path
from config import IMAGES_DIR, SCRIPTS_DIR, VIDEO_DIR, AUDIO_DIR

# ── Setup ────────────────────────────────────────────────────────────────────
fal_key = os.environ.get("FAL_KEY")
if not fal_key:
    raise ValueError("FAL_KEY not set")
fal_client.api_key = fal_key

EPISODE = 2
ep_img_dir = IMAGES_DIR / f"ep{EPISODE}"
clip_dir = ep_img_dir / "clips"
clip_dir.mkdir(parents=True, exist_ok=True)

# Load script
with open(SCRIPTS_DIR / f"ep{EPISODE}_script.json") as f:
    script = json.load(f)

# ── Step 1: Regenerate images for scenes 2 and 5 with softened prompts ────
# The originals may have tripped safety filters. Use simplified descriptions.
SOFTENED_PROMPTS = {
    2: (
        "3D Pixar-style CGI render of a cute cartoon celery character wearing "
        "a big white chef hat tilted over one eye. Bright colorful kitchen "
        "background with warm lighting, playful expression."
    ),
    5: (
        "3D Pixar-style CGI render of a friendly cartoon potato character "
        "sitting calmly in a small booth. Gentle smile, warm soft lighting, "
        "cozy background."
    ),
}

IMAGE_MODEL = "fal-ai/flux-2-pro"
IMAGE_SIZE = {"width": 768, "height": 1344}

print("=" * 60)
print("STEP 1: Regenerate missing images (scenes 2 & 5)")
print("=" * 60)

for scene_num, prompt in SOFTENED_PROMPTS.items():
    img_path = ep_img_dir / f"scene_{scene_num:02d}.png"

    # Remove old image if it exists (force regenerate)
    if img_path.exists():
        img_path.unlink()
        print(f"  Removed old scene {scene_num} image")

    print(f"\n  Generating scene {scene_num}...")
    print(f"  Prompt: {prompt[:80]}...")

    for attempt in range(3):
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
                print(f"  Saved: {img_path}")
                break
            else:
                print(f"  No images in response (attempt {attempt + 1})")

        except Exception as e:
            print(f"  Error attempt {attempt + 1}: {e}")
            if attempt < 2:
                time.sleep(8)
    else:
        print(f"  FAILED scene {scene_num} after 3 attempts!")

# ── Step 2: Animate scenes 2 and 5 with Kling ────────────────────────────
VIDEO_MODEL = "fal-ai/kling-video/v2.1/standard/image-to-video"

print("\n" + "=" * 60)
print("STEP 2: Animate scenes 2 & 5 with Kling")
print("=" * 60)

for scene_num in [2, 5]:
    img_path = ep_img_dir / f"scene_{scene_num:02d}.png"
    clip_path = clip_dir / f"scene_{scene_num:02d}.mp4"

    if not img_path.exists():
        print(f"  Skip scene {scene_num} - no image to animate")
        continue

    # Remove old clip to force regeneration
    if clip_path.exists():
        clip_path.unlink()
        print(f"  Removed old scene {scene_num} clip")

    # Get animation prompt from script
    scene_data = next(s for s in script["scenes"] if s["scene_number"] == scene_num)
    motion = scene_data.get("animation_prompt", "Gentle character movement with subtle camera motion.")

    print(f"\n  Animating scene {scene_num}...")
    print(f"  Motion: {motion[:70]}...")

    for attempt in range(3):
        try:
            image_url = fal_client.upload_file(str(img_path))

            result = fal_client.subscribe(
                VIDEO_MODEL,
                arguments={
                    "prompt": motion,
                    "image_url": image_url,
                    "duration": "5",
                    "aspect_ratio": "9:16",
                },
            )

            if "video" in result and result["video"].get("url"):
                video_data = requests.get(result["video"]["url"]).content
                clip_path.write_bytes(video_data)
                print(f"  Saved: {clip_path}")
                break
            else:
                print(f"  No video in response (attempt {attempt + 1})")

        except Exception as e:
            print(f"  Error attempt {attempt + 1}: {e}")
            if attempt < 2:
                print(f"  Retrying in 10s...")
                time.sleep(10)
    else:
        print(f"  FAILED to animate scene {scene_num}!")

# ── Step 3: Rebuild ep2_final.mp4 with all 12 scenes ─────────────────────
print("\n" + "=" * 60)
print("STEP 3: Rebuild ep2_final.mp4 with all 12 scenes")
print("=" * 60)

from video_assembler import assemble_video
final_video = assemble_video(EPISODE, script)
print(f"\n  Final video: {final_video}")

# ── Step 4: Generate BGM and mix it in ───────────────────────────────────
print("\n" + "=" * 60)
print("STEP 4: Generate BGM and mix into final video")
print("=" * 60)

from bgm_generator import generate_bgm, mix_bgm_with_video

bgm_path = generate_bgm(EPISODE, style="default")

if bgm_path and final_video:
    # Save version without BGM
    no_bgm_path = VIDEO_DIR / f"ep{EPISODE}_final_no_bgm.mp4"
    if not no_bgm_path.exists():
        import shutil
        shutil.copy2(final_video, str(no_bgm_path))
        print(f"  Saved no-BGM version: {no_bgm_path}")

    # Mix BGM into the final video (overwrite)
    mixed = mix_bgm_with_video(final_video, bgm_path, final_video)
    print(f"\n  Final video with BGM: {mixed}")
else:
    print("  Skipping BGM mix (missing video or BGM)")

print("\n" + "=" * 60)
print("DONE!")
print("=" * 60)
