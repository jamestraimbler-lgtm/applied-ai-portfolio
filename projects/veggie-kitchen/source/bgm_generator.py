"""
BGM Generator - Generates background music using CassetteAI via Fal.ai.
Produces 60-90 second dramatic/comedic background music for episodes.
Mixes BGM at 18% volume under the voice track.
"""

import os
import json
import time
import subprocess
import requests
import fal_client
from pathlib import Path
from config import AUDIO_DIR, VIDEO_DIR

CASSETTEAI_MODEL = "fal-ai/minimax-music/v2.5"
MAX_RETRIES = 3
BGM_VOLUME = 0.18  # 18% volume for BGM under dialogue


# BGM style prompts per episode mood
BGM_STYLES = {
    "default": (
        "Dramatic reality TV competition music, tense strings, "
        "comedic undertone, building intensity, orchestral with modern beats, "
        "cooking show background music, slightly absurd, 60 seconds"
    ),
    "intense": (
        "High-tension reality TV elimination music, dramatic drums, "
        "suspenseful strings, building to climax, cooking competition drama, "
        "heart-pounding decision moment, 60 seconds"
    ),
    "comedic": (
        "Comedic reality TV music, playful pizzicato strings, silly tuba, "
        "exaggerated dramatic stings, cooking show parody background, "
        "lighthearted chaos energy, 60 seconds"
    ),
    "emotional": (
        "Emotional reality TV confession music, soft piano, gentle strings, "
        "bittersweet melody, character backstory moment, heartfelt cooking "
        "competition music, 60 seconds"
    ),
}


def generate_bgm(episode_num: int, style: str = "default") -> str:
    """Generate background music for an episode using CassetteAI.

    Returns path to generated BGM audio file, or None on failure.
    """
    fal_key = os.environ.get("FAL_KEY")
    if not fal_key:
        raise ValueError("FAL_KEY not set")
    fal_client.api_key = fal_key

    ep_audio_dir = AUDIO_DIR / f"ep{episode_num}"
    ep_audio_dir.mkdir(parents=True, exist_ok=True)
    bgm_path = ep_audio_dir / "bgm.mp3"

    if bgm_path.exists():
        print(f"   skip BGM generation (exists)")
        return str(bgm_path)

    prompt = BGM_STYLES.get(style, BGM_STYLES["default"])
    print(f"   Generating BGM ({style} style)...")

    for attempt in range(MAX_RETRIES):
        try:
            result = fal_client.subscribe(
                CASSETTEAI_MODEL,
                arguments={
                    "prompt": prompt,
                    "is_instrumental": True,
                },
            )

            # Handle various response structures
            audio_url = None
            if isinstance(result, dict):
                if isinstance(result.get("audio"), dict):
                    audio_url = result["audio"].get("url")
                elif isinstance(result.get("audio"), str):
                    audio_url = result["audio"]
                elif result.get("audio_file"):
                    if isinstance(result["audio_file"], dict):
                        audio_url = result["audio_file"].get("url")
                    else:
                        audio_url = result["audio_file"]
                elif result.get("output"):
                    if isinstance(result["output"], dict):
                        audio_url = result["output"].get("url")
                    else:
                        audio_url = result["output"]

            if audio_url:
                data = requests.get(audio_url).content
                bgm_path.write_bytes(data)
                print(f"   BGM saved: {bgm_path}")
                return str(bgm_path)
            else:
                print(f"   No audio URL in response (attempt {attempt + 1}): {str(result)[:200]}")

        except Exception as e:
            print(f"   BGM error (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(10)

    print(f"   ⚠️  BGM generation failed after {MAX_RETRIES} attempts")
    return None


def mix_bgm_with_video(video_path: str, bgm_path: str, output_path: str = None) -> str:
    """Mix BGM at 18% volume under the existing video audio.

    Takes the final video and adds BGM underneath the dialogue/narration.
    """
    if not output_path:
        p = Path(video_path)
        output_path = str(p.parent / f"{p.stem}_with_bgm{p.suffix}")

    if Path(output_path).exists() and output_path != video_path:
        print(f"   skip BGM mix (already exists)")
        return output_path

    print(f"   Mixing BGM at {int(BGM_VOLUME * 100)}% volume...")

    # Get video duration
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    try:
        video_duration = float(result.stdout.strip())
    except ValueError:
        video_duration = 60.0

    # Mix: keep original audio at full volume, add BGM at 18%
    # Trim BGM to video length, fade in/out
    filter_complex = (
        f"[1:a]volume={BGM_VOLUME},"
        f"afade=t=in:st=0:d=2,"
        f"afade=t=out:st={video_duration - 2}:d=2,"
        f"atrim=0:{video_duration}[bgm];"
        f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", bgm_path,
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0 and Path(output_path).exists():
        print(f"   BGM mixed successfully: {output_path}")
        return output_path
    else:
        print(f"   ⚠️  BGM mix failed: {result.stderr[-300:]}")
        return video_path  # Return original if mix fails


if __name__ == "__main__":
    import sys
    ep = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    style = sys.argv[2] if len(sys.argv) > 2 else "default"
    bgm = generate_bgm(ep, style)
    if bgm:
        # If final video exists, mix BGM into it
        final_video = VIDEO_DIR / f"ep{ep}_final.mp4"
        if final_video.exists():
            mix_bgm_with_video(str(final_video), bgm)
