#!/usr/bin/env python3
"""
Vegetable Hell's Kitchen - Full Episode Generation Pipeline
============================================================
Single command to generate a complete episode end-to-end.

Usage:
    python generate_episode.py 2                  # Full pipeline for episode 2
    python generate_episode.py 2 --step script    # Only generate the script
    python generate_episode.py 2 --step images    # Only generate images
    python generate_episode.py 2 --step animate   # Only animate images
    python generate_episode.py 2 --step voice     # Only generate voice
    python generate_episode.py 2 --step video     # Only assemble video
    python generate_episode.py 2 --step bgm       # Only generate/mix BGM
    python generate_episode.py 2 --step upload    # Only upload to YouTube
    python generate_episode.py 2 --step preview   # Script preview only
    python generate_episode.py 2 --no-upload      # Full pipeline, skip upload

Pipeline:
    1. Load story state from previous episodes
    2. Generate script with GPT-4o (with full story context)
    3. Generate portrait images with Fal.ai Flux 2 Pro
    4. Animate images with Fal.ai Kling (unique motion prompts per scene, 9:16)
    5. Generate voices with Fal.ai ElevenLabs (character-specific voices)
    6. Sync captions with Whisper (word-by-word, 3-word chunks)
    7. Assemble video with FFmpeg (Ken Burns, transitions, color boost, captions)
    8. Generate BGM with CassetteAI via Fal.ai
    9. Mix BGM at 18% under voice
    10. Upload to YouTube (optional)

Required environment variables:
    FAL_KEY          - For image/voice/animation/BGM (Fal.ai)
    OPENAI_API_KEY   - For script generation (GPT-4o)
"""

import sys
import json
import time
import argparse
import traceback
from pathlib import Path

from config import SCRIPTS_DIR, VIDEO_DIR


def load_script(episode_num: int) -> dict:
    """Load an existing script from disk."""
    script_path = SCRIPTS_DIR / f"ep{episode_num}_script.json"
    if not script_path.exists():
        return None
    with open(script_path) as f:
        return json.load(f)


