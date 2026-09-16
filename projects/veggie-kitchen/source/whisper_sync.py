"""
Whisper Sync - Extract word-level timestamps from audio files.

Uses openai-whisper (installed via brew) to transcribe each scene's audio
and return precise word-by-word timing for subtitle sync.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from config import AUDIO_DIR


def transcribe_audio(audio_path: str, model: str = "base") -> dict:
    """Run Whisper on an audio file and return word-level timestamps.

    Args:
        audio_path: Path to audio file (mp3/wav)
        model: Whisper model size (tiny, base, small, medium, large)

    Returns:
        dict with 'segments' containing word-level timing data
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        return {"segments": [], "text": ""}

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "whisper",
            str(audio_path),
            "--model", model,
            "--language", "en",
            "--word_timestamps", "True",
            "--output_format", "json",
            "--output_dir", tmpdir,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            print(f"      [WARN] Whisper failed for {audio_path.name}: {result.stderr[-200:]}")
            return {"segments": [], "text": ""}

        # Whisper outputs <filename>.json in the output dir
        json_path = Path(tmpdir) / (audio_path.stem + ".json")
        if not json_path.exists():
            return {"segments": [], "text": ""}

        with open(json_path) as f:
            return json.load(f)


def get_word_timestamps(audio_path: str, model: str = "base") -> list[dict]:
    """Get flat list of word timestamps from audio file.

    Returns:
        List of dicts: [{"word": "hello", "start": 0.0, "end": 0.48}, ...]
    """
    data = transcribe_audio(audio_path, model)

    words = []
    for segment in data.get("segments", []):
        for w in segment.get("words", []):
            words.append({
                "word": w.get("word", "").strip(),
                "start": w.get("start", 0.0),
                "end": w.get("end", 0.0),
            })

    return words


def get_episode_timestamps(episode_num: int, num_scenes: int,
                           model: str = "base") -> dict[int, list[dict]]:
    """Transcribe all scenes for an episode and return word timestamps.

    Args:
        episode_num: Episode number
        num_scenes: Number of scenes to process
        model: Whisper model size

    Returns:
        Dict mapping scene_num -> list of word timestamp dicts
    """
    ep_audio_dir = AUDIO_DIR / f"ep{episode_num}"
    timestamps = {}

    for scene_num in range(1, num_scenes + 1):
        audio_path = ep_audio_dir / f"scene_{scene_num:02d}_combined.mp3"
        if not audio_path.exists():
            print(f"      [SKIP] No audio for scene {scene_num}")
            timestamps[scene_num] = []
            continue

        print(f"      Transcribing scene {scene_num}...")
        words = get_word_timestamps(str(audio_path), model)
        timestamps[scene_num] = words

        if words:
            print(f"      [{len(words)} words, {words[-1]['end']:.1f}s]")
        else:
            print(f"      [no words detected]")

    return timestamps


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # Quick test: transcribe a single audio file
        words = get_word_timestamps(sys.argv[1])
        for w in words:
            print(f"  {w['start']:6.2f} - {w['end']:6.2f}  {w['word']}")
    else:
        # Transcribe all of episode 1
        ts = get_episode_timestamps(1, 14)
        for scene_num, words in ts.items():
            print(f"\nScene {scene_num}: {len(words)} words")
            for w in words:
                print(f"  {w['start']:6.2f} - {w['end']:6.2f}  {w['word']}")
