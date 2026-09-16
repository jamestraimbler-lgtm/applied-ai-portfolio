"""
Script Generator - Episode script generation using GPT-4o with story engine context.
Generates structured scripts with scenes, dialogue, image prompts, and caption text.
Maintains narrative continuity across episodes via story_engine.
"""

import os
import json
from openai import OpenAI
from pathlib import Path
from characters import CHARACTERS, SHOW_BIBLE, EPISODE_ARCS
from config import SCRIPTS_DIR, FRAMES_PER_EPISODE
from story_engine import (
    ensure_story_state,
    get_story_context_for_prompt,
    get_episode_directives,
    update_state_after_episode,
    save_story_state,
)


# Words to avoid in image prompts (Flux safety filters)
UNSAFE_IMAGE_WORDS = [
    "aggressive", "human-like", "scheming", "shifty", "fury",
    "violent", "attack", "weapon", "blood", "kill",
]


def sanitize_image_prompt(prompt: str) -> str:
    """Remove words that trigger Flux 2 Pro safety filters."""
    result = prompt
    for word in UNSAFE_IMAGE_WORDS:
        result = result.replace(word, "determined")
        result = result.replace(word.capitalize(), "Determined")
    return result


def _get_used_lines_from_previous_episodes(episode_num: int) -> str:
    """Scan all previous episode scripts and extract dialogue lines and catchphrases used."""
    used_lines = []
    for ep in range(1, episode_num):
        script_path = SCRIPTS_DIR / f"ep{ep}_script.json"
        if not script_path.exists():
            continue
        with open(script_path) as f:
            script = json.load(f)
        for scene in script.get("scenes", []):
            for line in scene.get("dialogue", []):
                used_lines.append(f"  Ep{ep} - {line['character']}: \"{line['line']}\"")
            if scene.get("narration"):
                used_lines.append(f"  Ep{ep} - Narrator: \"{scene['narration']}\"")
    if not used_lines:
        return ""
    return "=== LINES ALREADY USED (DO NOT REPEAT OR PARAPHRASE THESE) ===\n" + "\n".join(used_lines)


