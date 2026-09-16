"""
Scene Animator - Uses Kling via Fal.ai to animate still images into short video clips.
Now generates UNIQUE motion prompts per scene from script animation_prompt field.
Aspect ratio: 9:16 vertical for Shorts/TikTok.
"""

import os
import json
import time
import requests
import fal_client
from pathlib import Path
from config import IMAGES_DIR

VIDEO_MODEL = "fal-ai/kling-video/v2.1/standard/image-to-video"
CLIP_DURATION = "5"
ASPECT_RATIO = "9:16"
MAX_RETRIES = 3
RETRY_DELAY = 10  # seconds


def animate_scenes(episode_num, script=None):
    """Animate scene images into video clips with unique motion per scene."""
    fal_key = os.environ.get("FAL_KEY")
    if not fal_key:
        raise ValueError("FAL_KEY not set")
    fal_client.api_key = fal_key

    if script is None:
        from config import SCRIPTS_DIR
        p = SCRIPTS_DIR / f"ep{episode_num}_script.json"
        with open(p) as f:
            script = json.load(f)

    ep_img_dir = IMAGES_DIR / f"ep{episode_num}"
    clip_dir = IMAGES_DIR / f"ep{episode_num}" / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    failed = []

    for scene in script["scenes"]:
        sn = scene["scene_number"]
        img_path = ep_img_dir / f"scene_{sn:02d}.png"
        clip_path = clip_dir / f"scene_{sn:02d}.mp4"

        if clip_path.exists():
            print(f"   skip scene {sn} (already animated)")
            generated.append(str(clip_path))
            continue

        if not img_path.exists():
            print(f"   skip scene {sn} (no image)")
            continue

        # Get unique motion prompt from script (new system)
        motion = scene.get("animation_prompt")
        if not motion:
            # Fallback to scene-type-based generic motion
            motion = _get_fallback_motion(scene)

        print(f"   animating scene {sn}/{len(script['scenes'])}...")
        print(f"      motion: {motion[:70]}...")

        success = False
        for attempt in range(MAX_RETRIES):
            try:
                image_url = fal_client.upload_file(str(img_path))

                result = fal_client.subscribe(
                    VIDEO_MODEL,
                    arguments={
                        "prompt": motion,
                        "image_url": image_url,
                        "duration": CLIP_DURATION,
                        "aspect_ratio": ASPECT_RATIO,
                    },
                )

                if "video" in result and result["video"].get("url"):
                    video_data = requests.get(result["video"]["url"]).content
                    clip_path.write_bytes(video_data)
                    print(f"      saved: {clip_path}")
                    generated.append(str(clip_path))
                    success = True
                    break
                else:
                    print(f"      no video in response (attempt {attempt + 1})")

            except Exception as e:
                print(f"      error attempt {attempt + 1}: {e}")
                if attempt < MAX_RETRIES - 1:
                    print(f"      retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)

        if not success:
            failed.append(sn)
            print(f"      [FAILED] scene {sn} after {MAX_RETRIES} attempts")

    print(f"\nAnimated {len(generated)}/{len(script['scenes'])} scenes")
    if failed:
        print(f"⚠️  Failed scenes: {failed}")

    return generated


def _get_fallback_motion(scene: dict) -> str:
    """Generate motion prompt from scene type if animation_prompt not in script."""
    scene_type = scene.get("type", "drama")
    desc = scene.get("scene_description", "")

    # These are the bare minimum fallbacks - the script should have animation_prompt
    fallbacks = {
        "hook": f"Dramatic character movement: {desc}. Camera pushes in with slight shake.",
        "cliffhanger": f"Slow dramatic zoom into character's face, tension building. {desc}",
        "confessional": f"Character subtly shifts and blinks while speaking to camera. Gentle breathing motion.",
        "setup": f"Characters react with subtle movement. Gentle ambient kitchen motion, steam rising.",
        "drama": f"Characters gesture and emote expressively. {desc}. Kitchen environment active.",
    }

    return fallbacks.get(scene_type, fallbacks["drama"])


if __name__ == "__main__":
    import sys
    ep = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    animate_scenes(ep)
