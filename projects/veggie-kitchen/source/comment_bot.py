"""
Comment Engagement Bot - Monitors YouTube comments and replies in-character.

Uses GPT-4o to generate replies as show characters (primarily Chef Tomatino).
Respects YouTube rate limits and community guidelines.

Usage:
    python comment_bot.py                    # Monitor and reply to new comments
    python comment_bot.py --video VIDEO_ID   # Monitor specific video
    python comment_bot.py --dry-run          # Preview replies without posting

Rate Limits:
    - Max 50 replies per day (YouTube quota is 10,000 units/day, comments use 50 each)
    - Minimum 5 minutes between replies on same video
    - Never reply to the same comment twice
"""

import os
import json
import time
import random
import argparse
from pathlib import Path
from datetime import datetime, timedelta

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    from googleapiclient.discovery import build
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False

from config import PROJECT_DIR
from characters import CHARACTERS

# Bot configuration
MAX_REPLIES_PER_DAY = 50
MIN_REPLY_INTERVAL = 300  # seconds (5 minutes)
REPLY_LOG_FILE = PROJECT_DIR / "comment_replies_log.json"
BOT_STATE_FILE = PROJECT_DIR / "comment_bot_state.json"

# Character response personalities
REPLY_CHARACTERS = {
    "Chef Tomatino": {
        "personality": (
            "You are Chef Tomatino, an angry tomato chef from Vegetable Hell's Kitchen. "
            "You yell a lot (USE CAPS), are dramatic, passionate about cooking, "
            "and secretly a fruit living as a vegetable. You call people 'donkey' sometimes. "
            "Keep replies SHORT (1-2 sentences max). Be funny and memeable. "
            "NEVER be actually mean or hurtful. This is comedy."
        ),
        "weight": 0.5,  # 50% chance of Tomatino replying
    },
    "Celery Steve": {
        "personality": (
            "You are Celery Steve, a nervous celery stalk always on the verge of panic. "
            "You stutter sometimes, are anxious, and your family is in a Bloody Mary. "
            "Keep replies SHORT. Be endearingly pathetic. Self-deprecating humor."
        ),
        "weight": 0.2,
    },
    "Potato Pete": {
        "personality": (
            "You are Potato Pete, a philosophical potato. You speak in short, cryptic, "
            "zen-like sentences. Everything sounds like an ancient proverb but it's about "
            "being a potato. Keep replies to ONE short sentence. Mysterious energy."
        ),
        "weight": 0.15,
    },
    "Narrator": {
        "personality": (
            "You are the snarky narrator of Vegetable Hell's Kitchen. "
            "You narrate everything like a BBC nature documentary but it's about vegetables. "
            "Dry British wit. Keep it to one dramatic observation. "
            "Speak in third person about the commenter."
        ),
        "weight": 0.15,
    },
}


def load_bot_state() -> dict:
    """Load bot state (replied comments, daily count, etc)."""
    if BOT_STATE_FILE.exists():
        with open(BOT_STATE_FILE) as f:
            return json.load(f)
    return {
        "replied_comments": [],
        "daily_count": 0,
        "last_reset_date": datetime.now().strftime("%Y-%m-%d"),
        "last_reply_time": 0,
    }


def save_bot_state(state: dict):
    """Save bot state."""
    with open(BOT_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def pick_character() -> tuple[str, dict]:
    """Randomly pick a character to reply as, weighted by config."""
    rand = random.random()
    cumulative = 0
    for char, config in REPLY_CHARACTERS.items():
        cumulative += config["weight"]
        if rand <= cumulative:
            return char, config
    return "Chef Tomatino", REPLY_CHARACTERS["Chef Tomatino"]


def generate_reply(comment_text: str, video_title: str = "") -> tuple[str, str]:
    """Generate an in-character reply to a comment using GPT-4o.

    Returns (character_name, reply_text).
    """
    if not HAS_OPENAI:
        raise ImportError("openai package not installed")

    char_name, char_config = pick_character()
    client = OpenAI()

    prompt = f"""You are replying to a YouTube comment as a character from "Vegetable Hell's Kitchen".

{char_config['personality']}

Video title: {video_title}
Comment to reply to: "{comment_text}"

Rules:
- Reply MUST be under 150 characters (YouTube comment reply limit is short for engagement)
- Be funny, in-character, and engaging
- NEVER be mean, hateful, or offensive
- Use relevant emoji (max 2)
- Make people want to reply back or like the comment
- Reference the show if relevant
- DO NOT use hashtags in replies

Reply as {char_name} (just the reply text, nothing else):"""

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=100,
        messages=[
            {"role": "system", "content": "You are a comedy character replying to YouTube comments. Be brief, funny, and in-character."},
            {"role": "user", "content": prompt},
        ],
        temperature=1.0,
    )

    reply = response.choices[0].message.content.strip()
    # Clean up quotes if the model wraps in them
    reply = reply.strip('"').strip("'")
    # Ensure under 150 chars
    if len(reply) > 150:
        reply = reply[:147] + "..."

    return char_name, reply


def get_video_comments(youtube, video_id: str, max_results: int = 20) -> list:
    """Fetch top-level comments on a video."""
    try:
        response = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=max_results,
            order="relevance",
        ).execute()

        comments = []
        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "id": item["id"],
                "comment_id": item["snippet"]["topLevelComment"]["id"],
                "text": snippet["textDisplay"],
                "author": snippet["authorDisplayName"],
                "likes": snippet.get("likeCount", 0),
                "published": snippet["publishedAt"],
            })

        return comments
    except Exception as e:
        print(f"   Error fetching comments: {e}")
        return []