def generate_script(episode_num: int) -> dict:
    """Generate a full episode script with story context for narrative continuity."""

    client = OpenAI()

    # Find the episode arc
    arc = None
    for a in EPISODE_ARCS:
        if a["episode"] == episode_num:
            arc = a
            break

    if not arc:
        # Generate a generic arc for episodes beyond what's predefined
        arc = {
            "episode": episode_num,
            "title": f"Episode {episode_num}",
            "summary": "Continue the ongoing drama with escalating stakes.",
            "cliffhanger": "A shocking revelation that changes everything.",
        }

    # === STORY ENGINE INTEGRATION ===
    story_state = ensure_story_state(episode_num)
    story_context = get_story_context_for_prompt(story_state, episode_num)
    episode_directives = get_episode_directives(episode_num, story_state)
    used_lines = _get_used_lines_from_previous_episodes(episode_num)

    # Build character descriptions with speech patterns
    char_descriptions = ""
    for name, info in CHARACTERS.items():
        char_descriptions += f"\n{info['emoji']} {name} ({info['role']}): {info['personality']}\n"
        char_descriptions += f"   Visual: {info['visual_description']}\n"
        char_descriptions += f"   Speech pattern: {info['speech_pattern']}\n"
        char_descriptions += f"   Available catchphrases: {', '.join(info['catchphrases'])}\n"

    prompt = f"""You are the HEAD WRITER for "Vegetable Hell's Kitchen", a viral AI brainrot short-form series.
You write scripts that feel like unhinged reality TV — characters talk OVER each other, jokes have consequences, and every scene moves the plot forward. You never write filler. You never write generic AI dialogue.

{SHOW_BIBLE}

CHARACTERS:
{char_descriptions}

=== CRITICAL CHARACTER NOTES ===
- Pepper Patricia is a RED CHILI PEPPER (spicy, hot, causes burns). She is NOT a bell pepper. When she gets emotional, she literally heats up, sets things on fire, or causes steam/burns.
- Each character has a DISTINCT speech pattern that must be followed:
  * Chef Tomatino: YELLS IN ALL CAPS. "THIS IS A KITCHEN NOT A DAYCARE!" Short explosive bursts.
  * Celery Steve: N-nervous stuttering. "I... I th-think maybe we should..." Trails off. Repeats words when panicking.
  * Potato Pete: Calm. Philosophical. "The soil teaches patience." One-word devastating comebacks. Never yells.
  * Pepper Patricia: Fierce. Short. Sentences. "Watch me." "Done." "Next." Every line hits like a slap.
  * Onion Olivia: Dramatic monologues even when nobody asked. "When I was just a seedling, I DREAMED of this moment..." Weaponizes crying mid-sentence.
  * Garlic Gary: *whispered* "You and me... we could run this kitchen..." Speaks in conspiratorial asides. Uses ellipses... always implying more.

{story_context}

{used_lines}

{episode_directives}

EPISODE {arc['episode']}: "{arc['title']}"
PLOT: {arc['summary']}
CLIFFHANGER TO END ON: {arc['cliffhanger']}

Generate a complete episode script. The episode MUST be 80-90 seconds when read aloud. This is a HARD requirement — not shorter.
You MUST generate 13-14 scenes. NOT 10. NOT 11. Count them before returning. Average 6 seconds per scene.
This is a continuation of an ongoing story — references to past events should feel natural.

Return ONLY valid JSON (no markdown, no backticks) in this exact format:
{{
    "episode_number": {episode_num},
    "title": "{arc['title']}",
    "scenes": [
        {{
            "scene_number": 1,
            "duration_seconds": 4,
            "type": "hook|setup|drama|confessional|cliffhanger",
            "narration": "The dramatic narrator text for this scene (optional, null if no narration)",
            "dialogue": [
                {{
                    "character": "Character Name",
                    "line": "Their dialogue line",
                    "emotion": "angry|scared|crying|scheming|calm|shocked|dramatic"
                }}
            ],
            "caption_text": "THE BOLD TEXT OVERLAY shown on screen (short, punchy, 5-10 words max)",
            "image_prompt": "A detailed prompt for generating the image. Include: 3D Pixar-style CGI render, specific characters present, their PHYSICAL ACTIONS in the scene, expressions, kitchen setting, dramatic lighting. Be very specific about composition. Do NOT use words like aggressive, human-like, scheming, shifty, or fury.",
            "scene_description": "Brief description of what's happening visually — what characters are DOING, not just feeling",
            "animation_prompt": "Describe what the CHARACTERS physically DO in this scene: gesturing, slamming, pointing, trembling, turning away, throwing ingredients, recoiling in horror, etc. Include physical interactions between characters. Then add camera movement. Must be unique per scene."
        }}
    ],
    "total_duration_seconds": 55,
    "hashtags": ["#VegetableHellsKitchen", "#AIBrainrot", "#plus3more"],
    "video_title": "A catchy YouTube Shorts title with emoji (max 70 chars)",
    "video_description": "A short engaging description for the video"
}}

=== WRITING RULES (NON-NEGOTIABLE) ===

DIALOGUE RULES:
1. NEVER repeat a catchphrase or line that was used in a previous episode. Characters EVOLVE. If a catchphrase was said before, the character must find NEW ways to express that energy. Check the "LINES ALREADY USED" section above.
2. Characters INTERRUPT and REACT to each other. No polite turn-taking. Lines should cut each other off ("—"), respond to what was JUST said, or be reactions ("Wait, WHAT?!"). At least 3 scenes should have characters talking over each other.
3. Every character MUST use their distinct speech pattern (see above). If Tomatino isn't yelling in caps, if Celery isn't stuttering, if Potato isn't dropping one-word philosophy — you've failed.
4. Dialogue must sound like something a SPECIFIC character would say, not generic TV dialogue. Test: cover the character name — can you still tell who's talking from the line alone? If not, rewrite it.

COMEDY RULES:
5. Every joke MUST have a SETUP and PAYOFF within the episode. If someone says something metaphorical (e.g. "I bring the heat"), it must have a LITERAL CONSEQUENCE later (e.g. something catches fire, a counter melts, someone gets burned). No throwaway jokes.
6. At least ONE moment per episode where the "vegetables cooking vegetables" cannibalism undertone surfaces as DARK HUMOR. Not subtle — a character should realize what they're doing and have a visible crisis, or another character should call it out.
7. The narrator is a SNARKY REALITY TV COMMENTATOR who breaks the fourth wall. They address the audience directly ("Yes, you heard that right"), make meta-observations ("This is the part where someone cries — oh wait, there it is"), and editorialize ("I don't get paid enough for this").

STRUCTURE RULES:
8. Generate EXACTLY 13 or 14 scenes. NOT 10, NOT 11, NOT 12. This is non-negotiable. Every scene must ADVANCE THE PLOT. No filler.
9. First scene MUST be a hook that resolves or directly references the previous cliffhanger.
10. Last scene MUST be a NEW cliffhanger.
11. Include at least 2 confessional scenes (character talking directly to camera).
12. Keep total duration between 80-90 seconds. Average 6 seconds per scene across 13-14 scenes.

IMAGE & ANIMATION RULES:
13. Every image_prompt must start with "3D Pixar-style CGI render" and describe the PHYSICAL ACTION happening — characters doing things, not just standing there.
14. Do NOT use these words in image_prompt: aggressive, human-like, scheming, shifty, fury, violent, attack
15. animation_prompt must describe what CHARACTERS PHYSICALLY DO: slamming counters, pointing at each other, recoiling, throwing ingredients, storming off, leaning in conspiratorially. NOT just camera movements. Include character-to-character physical interaction where applicable.
16. Every animation_prompt must be UNIQUE across all scenes.
17. For confessionals: nervous fidgeting, conspiratorial leaning, visible trembling
18. For drama: characters physically confronting each other, objects being thrown/dropped, steam/fire effects
19. caption_text: SHORT, PUNCHY, ALL CAPS. Works as video overlay. 5-10 words max.

POTATO PETE PUNCHLINE RULE (CRITICAL):
20. Before ANY of Potato Pete's one-word or short zen responses (e.g. "Perspective.", "Expanding horizons...", "Growth."), there MUST be a dramatic beat. The narration line before Pete's line should end with "..." to create a pause, OR include a stage direction like "A beat of silence." or "The kitchen falls quiet for a moment." His delivery is a ZEN DROP — it needs silence before it to land as a joke. Never rush into Pete's punchlines. The pause IS the comedy.

TONE: Unhinged reality TV energy. Every vegetable takes themselves dead seriously. The narrator doesn't. Brainrot but with actual narrative craft."""

    print(f"🍅 Generating script for Episode {episode_num}: {arc['title']}...")

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=7000,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the head writer of a hit absurdist reality TV show. "
                    "You write dialogue that sounds like real people (vegetables) "
                    "arguing, scheming, and having breakdowns — not like AI output. "
                    "Every joke has a payoff. Every scene moves the plot. "
                    "Characters have distinct voices and NEVER repeat themselves across episodes. "
                    "You maintain strict narrative continuity. "
                    "Always respond with valid JSON only, no markdown formatting or backticks."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.95,
    )

    # Parse the response
    raw_text = response.choices[0].message.content.strip()

    # Clean up potential markdown wrapping
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

    try:
        script = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"⚠️  JSON parse error: {e}")
        print(f"Raw response:\n{raw_text[:500]}...")
        # Save raw response for debugging
        debug_path = SCRIPTS_DIR / f"ep{episode_num}_raw_debug.txt"
        debug_path.write_text(raw_text)
        print(f"💾 Saved raw response to {debug_path}")
        raise

    # Sanitize image prompts for Flux safety
    for scene in script["scenes"]:
        if scene.get("image_prompt"):
            scene["image_prompt"] = sanitize_image_prompt(scene["image_prompt"])

    # Ensure animation_prompt exists for each scene (fallback if GPT didn't include it)
    for scene in script["scenes"]:
        if not scene.get("animation_prompt"):
            scene["animation_prompt"] = _generate_fallback_motion(scene)

    # Save the script
    script_path = SCRIPTS_DIR / f"ep{episode_num}_script.json"
    with open(script_path, "w") as f:
        json.dump(script, f, indent=2)

    print(f"✅ Script saved to {script_path}")
    print(f"   📋 {len(script['scenes'])} scenes, ~{script.get('total_duration_seconds', '?')}s total")
    print(f"   🎬 Title: {script.get('video_title', 'N/A')}")

    # === UPDATE STORY STATE ===
    story_state = update_state_after_episode(story_state, episode_num, script)
    save_story_state(story_state)

    return script


