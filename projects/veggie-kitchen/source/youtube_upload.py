"""
YouTube Upload - Uploads Shorts to YouTube via Data API v3.

Handles OAuth2 authentication, auto-generates metadata from script,
and uploads videos with proper tags/description.

Setup:
    1. Go to https://console.cloud.google.com/
    2. Create a project, enable YouTube Data API v3
    3. Create OAuth 2.0 credentials (Desktop app)
    4. Download client_secret.json to this directory
    5. First run will open browser for authorization
    6. Credentials cached in youtube_credentials.json

Channel: VeggieKitchenNightmare
"""

import os
import json
import time
from pathlib import Path

# Google API dependencies — install with:
#   pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False

from config import PROJECT_DIR

# OAuth2 config
CLIENT_SECRET_FILE = PROJECT_DIR / "client_secret.json"
CREDENTIALS_FILE = PROJECT_DIR / "youtube_credentials.json"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# YouTube upload defaults
DEFAULT_CATEGORY = "24"  # Entertainment
CHANNEL_NAME = "VeggieKitchenNightmare"
PRIVACY_STATUS = "public"  # public, unlisted, or private


def get_authenticated_service():
    """Authenticate with YouTube Data API v3 via OAuth2.

    First run opens browser for authorization.
    Subsequent runs use cached credentials.
    """
    if not HAS_GOOGLE_API:
        raise ImportError(
            "Google API libraries not installed. Run:\n"
            "  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )

    if not CLIENT_SECRET_FILE.exists():
        raise FileNotFoundError(
            f"OAuth client secret not found at {CLIENT_SECRET_FILE}\n"
            "Download from Google Cloud Console → APIs → Credentials → OAuth 2.0 Client"
        )

    credentials = None

    # Load cached credentials
    if CREDENTIALS_FILE.exists():
        credentials = Credentials.from_authorized_user_file(str(CREDENTIALS_FILE), SCOPES)

    # Refresh or re-authenticate
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_FILE), SCOPES
            )
            credentials = flow.run_local_server(port=0)

        # Cache credentials
        with open(CREDENTIALS_FILE, "w") as f:
            f.write(credentials.to_json())

    return build("youtube", "v3", credentials=credentials)


def generate_metadata(script: dict) -> dict:
    """Auto-generate YouTube metadata from episode script."""
    episode_num = script.get("episode_number", 1)
    title = script.get("video_title", f"Vegetable Hell's Kitchen Ep.{episode_num}")

    # Ensure title is within YouTube limits
    if len(title) > 100:
        title = title[:97] + "..."

    # Build description
    video_desc = script.get("video_description", "")
    hashtags = script.get("hashtags", [
        "#VegetableHellsKitchen", "#AIBrainrot", "#VeggieDrama",
        "#Shorts", "#CookingChaos", "#Brainrot",
    ])

    # Add standard hashtags
    standard_tags = ["#Shorts", "#AIGenerated", "#Brainrot", "#VeggieKitchen"]
    for tag in standard_tags:
        if tag not in hashtags:
            hashtags.append(tag)

    description = f"""{video_desc}

Episode {episode_num} of Vegetable Hell's Kitchen — the AI brainrot cooking competition where vegetables compete, cry, and question their existence.

{' '.join(hashtags)}

Subscribe for more veggie drama! 🍅🔥

---
Made with AI (GPT-4o + Flux + Kling + ElevenLabs + FFmpeg)
"""

    # Tags for discoverability
    tags = [
        "vegetable hells kitchen", "ai brainrot", "veggie drama",
        "cooking competition", "ai generated", "shorts",
        "brainrot content", "animated vegetables", "comedy",
        "chef tomatino", "reality tv parody",
    ]

    return {
        "title": title,
        "description": description.strip(),
        "tags": tags,
        "category_id": DEFAULT_CATEGORY,
    }