def run_pipeline(episode_num: int, step: str = None, no_upload: bool = False):
    """Run the full pipeline or a specific step."""

    print(f"\n🍅🔥 VEGETABLE HELL'S KITCHEN — Episode {episode_num} 🔥🍅")
    print(f"{'='*55}")
    if step:
        print(f"   Running step: {step}")
    else:
        print(f"   Running FULL PIPELINE (all steps)")
    print(f"{'='*55}\n")

    start_time = time.time()
    script = None

    # === STEP 1: SCRIPT GENERATION ===
    if step in (None, "script", "preview"):
        print("📝 STEP 1: Generating Script (with story engine context)...")
        print("-" * 45)
        try:
            from script_generator import generate_script, print_script
            script = generate_script(episode_num)
            print_script(script)
        except Exception as e:
            print(f"❌ Script generation failed: {e}")
            traceback.print_exc()
            return

        if step == "preview":
            print("\n✋ Preview mode — stopping here.")
            return

        if step == "script":
            print("\n✋ Script step complete.")
            return
    else:
        script = load_script(episode_num)
        if not script:
            print(f"❌ No script found for episode {episode_num}. Run --step script first.")
            return

    # === STEP 2: IMAGE GENERATION ===
    if step in (None, "images"):
        print("\n🖼️  STEP 2: Generating Images (Flux 2 Pro)...")
        print("-" * 45)
        try:
            from image_generator import generate_images
            images = generate_images(episode_num, script)
            print(f"   ✅ {len(images)} images ready")
        except Exception as e:
            print(f"❌ Image generation failed: {e}")
            traceback.print_exc()
            if step is not None:
                return
            print("   ⚠️  Continuing pipeline (video assembler will use available images)...")

        if step == "images":
            print("\n✋ Images step complete.")
            return

    # === STEP 3: ANIMATION ===
    if step in (None, "animate"):
        print("\n🎬 STEP 3: Animating Scenes (Kling Video, 9:16)...")
        print("-" * 45)
        try:
            from animate_scenes import animate_scenes
            clips = animate_scenes(episode_num, script)
            print(f"   ✅ {len(clips)} clips animated")
        except Exception as e:
            print(f"⚠️  Animation failed: {e}")
            traceback.print_exc()
            if step is not None:
                return
            print("   Continuing with static images + Ken Burns...")

        if step == "animate":
            print("\n✋ Animation step complete.")
            return

    # === STEP 4: VOICE GENERATION ===
    if step in (None, "voice"):
        print("\n🎙️  STEP 4: Generating Voices (ElevenLabs)...")
        print("-" * 45)
        try:
            from voice_generator import generate_voice
            audio_files = generate_voice(episode_num, script)
            print(f"   ✅ {len(audio_files)} audio files ready")
        except Exception as e:
            print(f"❌ Voice generation failed: {e}")
            traceback.print_exc()
            if step is not None:
                return
            print("   ⚠️  Continuing without voice (video will be silent)...")

        if step == "voice":
            print("\n✋ Voice step complete.")
            return

    # === STEP 5: VIDEO ASSEMBLY (includes Whisper sync) ===
    if step in (None, "video"):
        print("\n🎥 STEP 5: Assembling Video (Whisper sync + Ken Burns + transitions)...")
        print("-" * 45)
        try:
            from video_assembler import assemble_video
            video_path = assemble_video(episode_num, script)
        except Exception as e:
            print(f"❌ Video assembly failed: {e}")
            traceback.print_exc()
            return

        if not video_path:
            print("❌ Video assembly returned no path.")
            return

        if step == "video":
            print(f"\n✋ Video step complete: {video_path}")
            return

    # === STEP 6: BGM GENERATION & MIX ===
    if step in (None, "bgm"):
        print("\n🎵 STEP 6: Generating BGM (CassetteAI) + mixing at 18%...")
        print("-" * 45)

        video_no_bgm = VIDEO_DIR / f"ep{episode_num}_final.mp4"
        if not video_no_bgm.exists():
            if step == "bgm":
                print(f"❌ No video found at {video_no_bgm}")
                return
            print("   ⚠️  No video to mix BGM into, skipping...")
        else:
            try:
                from bgm_generator import generate_bgm, mix_bgm_with_video

                # Generate BGM
                bgm_path = generate_bgm(episode_num, style="default")

                if bgm_path:
                    # Mix BGM into video (temp file, then replace original)
                    final_with_bgm = str(VIDEO_DIR / f"ep{episode_num}_final_bgm.mp4")
                    result_path = mix_bgm_with_video(
                        str(video_no_bgm), bgm_path, final_with_bgm
                    )
                    video_path = result_path
                    # Copy BGM version over as the canonical ep_final.mp4
                    if Path(result_path).exists() and result_path != str(video_no_bgm):
                        import shutil
                        shutil.copy2(result_path, str(video_no_bgm))
                        print(f"   ✅ Final video (with BGM): {video_no_bgm}")
                    else:
                        print(f"   ✅ Final video with BGM: {result_path}")
                else:
                    print("   ⚠️  BGM generation failed, using video without BGM")
                    video_path = str(video_no_bgm)

            except Exception as e:
                print(f"⚠️  BGM step failed: {e}")
                traceback.print_exc()
                video_path = str(video_no_bgm)

        if step == "bgm":
            print("\n✋ BGM step complete.")
            return

    # === STEP 7: YOUTUBE UPLOAD ===
    if step in (None, "upload") and not no_upload:
        print("\n📤 STEP 7: YouTube Upload...")
        print("-" * 45)

        # Determine best video file to upload
        final_bgm = VIDEO_DIR / f"ep{episode_num}_final_bgm.mp4"
        final_plain = VIDEO_DIR / f"ep{episode_num}_final.mp4"

        if final_bgm.exists():
            upload_video = str(final_bgm)
        elif final_plain.exists():
            upload_video = str(final_plain)
        else:
            print("   ❌ No video file found to upload")
            if step == "upload":
                return
            upload_video = None

        if upload_video:
            try:
                from youtube_upload import upload_to_youtube
                result = upload_to_youtube(upload_video, script)
                if result:
                    print(f"   ✅ Uploaded! Video ID: {result}")
                else:
                    print("   ⚠️  Upload skipped or failed (check credentials)")
            except ImportError:
                print("   ⚠️  youtube_upload module not available")
            except Exception as e:
                print(f"   ⚠️  Upload failed: {e}")
                if step == "upload":
                    traceback.print_exc()

        if step == "upload":
            print("\n✋ Upload step complete.")
            return
    elif no_upload:
        print("\n⏭️  Skipping YouTube upload (--no-upload flag)")

    # === DONE ===
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    print(f"\n{'='*55}")
    print(f"🎉 EPISODE {episode_num} COMPLETE!")
    print(f"{'='*55}")
    print(f"⏱️  Total time: {minutes}m {seconds}s")

    # Show output files
    final_bgm = VIDEO_DIR / f"ep{episode_num}_final_bgm.mp4"
    final_plain = VIDEO_DIR / f"ep{episode_num}_final.mp4"
    if final_bgm.exists():
        size_mb = final_bgm.stat().st_size / (1024 * 1024)
        print(f"📁 Video (with BGM): {final_bgm} ({size_mb:.1f}MB)")
    if final_plain.exists():
        size_mb = final_plain.stat().st_size / (1024 * 1024)
        print(f"📁 Video (no BGM):   {final_plain} ({size_mb:.1f}MB)")

    script_path = SCRIPTS_DIR / f"ep{episode_num}_script.json"
    if script_path.exists():
        print(f"📄 Script: {script_path}")

    print(f"{'='*55}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Vegetable Hell's Kitchen - AI Brainrot Video Generator"
    )
    parser.add_argument(
        "episode",
        nargs="?",
        type=int,
        default=1,
        help="Episode number to generate (default: 1)",
    )
    parser.add_argument(
        "--step",
        choices=["script", "images", "animate", "voice", "video", "bgm", "upload", "preview"],
        default=None,
        help="Run a specific pipeline step (default: run all)",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip YouTube upload even in full pipeline",
    )

    args = parser.parse_args()
    run_pipeline(args.episode, args.step, args.no_upload)


if __name__ == "__main__":
    main()