def _generate_fallback_motion(scene: dict) -> str:
    """Generate a fallback animation prompt if the LLM didn't provide one."""
    scene_type = scene.get("type", "drama")
    scene_num = scene.get("scene_number", 1)
    desc = scene.get("scene_description", "")

    motions = {
        "hook": [
            "Character slams fist on counter, camera shakes slightly, steam erupts from behind",
            "Dramatic zoom into character's face as they deliver shocking line, eyes widen",
            "Character spins around to face camera, spatula raised, kitchen lights flicker",
        ],
        "cliffhanger": [
            "Slow push into character's frozen expression, everything else fades to dark",
            "Character turns slowly toward camera, single spotlight narrows, breath visible",
            "Extreme slow zoom on character's eyes as they widen in shock, background blurs",
        ],
        "confessional": [
            "Character shifts nervously, eyes darting left and right, subtle breathing",
            "Character leans toward camera conspiratorially, eyebrow raised, slight smirk",
            "Character trembles slightly while talking, tears forming, gentle head shake",
        ],
        "setup": [
            "Slow pan across kitchen counter revealing ingredients, steam rising gently",
            "Characters exchange glances nervously, subtle swaying, ambient kitchen movement",
            "Character gestures dramatically at whiteboard, other characters lean back in shock",
        ],
        "drama": [
            "Character points accusingly, other character recoils, sparks fly from stove",
            "Two characters face off, one steaming with rage, the other calm and still",
            "Character drops plate in shock, slow motion shatter effect, others gasp",
            "Character storms across kitchen, other characters part to make way",
            "Character whispers to ally while looking over shoulder, conspiratorial lean",
        ],
    }

    options = motions.get(scene_type, motions["drama"])
    # Use scene_num to pick a different motion deterministically
    return options[scene_num % len(options)]


