# Vegetable Hell's Kitchen - AI Brainrot Video Pipeline
# =====================================================
# Automated pipeline for generating short-form brainrot content
# featuring anthropomorphic vegetables in a cooking competition.
#
# Pipeline: Script (Claude) → Images (Fal.ai) → Voice (GPT TTS) → Video (FFmpeg)
#
# Usage:
#   python generate_episode.py --episode 1
#   python generate_episode.py --episode 1 --step script    # just generate script
#   python generate_episode.py --episode 1 --step images    # just generate images
#   python generate_episode.py --episode 1 --step voice     # just generate voice
#   python generate_episode.py --episode 1 --step video     # just assemble video

import os
import json
from pathlib import Path

# === DIRECTORIES ===
PROJECT_DIR = Path(__file__).parent
SCRIPTS_DIR = PROJECT_DIR / "output" / "scripts"
IMAGES_DIR = PROJECT_DIR / "output" / "images"
AUDIO_DIR = PROJECT_DIR / "output" / "audio"
VIDEO_DIR = PROJECT_DIR / "output" / "videos"

for d in [SCRIPTS_DIR, IMAGES_DIR, AUDIO_DIR, VIDEO_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# === API KEYS (set these as environment variables) ===
# export FAL_KEY="your-key"         - Image/Voice/Animation/BGM (Fal.ai)
# export OPENAI_API_KEY="your-key"  - Script generation (GPT-4o)

# === IMAGE GENERATION SETTINGS ===
IMAGE_MODEL = "fal-ai/flux-2-pro"  # cheapest for prototyping
IMAGE_SIZE = {"width": 768, "height": 1344}  # square, we crop to 9:16 in FFmpeg
FRAMES_PER_EPISODE = 14  # number of visual frames per episode

# === VIDEO SETTINGS ===
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920  # 9:16 vertical
VIDEO_FPS = 30
SECONDS_PER_FRAME = 4  # how long each image shows (with Ken Burns effect)

# === TTS SETTINGS ===
TTS_MODEL = "tts-1"  # OpenAI TTS model
NARRATOR_VOICE = "onyx"  # deep, dramatic narrator
CHARACTER_VOICES = {
    "Chef Tomatino": "echo",      # intense, commanding
    "Celery Steve": "fable",       # nervous, shaky
    "Potato Pete": "alloy",        # calm, understated
    "Pepper Patricia": "nova",     # fierce, energetic
    "Onion Olivia": "shimmer",     # emotional, dramatic
    "Garlic Gary": "alloy",        # scheming, quiet
}
