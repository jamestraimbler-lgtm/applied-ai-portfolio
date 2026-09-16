"""
Video Assembler v2 - Professional-grade vertical video assembly pipeline.

Combines animated clips, Whisper-synced word-by-word captions (ASS format),
transition effects, and proper audio mixing into final TikTok/Shorts video.

Key improvements over v1:
- Whisper word-level timestamps for perfect caption sync
- ASS subtitle format with TikTok-style bold outlined text
- Word-by-word highlight (active word in yellow, rest white)
- Flash/zoom-punch transitions between scenes
- Better Ken Burns with more dynamic motion
- Improved color grading (contrast + saturation)
- Safe zone awareness for platform UI overlays
- Background music bed support
"""

import os
import json
import random
import subprocess
import tempfile
from pathlib import Path
from config import (
    VIDEO_DIR, IMAGES_DIR, AUDIO_DIR, SCRIPTS_DIR,
    VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS,
)

# ── Caption Settings ──────────────────────────────────────────────────────────
# Use Impact (available on macOS) — the classic bold meme/brainrot font
FONT_NAME = "Impact"
FONT_PATH = "/System/Library/Fonts/Supplemental/Impact.ttf"
FONT_SIZE = 78                    # Large for vertical video readability
WORDS_PER_CHUNK = 3               # Words shown at once (brainrot style)
CAPTION_Y_POSITION = 1350         # Y position (upper-lower third, safe from UI)
HIGHLIGHT_COLOR = "&H0000FFFF"    # Yellow (ASS BGR format) for active word
NORMAL_COLOR = "&H00FFFFFF"       # White for inactive words
OUTLINE_COLOR = "&H00000000"      # Black outline
OUTLINE_WIDTH = 5                 # Thick outline for readability
PLAY_RES_X = 1080                 # ASS resolution matches video
PLAY_RES_Y = 1920

# ── Video Effects ─────────────────────────────────────────────────────────────
SATURATION = 1.3                  # Color boost for punchy look
CONTRAST = 1.08                   # Slight contrast bump
BRIGHTNESS = 0.02                 # Slight brightness lift
TRANSITION_FRAMES = 2             # White flash frames between scenes
SCENE_PADDING_MS = 80             # Brief pause between scenes

# ── Whisper Settings ──────────────────────────────────────────────────────────
WHISPER_MODEL = "base"            # base is fast + good enough for TTS audio


