"""
Voice Generator - Uses ElevenLabs text-to-speech via Fal.ai for character voices.

Voice assignments (ElevenLabs voices):
  George = Chef Tomatino (commanding, intense)
  River  = Celery Steve / Garlic Gary (versatile, can do nervous or scheming)
  Charlie = Narrator / Potato Pete (deep, calm, authoritative)
  Lily   = Pepper Patricia (fierce, energetic)
  Sarah  = Onion Olivia (emotional, dramatic)
"""

import os
import json
import time
import shutil
import requests
import fal_client
from pathlib import Path
from config import AUDIO_DIR

# ElevenLabs voice mapping via Fal.ai
ELEVENLABS_MODEL = "fal-ai/elevenlabs/text-to-dialogue/eleven-v3"

CHARACTER_VOICES = {
    "Narrator": {"voice": "Charlie", "style": "dramatic documentary narrator"},
    "Chef Tomatino": {"voice": "George", "style": "angry Gordon Ramsay yelling"},
    "Celery Steve": {"voice": "River", "style": "nervous trembling whisper"},
    "Potato Pete": {"voice": "Charlie", "style": "calm philosophical zen"},
    "Pepper Patricia": {"voice": "Lily", "style": "fierce sassy attitude"},
    "Onion Olivia": {"voice": "Sarah", "style": "emotional crying dramatic"},
    "Garlic Gary": {"voice": "River", "style": "quiet scheming whisper"},
}

MAX_RETRIES = 3
RETRY_DELAY = 5


def generate_voice(episode_num, script=None):
    """Generate voice audio for all scenes using ElevenLabs via Fal.ai."""
    fal_key = os.environ.get("FAL_KEY")
    if not fal_key:
        raise ValueError("FAL_KEY not set")
    fal_client.api_key = fal_key

    if script is None:
        from config import SCRIPTS_DIR
        p = SCRIPTS_DIR / f"ep{episode_num}_script.json"
        with open(p) as f:
            script = json.load(f)

    ep_dir = AUDIO_DIR / f"ep{episode_num}"
    ep_dir.mkdir(parents=True, exist_ok=True)

    generated = []

    for scene in script["scenes"]:
        sn = scene["scene_number"]
        combined_path = ep_dir / f"scene_{sn:02d}_combined.mp3"

        if combined_path.exists():
            print(f"   skip scene {sn} audio (exists)")
            generated.append(str(combined_path))
            continue

        segments = []

        if scene.get("narration"):
            segments.append(("Narrator", scene["narration"]))

        for line in scene.get("dialogue", []):
            char = line["character"]
            text = line["line"]
            if not text or text.strip() == "...":
                continue
            segments.append((char, text))

        if not segments:
            print(f"   skip scene {sn} (no dialogue)")
            continue

        scene_parts = []
        for i, (char, text) in enumerate(segments):
            part_path = ep_dir / f"scene_{sn:02d}_part_{i:02d}.mp3"

            if part_path.exists():
                scene_parts.append(str(part_path))
                continue

            voice_cfg = CHARACTER_VOICES.get(char, {"voice": "Charlie", "style": "neutral"})

            print(f"   voice scene {sn} - {char} ({voice_cfg['voice']}): {text[:50]}...")

            success = False
            for attempt in range(MAX_RETRIES):
                try:
                    result = fal_client.subscribe(
                        ELEVENLABS_MODEL,
                        arguments={
                            "inputs": [
                                {"text": text, "voice": voice_cfg["voice"]}
                            ],
                        },
                    )

                    audio_url = None
                    if isinstance(result, dict) and isinstance(result.get("audio"), dict):
                        audio_url = result["audio"].get("url")

                    if audio_url:
                        data = requests.get(audio_url).content
                        part_path.write_bytes(data)
                        scene_parts.append(str(part_path))
                        print(f"      saved: {part_path.name}")
                        success = True
                        break
                    else:
                        print(f"      no audio url (attempt {attempt + 1}): {str(result)[:150]}")

                except Exception as e:
                    print(f"      error attempt {attempt + 1}: {e}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)

        # Combine parts into one scene file
        if scene_parts:
            if len(scene_parts) == 1:
                shutil.copy2(scene_parts[0], combined_path)
            else:
                _concat_audio(scene_parts, combined_path, ep_dir, sn)

            generated.append(str(combined_path))
            print(f"   done scene {sn} audio")

    print(f"\nGenerated audio for {len(generated)} scenes")
    return generated


def _concat_audio(parts: list, output_path: Path, ep_dir: Path, scene_num: int):
    """Concatenate multiple audio parts into one file."""
    concat_file = ep_dir / f"scene_{scene_num:02d}_concat.txt"
    with open(concat_file, "w") as f:
        for sp in parts:
            f.write(f"file '{sp}'\n")

    cmd = (
        f"ffmpeg -y -f concat -safe 0 -i '{concat_file}' "
        f"-c copy '{output_path}' -loglevel error 2>/dev/null || "
        f"ffmpeg -y -f concat -safe 0 -i '{concat_file}' '{output_path}' -loglevel error"
    )
    os.system(cmd)
    concat_file.unlink(missing_ok=True)


if __name__ == "__main__":
    import sys
    ep = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    generate_voice(ep)
