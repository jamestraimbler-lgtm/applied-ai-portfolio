"""
Story Engine - Maintains narrative continuity across episodes.

Tracks character relationships, alliances, rivalries, elimination order,
ongoing plot threads, and cliffhanger resolutions. Provides full story
context to GPT-4o for consistent, evolving narrative.
"""

import json
from pathlib import Path
from config import PROJECT_DIR, SCRIPTS_DIR

STORY_STATE_PATH = PROJECT_DIR / "story_state.json"

# Default initial state (Episode 0 - before the show starts)
DEFAULT_STATE = {
    "current_episode": 0,
    "eliminated": [],
    "remaining_contestants": [
        "Chef Tomatino", "Celery Steve", "Potato Pete",
        "Pepper Patricia", "Onion Olivia", "Garlic Gary"
    ],
    "relationships": {
        "Pepper Patricia -> Garlic Gary": {"type": "alliance", "strength": 7, "notes": "Secret pact formed before the show"},
        "Pepper Patricia -> Potato Pete": {"type": "rivalry", "strength": 6, "notes": "Pepper sees Potato as beneath her"},
        "Onion Olivia -> Celery Steve": {"type": "manipulation", "strength": 5, "notes": "Olivia uses Steve's anxiety"},
        "Garlic Gary -> Onion Olivia": {"type": "alliance", "strength": 4, "notes": "Gary sees Olivia as useful"},
        "Celery Steve -> Chef Tomatino": {"type": "fear", "strength": 9, "notes": "Steve terrified of Tomatino"},
        "Potato Pete -> Celery Steve": {"type": "friendship", "strength": 3, "notes": "Pete quietly watches out for Steve"},
    },
    "plot_threads": {
        "tomatino_fruit_secret": {
            "status": "dormant",
            "description": "Tomatino is technically a fruit. This secret could destroy his authority.",
            "known_by": [],
            "reveal_episode": None,
        },
        "garlic_double_agent": {
            "status": "active",
            "description": "Gary is forming alliances with everyone while secretly playing all sides.",
            "known_by": [],
            "evidence_count": 0,
        },
        "celery_underdog_arc": {
            "status": "active",
            "description": "Celery Steve keeps surprising everyone with unexpected competence.",
            "confidence_level": 1,  # 1-10
            "near_eliminations": 0,
        },
        "olivia_manipulation": {
            "status": "active",
            "description": "Onion Olivia manipulates others using tears and emotional outbursts.",
            "known_by": [],
            "victims": ["Celery Steve"],
        },
        "pepper_potato_rivalry": {
            "status": "active",
            "description": "Pepper looks down on Potato, but Potato keeps outperforming expectations.",
            "escalation_level": 2,  # 1-10
        },
        "cannibalism_question": {
            "status": "dormant",
            "description": "The existential horror of vegetables cooking with vegetables.",
            "addressed_in_episodes": [],
        },
    },
    "character_arcs": {
        "Chef Tomatino": {
            "current_state": "authoritative",
            "arc_direction": "toward identity crisis",
            "key_moments": [],
            "emotional_state": "angry but in control",
        },
        "Celery Steve": {
            "current_state": "terrified but surviving",
            "arc_direction": "underdog rising",
            "key_moments": [],
            "emotional_state": "anxious, near breakdown",
        },
        "Potato Pete": {
            "current_state": "quietly observing",
            "arc_direction": "dark horse emerging",
            "key_moments": [],
            "emotional_state": "zen, philosophical",
        },
        "Pepper Patricia": {
            "current_state": "dominant, aggressive",
            "arc_direction": "hubris before fall",
            "key_moments": [],
            "emotional_state": "overconfident",
        },
        "Onion Olivia": {
            "current_state": "playing victim",
            "arc_direction": "villain reveal",
            "key_moments": [],
            "emotional_state": "calculated crying",
        },
        "Garlic Gary": {
            "current_state": "scheming in shadows",
            "arc_direction": "exposure incoming",
            "key_moments": [],
            "emotional_state": "smug, overplaying hand",
        },
    },
    "cliffhangers": {
        "previous": None,
        "current": None,
    },
    "episode_summaries": [],
    "running_jokes": [
        "Celery's family is in a Bloody Mary",
        "Potato Pete's one-word devastating responses",
        "Tomatino saying 'wrong show' after Ramsay-like moments",
        "Everyone crying when Olivia enters the room",
        "Nobody can see Gary coming but they smell him",
    ],
    "eliminated_contestants": [],
    "drama_meter": 5,  # 1-10, escalates each episode
}