def get_duration(file_path: str) -> float:
    """Get duration of a media file in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1",
         file_path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 4.0


def seconds_to_ass_time(s: float) -> str:
    """Convert seconds to ASS timestamp format (H:MM:SS.cc)."""
    hours = int(s // 3600)
    minutes = int((s % 3600) // 60)
    secs = int(s % 60)
    centis = int((s % 1) * 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def generate_ass_subtitles(
    word_timestamps: list[dict],
    scene_data: dict,
    duration: float,
    output_path: str,
    words_per_chunk: int = WORDS_PER_CHUNK,
) -> str:
    """Generate ASS subtitle file with word-by-word highlight synced to audio.

    If word timestamps are available (from Whisper), uses precise timing.
    Falls back to even distribution if no timestamps available.

    The active word is highlighted in yellow, surrounding words stay white.
    Each chunk pops in with a slight scale animation.
    """
    # Collect spoken text from scene for fallback
    segments_text = []
    if scene_data.get("narration"):
        segments_text.append(scene_data["narration"])
    for d in scene_data.get("dialogue", []):
        if d.get("line"):
            segments_text.append(d["line"])
    if not segments_text:
        caption = scene_data.get("caption_text", "")
        if caption:
            segments_text = [caption]

    # ── Build word list with timing ───────────────────────────────────────
    words_with_timing = []

    if word_timestamps:
        # Use Whisper timestamps (precise)
        words_with_timing = [
            {"word": w["word"], "start": w["start"], "end": w["end"]}
            for w in word_timestamps
            if w["word"].strip()
        ]
    elif segments_text:
        # Fallback: distribute words evenly across duration
        all_words = []
        for seg in segments_text:
            all_words.extend(seg.split())

        if all_words:
            pad = 0.15
            usable = max(duration - 2 * pad, 0.5)
            time_per_word = usable / len(all_words)
            for i, word in enumerate(all_words):
                words_with_timing.append({
                    "word": word,
                    "start": pad + i * time_per_word,
                    "end": pad + (i + 1) * time_per_word,
                })

    if not words_with_timing:
        # Write empty ASS file
        _write_ass_file(output_path, [])
        return output_path

    # ── Group words into chunks ───────────────────────────────────────────
    chunks = []
    for i in range(0, len(words_with_timing), words_per_chunk):
        chunk = words_with_timing[i:i + words_per_chunk]
        chunks.append(chunk)

    # ── Generate ASS events with word-by-word highlight ───────────────────
    events = []

    for chunk in chunks:
        chunk_start = chunk[0]["start"]
        chunk_end = chunk[-1]["end"]
        chunk_words = [w["word"].upper() for w in chunk]

        # Create one event per word in the chunk (active word highlighted)
        for active_idx, active_word_data in enumerate(chunk):
            word_start = active_word_data["start"]
            # End time: either next word's start, or chunk end
            if active_idx < len(chunk) - 1:
                word_end = chunk[active_idx + 1]["start"]
            else:
                word_end = chunk_end

            # Ensure minimum display time
            if word_end - word_start < 0.05:
                word_end = word_start + 0.05

            # Build the display text with highlight on active word
            parts = []
            for j, word_text in enumerate(chunk_words):
                if j == active_idx:
                    # Active word: yellow + slight scale pop
                    parts.append(
                        f"{{\\c{HIGHLIGHT_COLOR}\\fscx110\\fscy110}}"
                        f"{word_text}"
                        f"{{\\c{NORMAL_COLOR}\\fscx100\\fscy100}}"
                    )
                else:
                    parts.append(word_text)

            line_text = " ".join(parts)

            # Add fade-in on first word of chunk
            prefix = ""
            if active_idx == 0:
                prefix = "{\\fad(80,0)}"

            start_ts = seconds_to_ass_time(word_start)
            end_ts = seconds_to_ass_time(word_end)

            events.append(
                f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{prefix}{line_text}"
            )

    _write_ass_file(output_path, events)
    return output_path


def _write_ass_file(output_path: str, events: list[str]):
    """Write ASS subtitle file with TikTok-style formatting."""
    header = f"""[Script Info]