def post_reply(youtube, parent_id: str, reply_text: str) -> bool:
    """Post a reply to a comment."""
    try:
        youtube.comments().insert(
            part="snippet",
            body={
                "snippet": {
                    "parentId": parent_id,
                    "textOriginal": reply_text,
                }
            },
        ).execute()
        return True
    except Exception as e:
        print(f"   Error posting reply: {e}")
        return False


def get_channel_videos(youtube, max_results: int = 10) -> list:
    """Get recent videos from our channel."""
    try:
        channels = youtube.channels().list(mine=True, part="contentDetails").execute()
        if not channels.get("items"):
            return []

        playlist_id = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        playlist = youtube.playlistItems().list(
            playlistId=playlist_id,
            part="snippet",
            maxResults=max_results,
        ).execute()

        videos = []
        for item in playlist.get("items", []):
            videos.append({
                "video_id": item["snippet"]["resourceId"]["videoId"],
                "title": item["snippet"]["title"],
                "published": item["snippet"]["publishedAt"],
            })
        return videos
    except Exception as e:
        print(f"   Error fetching channel videos: {e}")
        return []


def run_bot(video_id: str = None, dry_run: bool = False, max_replies: int = 5):
    """Run the comment engagement bot.

    Monitors comments and replies in-character to top comments.
    """
    if not HAS_GOOGLE_API:
        print("❌ Google API libraries not installed")
        print("   pip install google-api-python-client google-auth-oauthlib")
        return

    if not HAS_OPENAI:
        print("❌ OpenAI library not installed")
        return

    # Load state
    state = load_bot_state()

    # Reset daily count if new day
    today = datetime.now().strftime("%Y-%m-%d")
    if state["last_reset_date"] != today:
        state["daily_count"] = 0
        state["last_reset_date"] = today

    if state["daily_count"] >= MAX_REPLIES_PER_DAY:
        print(f"⚠️  Daily reply limit reached ({MAX_REPLIES_PER_DAY}). Try again tomorrow.")
        return

    # Authenticate
    from youtube_upload import get_authenticated_service
    youtube = get_authenticated_service()

    # Get videos to monitor
    if video_id:
        videos = [{"video_id": video_id, "title": ""}]
    else:
        videos = get_channel_videos(youtube)
        if not videos:
            print("No videos found on channel")
            return

    replies_made = 0

    for video in videos:
        if replies_made >= max_replies:
            break

        vid = video["video_id"]
        title = video.get("title", "")
        print(f"\n📺 Checking: {title or vid}")

        comments = get_video_comments(youtube, vid)
        if not comments:
            print("   No comments found")
            continue

        # Filter out already-replied comments
        new_comments = [
            c for c in comments
            if c["comment_id"] not in state["replied_comments"]
        ]

        if not new_comments:
            print("   All comments already replied to")
            continue

        # Reply to top comments (by likes)
        new_comments.sort(key=lambda c: c["likes"], reverse=True)

        for comment in new_comments[:3]:  # Max 3 per video
            if replies_made >= max_replies:
                break

            # Rate limit check
            elapsed = time.time() - state["last_reply_time"]
            if elapsed < MIN_REPLY_INTERVAL:
                wait = MIN_REPLY_INTERVAL - elapsed
                print(f"   ⏳ Rate limit: waiting {int(wait)}s...")
                if not dry_run:
                    time.sleep(wait)

            # Generate reply
            char_name, reply = generate_reply(comment["text"], title)
            print(f"   💬 @{comment['author']}: \"{comment['text'][:60]}...\"")
            print(f"   🎭 {char_name}: \"{reply}\"")

            if dry_run:
                print("   [DRY RUN - not posting]")
            else:
                success = post_reply(youtube, comment["comment_id"], reply)
                if success:
                    state["replied_comments"].append(comment["comment_id"])
                    state["daily_count"] += 1
                    state["last_reply_time"] = time.time()
                    replies_made += 1
                    print("   ✅ Reply posted!")

                    # Log the reply
                    _log_reply(comment, char_name, reply, vid)
                else:
                    print("   ❌ Failed to post reply")

    # Save state
    save_bot_state(state)
    print(f"\n📊 Session: {replies_made} replies made. Daily total: {state['daily_count']}/{MAX_REPLIES_PER_DAY}")


def _log_reply(comment: dict, char_name: str, reply: str, video_id: str):
    """Log a reply for tracking/review."""
    log = []
    if REPLY_LOG_FILE.exists():
        with open(REPLY_LOG_FILE) as f:
            log = json.load(f)

    log.append({
        "timestamp": datetime.now().isoformat(),
        "video_id": video_id,
        "comment_author": comment["author"],
        "comment_text": comment["text"],
        "character": char_name,
        "reply": reply,
    })

    # Keep last 500 entries
    log = log[-500:]

    with open(REPLY_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Veggie Kitchen Comment Engagement Bot")
    parser.add_argument("--video", type=str, help="Specific video ID to monitor")
    parser.add_argument("--dry-run", action="store_true", help="Preview replies without posting")
    parser.add_argument("--max-replies", type=int, default=5, help="Max replies per session")

    args = parser.parse_args()
    run_bot(video_id=args.video, dry_run=args.dry_run, max_replies=args.max_replies)