def load_story_state() -> dict:
    """Load the current story state from disk, or create default."""
    if STORY_STATE_PATH.exists():
        with open(STORY_STATE_PATH) as f:
            return json.load(f)
    return DEFAULT_STATE.copy()


def save_story_state(state: dict):
    """Persist story state to disk."""
    with open(STORY_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
    print(f"   💾 Story state saved ({STORY_STATE_PATH.name})")


def initialize_from_episode_1(state: dict) -> dict:
    """Bootstrap story state from Episode 1's events."""
    state["current_episode"] = 1
    state["cliffhangers"]["current"] = (
        "Chef Tomatino tasted Celery Steve's dish and went completely silent. "
        "In this kitchen, silence means either genius... or someone's about to get composted."
    )
    state["episode_summaries"].append({
        "episode": 1,
        "title": "Welcome to the Kitchen",
        "key_events": [
            "Contestants arrived and were introduced",
            "Challenge: cook a dish with NO vegetable ingredients",
            "Pepper trash-talked Potato (Potato was unbothered)",
            "Onion Olivia made everyone cry during her intro",
            "Garlic Gary revealed his scheming nature in confessional",
            "Celery Steve dropped a tray but recovered",
            "Potato Pete delivered philosophical monologue about versatility",
            "Tomatino grudgingly approved Pepper's dish",
            "Celery Steve served a surprisingly elegant dish",
            "Tomatino went SILENT after tasting it",
        ],
        "character_developments": {
            "Celery Steve": "Showed unexpected competence despite constant anxiety",
            "Potato Pete": "Established himself as the quiet philosopher/dark horse",
            "Pepper Patricia": "Established dominance but may be overconfident",
            "Garlic Gary": "Already forming alliances in secret",
            "Onion Olivia": "Emotional manipulation already in effect",
            "Chef Tomatino": "Authority established but silent reaction to Steve hints at depth",
        },
        "cliffhanger": "Tomatino silently tasting Celery's dish — is it genius or garbage?",
    })

    # Update character arcs
    state["character_arcs"]["Celery Steve"]["key_moments"].append(
        "Ep1: Served a surprisingly elegant dish that stunned Tomatino"
    )
    state["character_arcs"]["Potato Pete"]["key_moments"].append(
        "Ep1: 'You can boil me, mash me, fry me. I always come back. That's not a flex. That's a warning.'"
    )
    state["character_arcs"]["Pepper Patricia"]["key_moments"].append(
        "Ep1: Got grudging respect from Tomatino for her dish"
    )
    state["character_arcs"]["Garlic Gary"]["key_moments"].append(
        "Ep1: 'Nobody sees the garlic coming... but they always smell it.'"
    )

    # Update plot threads
    state["plot_threads"]["celery_underdog_arc"]["confidence_level"] = 3
    state["plot_threads"]["garlic_double_agent"]["evidence_count"] = 1
    state["plot_threads"]["pepper_potato_rivalry"]["escalation_level"] = 3
    state["plot_threads"]["cannibalism_question"]["addressed_in_episodes"].append(1)

    state["drama_meter"] = 6

    return state


def update_state_after_episode(state: dict, episode_num: int, script: dict) -> dict:
    """Update story state based on what happened in the generated script.

    This should be called after a script is generated and finalized.
    It extracts key events, relationship changes, and the new cliffhanger.
    """
    state["current_episode"] = episode_num

    # Move current cliffhanger to previous
    state["cliffhangers"]["previous"] = state["cliffhangers"]["current"]

    # Extract cliffhanger from last scene
    last_scene = script["scenes"][-1]
    cliffhanger_text = ""
    if last_scene.get("narration"):
        cliffhanger_text = last_scene["narration"]
    elif last_scene.get("dialogue"):
        last_line = last_scene["dialogue"][-1]
        cliffhanger_text = f"{last_line['character']}: \"{last_line['line']}\""
    elif last_scene.get("caption_text"):
        cliffhanger_text = last_scene["caption_text"]

    state["cliffhangers"]["current"] = cliffhanger_text

    # Build episode summary
    key_events = []
    character_developments = {}

    for scene in script["scenes"]:
        if scene.get("narration"):
            key_events.append(scene["narration"])
        for line in scene.get("dialogue", []):
            char = line["character"]
            if char not in character_developments:
                character_developments[char] = []

    state["episode_summaries"].append({
        "episode": episode_num,
        "title": script.get("title", f"Episode {episode_num}"),
        "key_events": key_events[:10],
        "cliffhanger": cliffhanger_text,
    })

    # Escalate drama
    state["drama_meter"] = min(10, state["drama_meter"] + 1)

    return state


def get_story_context_for_prompt(state: dict, episode_num: int) -> str:
    """Generate a rich story context string for the GPT-4o script generation prompt.

    This gives the AI everything it needs to maintain narrative continuity.
    """
    context_parts = []

    # === Previous episodes recap ===
    if state["episode_summaries"]:
        context_parts.append("=== STORY SO FAR ===")
        for summary in state["episode_summaries"]:
            context_parts.append(f"\nEPISODE {summary['episode']}: \"{summary['title']}\"")
            for event in summary.get("key_events", []):
                context_parts.append(f"  • {event}")
            if summary.get("cliffhanger"):
                context_parts.append(f"  CLIFFHANGER: {summary['cliffhanger']}")

    # === Cliffhanger resolution ===
    if state["cliffhangers"].get("current"):
        context_parts.append(f"\n=== UNRESOLVED CLIFFHANGER (must resolve THIS episode) ===")
        context_parts.append(state["cliffhangers"]["current"])

    # === Character status ===
    context_parts.append("\n=== CHARACTER STATUS ===")
    for char, arc in state["character_arcs"].items():
        context_parts.append(f"\n{char}:")
        context_parts.append(f"  State: {arc['current_state']}")
        context_parts.append(f"  Arc direction: {arc['arc_direction']}")
        context_parts.append(f"  Emotional state: {arc['emotional_state']}")
        if arc["key_moments"]:
            context_parts.append(f"  Key moments: {'; '.join(arc['key_moments'][-3:])}")

    # === Active relationships ===
    context_parts.append("\n=== RELATIONSHIPS ===")
    for pair, rel in state["relationships"].items():
        context_parts.append(f"  {pair}: {rel['type']} (strength {rel['strength']}/10) — {rel['notes']}")

    # === Active plot threads ===
    context_parts.append("\n=== ACTIVE PLOT THREADS ===")
    for thread_id, thread in state["plot_threads"].items():
        if thread["status"] == "active":
            context_parts.append(f"  [{thread_id}]: {thread['description']}")

    # === Elimination status ===
    if state["eliminated"]:
        context_parts.append(f"\n=== ELIMINATED ===")
        for elim in state["eliminated"]:
            context_parts.append(f"  {elim}")

    context_parts.append(f"\n=== REMAINING CONTESTANTS ===")
    context_parts.append(f"  {', '.join(state['remaining_contestants'])}")

    # === Running jokes to callback ===
    if state["running_jokes"]:
        context_parts.append(f"\n=== RUNNING JOKES (reference 1-2 of these) ===")
        for joke in state["running_jokes"]:
            context_parts.append(f"  • {joke}")

    # === Drama level ===
    context_parts.append(f"\n=== DRAMA METER: {state['drama_meter']}/10 ===")
    context_parts.append("(Each episode should escalate. More dramatic reveals, bigger conflicts, higher stakes.)")

    return "\n".join(context_parts)


def get_episode_directives(episode_num: int, state: dict) -> str:
    """Get specific narrative directives for this episode number."""

    directives = {
        2: """
EPISODE 2 SPECIFIC DIRECTIVES:
- MUST open by resolving Ep1's cliffhanger: Tomatino tasting Celery's dish in silence
- The resolution should be SURPRISING — not what the audience expects
- Introduce the "cannibalism question" as the central conflict
- Celery Steve's confidence should grow slightly (but he's still anxious)
- Garlic Gary should be seen whispering to at least 2 different people
- Pepper should get increasingly frustrated that others are getting attention
- End with a NEW cliffhanger that sets up Episode 3
- Someone should almost get eliminated (or get eliminated)
- The narrator should make at least one dark cannibalism joke
- Keep the brainrot energy: short punchy lines, meme-worthy moments
- At least one character should have a confessional that becomes a meme format
""",
        3: """
EPISODE 3 SPECIFIC DIRECTIVES:
- A fruit character enters the competition (Strawberry)
- The vegetables are xenophobic about fruits
- Tomatino's fruit identity becomes a ticking time bomb
- Garlic Gary should try to use the fruit drama to his advantage
- Pepper and Strawberry should have a confrontation
- Potato Pete should be the voice of reason (as always)
- The cannibalism question from Ep2 should still linger
""",
        4: """
EPISODE 4 SPECIFIC DIRECTIVES:
- Tomatino's fruit identity is revealed or nearly revealed
- Garlic uses this information as leverage
- Celery accidentally makes another incredible dish
- The competition narrows — stakes feel higher
- Alliances start to fracture
- Onion Olivia's manipulation should be more obvious to the audience
""",
        5: """
EPISODE 5 SPECIFIC DIRECTIVES:
- Garlic Gary's double-dealing is fully exposed
- Maximum drama — kitchen erupts into chaos
- Unexpected elimination or twist
- Tomatino must make a difficult decision
- This should feel like a season finale
- Biggest emotional moments of the series
""",
    }

    return directives.get(episode_num, f"""
EPISODE {episode_num} DIRECTIVES:
- Continue escalating the drama
- Develop at least 2 character arcs
- Reference at least 1 running joke
- Introduce a new conflict or complication
- End on a cliffhanger that makes viewers NEED episode {episode_num + 1}
""")


def ensure_story_state(episode_num: int) -> dict:
    """Ensure story state exists and is caught up to the requested episode.

    If we're generating episode 2 but have no state, bootstrap from ep1.
    """
    state = load_story_state()

    # If state is at episode 0 and we're generating ep2+, bootstrap from ep1
    if state["current_episode"] == 0 and episode_num >= 2:
        # Check if ep1 script exists
        ep1_script_path = SCRIPTS_DIR / "ep1_script.json"
        if ep1_script_path.exists():
            state = initialize_from_episode_1(state)
            save_story_state(state)
            print("   📖 Bootstrapped story state from Episode 1")

    return state


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "init":
        state = DEFAULT_STATE.copy()
        state = initialize_from_episode_1(state)
        save_story_state(state)
        print("✅ Story state initialized from Episode 1")
        print(f"\n📖 Story context preview:\n")
        print(get_story_context_for_prompt(state, 2)[:2000])
    elif len(sys.argv) > 1 and sys.argv[1] == "show":
        state = load_story_state()
        print(json.dumps(state, indent=2))
    else:
        print("Usage: python story_engine.py [init|show]")
        print("  init - Initialize story state from Episode 1")
        print("  show - Display current story state")