Title: Veggie Kitchen Captions
ScriptType: v4.00+
PlayResX: {PLAY_RES_X}
PlayResY: {PLAY_RES_Y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{FONT_SIZE},{NORMAL_COLOR},{HIGHLIGHT_COLOR},{OUTLINE_COLOR},&H00000000,-1,0,0,0,100,100,2,0,1,{OUTLINE_WIDTH},0,2,40,40,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(output_path, "w") as f:
        f.write(header)
        for event in events:
            f.write(event + "\n")


def build_scene_video(
    clip_info: dict,
    episode_num: int,
    word_timestamps: list[dict],
    out_path: Path,
) -> bool:
    """Render a single scene with video, audio, and synced captions.

    Returns True on success.
    """
    scene_num = clip_info["scene_num"]
    duration = clip_info["duration"]
    scene_data = clip_info["scene_data"]
    use_clip = clip_info["use_clip"]

    # ── Generate ASS subtitle file ────────────────────────────────────────
    ass_path = out_path.parent / f"scene_{scene_num:02d}.ass"
    generate_ass_subtitles(
        word_timestamps=word_timestamps,
        scene_data=scene_data,
        duration=duration,
        output_path=str(ass_path),
    )

    # ── Build video filter chain ──────────────────────────────────────────
    if use_clip:
        # Animated clip: scale → crop → color grade → subtitles
        vf = (
            f"[0:v]scale=-2:{VIDEO_HEIGHT},"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(iw-{VIDEO_WIDTH})/2:0,"
            f"eq=saturation={SATURATION}:contrast={CONTRAST}:brightness={BRIGHTNESS},"
            f"ass='{ass_path}'"
            f"[v]"
        )
    else:
        # Static image: Ken Burns → color grade → subtitles
        random.seed(scene_num + episode_num * 100)
        total_frames = int(duration * VIDEO_FPS)

        # More dynamic Ken Burns — wider zoom range, deliberate direction
        scene_type = scene_data.get("type", "drama")
        if scene_type == "hook":
            zoom_start, zoom_end = 1.15, 1.0     # zoom out (dramatic reveal)
        elif scene_type == "cliffhanger":
            zoom_start, zoom_end = 1.0, 1.2       # slow zoom in (tension)
        elif scene_type == "confessional":
            zoom_start, zoom_end = 1.05, 1.12     # gentle zoom in (intimate)
        else:
            zoom_start = random.uniform(1.0, 1.1)
            zoom_end = random.uniform(1.05, 1.2)
            if random.random() > 0.5:
                zoom_start, zoom_end = zoom_end, zoom_start

        x_drift = random.uniform(-0.04, 0.04)
        y_drift = random.uniform(-0.03, 0.03)

        vf = (
            f"[0:v]zoompan=z='if(eq(on\\,1)\\,{zoom_start}\\,"
            f"{zoom_start}+(({zoom_end}-{zoom_start})/{total_frames})*on)'"
            f":x='iw/2-(iw/zoom/2)+({x_drift}*on)'"
            f":y='ih/2-(ih/zoom/2)+({y_drift}*on)'"
            f":d={total_frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS},"
            f"eq=saturation={SATURATION}:contrast={CONTRAST}:brightness={BRIGHTNESS},"
            f"ass='{ass_path}'"
            f"[v]"
        )

    # ── Build FFmpeg command ──────────────────────────────────────────────
    cmd = ["ffmpeg", "-y"]

    if use_clip:
        cmd.extend(["-stream_loop", "-1"])

    cmd.extend(["-i", clip_info["video_source"]])

    if clip_info["audio"]:
        cmd.extend(["-i", clip_info["audio"]])
    else:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])

    cmd.extend([
        "-filter_complex", vf,
        "-map", "[v]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        "-r", str(VIDEO_FPS),
        "-movflags", "+faststart",
        str(out_path),
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"      [ERR] Scene {scene_num}: {result.stderr[-500:]}")
        return False

    return True


def generate_flash_frame(output_path: Path, duration_frames: int = 2) -> str:
    """Generate a brief white flash transition frame (as a video file)."""
    duration_sec = duration_frames / VIDEO_FPS
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"color=c=white:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:r={VIDEO_FPS}:d={duration_sec}",
        "-f", "lavfi", "-i",
        f"anullsrc=r=44100:cl=stereo",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-ac", "2",
        "-pix_fmt", "yuv420p",
        "-t", str(duration_sec),
        "-shortest",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return str(output_path)


def assemble_video(episode_num: int, script: dict = None) -> str:
    """Assemble final video from animated clips, audio, and Whisper-synced captions.

    Pipeline:
    1. Run Whisper on all scene audio files for word-level timestamps
    2. Generate ASS subtitle files with word-by-word highlight
    3. Render each scene (video + audio + captions)
    4. Add flash transitions between scenes
    5. Concatenate everything into the final video
    """
    # Load script
    if script is None:
        script_path = SCRIPTS_DIR / f"ep{episode_num}_script.json"
        if not script_path.exists():
            raise FileNotFoundError(f"No script found at {script_path}")
        with open(script_path) as f:
            script = json.load(f)

    ep_img_dir = IMAGES_DIR / f"ep{episode_num}"
    ep_clips_dir = ep_img_dir / "clips"
    ep_audio_dir = AUDIO_DIR / f"ep{episode_num}"
    temp_dir = VIDEO_DIR / f"ep{episode_num}_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Clean old temp files
    for old in temp_dir.glob("scene_*.mp4"):
        old.unlink()
    for old in temp_dir.glob("scene_*.ass"):
        old.unlink()
    for old in temp_dir.glob("flash_*.mp4"):
        old.unlink()

    # ── Step 1: Run Whisper for word-level timestamps ─────────────────────
    print(f"   Running Whisper ({WHISPER_MODEL}) for caption sync...")
    from whisper_sync import get_episode_timestamps
    num_scenes = len(script["scenes"])
    all_timestamps = get_episode_timestamps(episode_num, num_scenes, WHISPER_MODEL)

    # ── Step 2: Collect scene info ────────────────────────────────────────
    scene_clips = []
    for scene in script["scenes"]:
        scene_num = scene["scene_number"]
        clip_path = ep_clips_dir / f"scene_{scene_num:02d}.mp4"
        image_path = ep_img_dir / f"scene_{scene_num:02d}.png"
        audio_path = ep_audio_dir / f"scene_{scene_num:02d}_combined.mp3"

        # Prefer animated clip, fall back to static image
        if clip_path.exists():
            video_source = str(clip_path)
            use_clip = True
        elif image_path.exists():
            video_source = str(image_path)
            use_clip = False
        else:
            print(f"   [!] Missing media for scene {scene_num}, skipping")
            continue

        if audio_path.exists():
            duration = max(get_duration(str(audio_path)), 2.0)
        else:
            duration = scene.get("duration_seconds", 4)
            audio_path = None

        scene_clips.append({
            "scene_num": scene_num,
            "video_source": video_source,
            "use_clip": use_clip,
            "audio": str(audio_path) if audio_path else None,
            "duration": duration,
            "scene_data": scene,
        })

    if not scene_clips:
        raise ValueError("No scene clips to assemble!")

    print(f"\n   Assembling {len(scene_clips)} scenes...")

    # ── Step 3: Render each scene ─────────────────────────────────────────
    rendered_paths = []

    for clip in scene_clips:
        scene_num = clip["scene_num"]
        out_path = temp_dir / f"scene_{scene_num:02d}.mp4"

        word_timestamps = all_timestamps.get(scene_num, [])

        print(f"   Rendering scene {scene_num:02d} ({clip['duration']:.1f}s, "
              f"{len(word_timestamps)} words synced)...")

        success = build_scene_video(
            clip_info=clip,
            episode_num=episode_num,
            word_timestamps=word_timestamps,
            out_path=out_path,
        )

        if success:
            rendered_paths.append(str(out_path))
            print(f"      [OK]")
        else:
            print(f"      [FAILED]")

    if not rendered_paths:
        raise ValueError("No scenes rendered successfully!")

    # ── Step 4: Add flash transitions between scenes ──────────────────────
    print(f"\n   Adding transitions...")
    final_sequence = []

    for i, scene_path in enumerate(rendered_paths):
        final_sequence.append(scene_path)

        # Add flash transition between scenes (not after last)
        if i < len(rendered_paths) - 1 and TRANSITION_FRAMES > 0:
            flash_path = temp_dir / f"flash_{i:02d}.mp4"
            flash = generate_flash_frame(flash_path, TRANSITION_FRAMES)
            if flash:
                final_sequence.append(flash)

    # ── Step 5: Concatenate into final video ──────────────────────────────
    final_path = VIDEO_DIR / f"ep{episode_num}_final.mp4"
    concat_file = temp_dir / "concat.txt"

    with open(concat_file, "w") as f:
        for p in final_sequence:
            if Path(p).exists():
                f.write(f"file '{p}'\n")

    print(f"\n   Concatenating {len(final_sequence)} segments into final video...")

    # First try stream copy (fast)
    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(final_path),
    ]

    result = subprocess.run(concat_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Fallback: re-encode for consistent codec params
        print(f"   [!] Stream copy failed, re-encoding...")
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(final_path),
        ]
        result = subprocess.run(concat_cmd, capture_output=True, text=True)

    if final_path.exists():
        total_dur = get_duration(str(final_path))
        file_size_mb = final_path.stat().st_size / (1024 * 1024)

        print(f"\n   {'='*50}")
        print(f"   FINAL VIDEO: {final_path}")
        print(f"   Duration:    {total_dur:.1f}s")
        print(f"   Size:        {file_size_mb:.1f}MB")
        print(f"   Resolution:  {VIDEO_WIDTH}x{VIDEO_HEIGHT}")
        print(f"   Captions:    Whisper-synced word-by-word ASS")
        print(f"   Transitions: {TRANSITION_FRAMES}-frame flash between scenes")
        print(f"   {'='*50}")

        return str(final_path)
    else:
        print("   [ERR] Failed to create final video")
        return None


if __name__ == "__main__":
    import sys
    ep_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    assemble_video(ep_num)