def upload_to_youtube(
    video_path: str,
    script: dict = None,
    privacy: str = PRIVACY_STATUS,
    schedule_time: str = None,
) -> str:
    """Upload a video to YouTube as a Short.

    Args:
        video_path: Path to the video file
        script: Episode script dict for metadata generation
        privacy: "public", "unlisted", or "private"
        schedule_time: ISO 8601 datetime for scheduled publish (optional)

    Returns:
        YouTube video ID on success, None on failure
    """
    if not Path(video_path).exists():
        print(f"   ❌ Video not found: {video_path}")
        return None

    # Generate metadata
    if script:
        metadata = generate_metadata(script)
    else:
        metadata = {
            "title": "Vegetable Hell's Kitchen #Shorts",
            "description": "AI brainrot cooking competition 🍅🔥 #Shorts #AIBrainrot",
            "tags": ["shorts", "ai brainrot", "veggie drama"],
            "category_id": DEFAULT_CATEGORY,
        }

    print(f"   📤 Uploading to YouTube: {metadata['title']}")

    try:
        youtube = get_authenticated_service()
    except (ImportError, FileNotFoundError) as e:
        print(f"   ⚠️  {e}")
        return None

    # Build request body
    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata["tags"],
            "categoryId": metadata["category_id"],
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "commentSettings": "enabled",
        },
    }

    # Add scheduled publish time if provided
    if schedule_time and privacy == "private":
        body["status"]["publishAt"] = schedule_time
        body["status"]["privacyStatus"] = "private"

    # Upload with resumable upload
    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024,  # 1MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    # Execute with progress reporting
    response = None
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                print(f"   📤 Upload progress: {progress}%")
        except Exception as e:
            print(f"   ❌ Upload error: {e}")
            return None

    video_id = response.get("id")
    if video_id:
        print(f"   ✅ Upload complete!")
        print(f"   🔗 https://youtube.com/shorts/{video_id}")
        return video_id
    else:
        print(f"   ❌ Upload failed: {response}")
        return None


def list_uploads(max_results: int = 5):
    """List recent uploads on the channel (for verification)."""
    try:
        youtube = get_authenticated_service()
    except (ImportError, FileNotFoundError) as e:
        print(f"⚠️  {e}")
        return

    # Get channel's upload playlist
    channels = youtube.channels().list(mine=True, part="contentDetails").execute()
    if not channels.get("items"):
        print("No channel found")
        return

    playlist_id = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # List videos
    playlist = youtube.playlistItems().list(
        playlistId=playlist_id,
        part="snippet",
        maxResults=max_results,
    ).execute()

    print(f"\n📺 Recent uploads ({CHANNEL_NAME}):")
    for item in playlist.get("items", []):
        snippet = item["snippet"]
        print(f"   • {snippet['title']}")
        print(f"     Published: {snippet['publishedAt']}")
        print(f"     ID: {snippet['resourceId']['videoId']}")


# ── TikTok Upload Research ──────────────────────────────────────────────────
TIKTOK_NOTES = """
=== TikTok Upload API Research ===

TikTok Content Posting API requires:
1. A TikTok Developer account (https://developers.tiktok.com/)
2. App registration and review
3. Business verification (business license/registration)
4. OAuth2 authentication flow
5. The "Content Posting API" permission (requires app review)

Steps to set up:
1. Register at developers.tiktok.com
2. Create an app → select "Content Posting API"
3. Submit for review (may take 1-2 weeks)
4. Once approved, implement OAuth2 flow
5. Use POST /v2/post/publish/video/init/ to upload

Key limitations:
- Business verification required (not available for personal accounts easily)
- App review process is manual and slow
- Daily upload limits apply
- Videos must be under 10 minutes
- Must comply with TikTok community guidelines

Alternative approaches:
- Use TikTok's "Share to TikTok" SDK (mobile only)
- Use browser automation (Selenium/Playwright) — against TOS but common
- Use third-party services like Repurpose.io or Publer
- Manually upload (fastest for low volume)

Recommended: Start with YouTube Shorts, manually cross-post to TikTok.
When volume justifies it, apply for TikTok Business API access.
"""


def print_tiktok_research():
    """Print TikTok upload research findings."""
    print(TIKTOK_NOTES)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Test authentication
        print("Testing YouTube API authentication...")
        try:
            youtube = get_authenticated_service()
            print("✅ Authentication successful!")
            list_uploads()
        except Exception as e:
            print(f"❌ Authentication failed: {e}")

    elif len(sys.argv) > 1 and sys.argv[1] == "tiktok":
        print_tiktok_research()

    elif len(sys.argv) > 2 and sys.argv[1] == "upload":
        video_path = sys.argv[2]
        script_path = sys.argv[3] if len(sys.argv) > 3 else None
        script = None
        if script_path and Path(script_path).exists():
            with open(script_path) as f:
                script = json.load(f)
        upload_to_youtube(video_path, script)

    else:
        print("Usage:")
        print("  python youtube_upload.py test              # Test auth")
        print("  python youtube_upload.py upload <video>     # Upload video")
        print("  python youtube_upload.py tiktok             # TikTok research")