def print_script(script: dict):
    """Pretty print a script for review."""
    print(f"\n{'='*60}")
    print(f"🎬 EPISODE {script['episode_number']}: {script['title']}")
    print(f"{'='*60}")

    for scene in script["scenes"]:
        print(f"\n--- Scene {scene['scene_number']} [{scene['type'].upper()}] ({scene['duration_seconds']}s) ---")
        print(f"📝 Caption: {scene['caption_text']}")

        if scene.get("narration"):
            print(f"🎙️  Narrator: \"{scene['narration']}\"")

        if scene.get("dialogue"):
            for line in scene["dialogue"]:
                char = line["character"]
                emoji = CHARACTERS.get(char, {}).get("emoji", "❓")
                print(f"   {emoji} {char} [{line['emotion']}]: \"{line['line']}\"")

        if scene.get("animation_prompt"):
            print(f"🎬 Motion: {scene['animation_prompt'][:60]}...")

        print(f"🖼️  Image: {scene['image_prompt'][:80]}...")

    print(f"\n{'='*60}")
    print(f"⏱️  Total: ~{script.get('total_duration_seconds', '?')}s")
    print(f"📱 Title: {script.get('video_title', 'N/A')}")
    print(f"#️⃣  Tags: {' '.join(script.get('hashtags', []))}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys
    ep_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    script = generate_script(ep_num)
    print_script(script)
