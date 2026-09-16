# Character definitions and world-building for script generation

CHARACTERS = {
    "Chef Tomatino": {
        "emoji": "🍅",
        "role": "Head Chef / Judge",
        "personality": "Explosive, red-faced (literally), screams at everyone. Sweats marinara when angry. Has a secret soft side for Basil. Technically a fruit but living a lie as a vegetable.",
        "visual_description": "A large, round, angry tomato with a tall white chef hat, thick eyebrows, tiny muscular arms, wearing a white chef coat with sauce stains. Always red-faced and yelling.",
        "speech_pattern": "YELLS EVERYTHING IN ALL CAPS. Short explosive bursts. Interrupts constantly. Uses cooking metaphors as insults.",
        "catchphrases": [
            "You call this a SALAD?! I call it a CRIME SCENE!",
            "You're so raw, the garden wants you BACK!",
            "SHUT IT DOWN! This kitchen is a COMPOST HEAP!",
            "I've seen better plating in a COMPOST BIN!",
            "You donkey! Wait... wrong show.",
        ],
    },
    "Celery Steve": {
        "emoji": "🥬",
        "role": "The Nervous Wreck",
        "personality": "Tall, thin, constantly trembling. Cries peanut butter. Always apologizing. Somehow keeps surviving eliminations through pure luck.",
        "visual_description": "A tall, pale green celery stalk with huge anxious eyes, wearing an oversized chef hat that keeps falling over his eyes. Visibly shaking. Very thin and gangly.",
        "speech_pattern": "N-nervous stuttering. Trails off mid-sentence... Starts talking then panics. Self-deprecating. Repeats words when scared (no no no no).",
        "catchphrases": [
            "I'm sorry, Chef... I'll try to be less bland...",
            "Please don't chop me...",
            "I know I'm mostly water, but these are REAL tears!",
        ],
    },
    "Potato Pete": {
        "emoji": "🥔",
        "role": "The Underdog",
        "personality": "Quiet, unassuming, thick-skinned. Everyone underestimates him. Has hidden depth. Surprisingly philosophical. Dark horse to win.",
        "visual_description": "A round, brown potato with calm half-closed eyes, small smile, wearing a simple apron. Looks plain but has a wise, knowing expression. Slightly dirty.",
        "speech_pattern": "Calm, measured, philosophical. Speaks in short zen-like statements. One-word devastating responses. Never raises voice. Drops profound truth bombs casually.",
        "catchphrases": [
            "I may look plain, but I'm versatile.",
            "Mash me, fry me, bake me — I always deliver.",
            "You can't judge a potato by its skin.",
        ],
    },
    "Pepper Patricia": {
        "emoji": "🌶️",
        "role": "The Hot-Head Rival",
        "personality": "A RED CHILI PEPPER — not a bell pepper. Fiery competitor, literally hot to the touch. Starts beef with everyone. Secret alliance with Garlic. Too spicy for her own good. Steams when angry. Sets things on fire when emotional.",
        "visual_description": "A sleek red chili pepper with fierce eyes, long eyelashes, wearing a stylish red bandana. Flames occasionally flicker from her stem. Confident pose. Visibly radiates heat.",
        "speech_pattern": "Fierce. Short. Sentences. Like punches. Never explains herself. Drops mic constantly. Every line is a threat or a flex.",
        "catchphrases": [
            "I bring the HEAT, baby!",
            "If you can't handle me, get out of the kitchen.",
            "That dish needs ME. Everything does.",
        ],
    },
    "Onion Olivia": {
        "emoji": "🧅",
        "role": "The Emotional Manipulator",
        "personality": "Makes everyone cry — literally and emotionally. Layers of personality. Master of dramatic monologues. Has a villain arc brewing.",
        "visual_description": "A golden-brown onion with large teary eyes, mascara running, wearing a pearl necklace. Multiple visible layers. Always on the verge of (or actively) crying.",
        "speech_pattern": "Dramatic monologues. Speaks in soliloquies even when nobody asked. References her own pain constantly. Third-person self-references. Starts crying mid-sentence then weaponizes it.",
        "catchphrases": [
            "You don't know my LAYERS!",
            "*sobbing* This isn't tears, it's PASSION!",
            "I didn't come here to make friends. I came here to make you CRY.",
        ],
    },
    "Garlic Gary": {
        "emoji": "🧄",
        "role": "The Schemer",
        "personality": "Small but powerful. Everyone can smell him coming. Forms alliances then backstabs. The strategic mastermind of the competition.",
        "visual_description": "A small garlic bulb with shifty, half-closed eyes, wearing a tiny black turtleneck. Looks suspicious at all times. Always whispering. Has a goatee drawn on.",
        "speech_pattern": "Whispered scheming. Speaks in asides to camera. Uses 'we' to include people in plans they didn't agree to. Ellipses everywhere... always implying more. Finishes others' sentences.",
        "catchphrases": [
            "I may be small, but I make EVERYTHING better.",
            "Nobody saw that coming... but they smelled it.",
            "Alliances are like garlic bread — better when you crush them.",
        ],
    },
}

SHOW_BIBLE = """
SHOW: Vegetable Hell's Kitchen
FORMAT: 30-60 second vertical short-form episodes (TikTok/YouTube Shorts/Reels)
GENRE: AI Brainrot / Surreal Comedy / Reality TV Parody

PREMISE:
A cooking competition show where ALL contestants and judges are anthropomorphic 3D vegetables.
The dark comedic tension: they're cooking dishes potentially made from other vegetables (cannibalism undertone).
The vegetables take everything EXTREMELY seriously. The narrator treats it like a BBC war documentary.
The contrast between the ridiculous premise and the dead-serious execution IS the comedy.

VISUAL STYLE:
- 3D Pixar/DreamWorks-style rendering
- Vibrant, dramatic kitchen lighting
- Over-the-top facial expressions
- Kitchen set with oversized utensils
- Think: if Pixar had a nervous breakdown in a Gordon Ramsay kitchen

TONE:
- Absurd + Dramatic + Self-Aware
- Every vegetable takes themselves WAY too seriously
- Reality TV tropes played completely straight (confessionals, dramatic music cues, cliffhangers)
- The cannibalism question is always lurking but never fully addressed

EPISODE STRUCTURE:
1. HOOK (0-3 seconds): Shocking statement or dramatic moment to stop scrolling
2. SETUP (3-10 seconds): Establish the challenge or conflict
3. DRAMA (10-35 seconds): Character interactions, cooking chaos, arguments
4. CLIFFHANGER (35-45 seconds): Episode ends on an unresolved dramatic moment

KEY RULES:
- Every episode MUST end on a cliffhanger
- At least one character should yell or cry per episode
- Include at least one absurd food-related pun or joke
- The "cannibalism" tension should surface at least subtly
- Narrator should be overly dramatic like a nature documentary
"""

EPISODE_ARCS = [
    {
        "episode": 1,
        "title": "Welcome to the Kitchen",
        "summary": "Contestants arrive. Chef Tomatino establishes dominance. First challenge revealed: cook a dish WITHOUT using any vegetable ingredients. Celery panics. Pepper trash-talks Potato. Onion cries during her intro.",
        "cliffhanger": "Chef Tomatino tastes Celery's dish and goes completely silent for 10 seconds...",
    },
    {
        "episode": 2,
        "title": "The Cannibalism Question",
        "summary": "When Carrot Carl serves carrot soup, the kitchen goes SILENT. Moral crisis erupts. Is cooking with vegetables... murder? Onion has a breakdown. Potato gives a philosophical speech. Elimination: Lettuce Linda is sent home for being 'too forgettable'.",
        "cliffhanger": "A mysterious new contestant arrives — a FRUIT. The vegetables are NOT happy.",
    },
    {
        "episode": 3,
        "title": "Fruit Infiltration",
        "summary": "Strawberry has entered. Cross-kingdom drama. Vegetables form alliance against fruit intruder. Pepper and Strawberry screaming match. Potato defends Strawberry. Chef Tomatino reveals HE'S technically a fruit. Identity crisis.",
        "cliffhanger": "Chef Tomatino whispers: 'I've been living a lie...'",
    },
    {
        "episode": 4,
        "title": "Tomatino's Secret",
        "summary": "Chef Tomatino's fruit identity crisis continues. Garlic uses this information to manipulate others. Pepper tries to get Tomatino disqualified. Celery accidentally makes an incredible dish. Onion delivers a monologue about acceptance.",
        "cliffhanger": "Garlic is caught whispering to BOTH teams. Double agent revealed.",
    },
    {
        "episode": 5,
        "title": "The Great Betrayal",
        "summary": "Garlic's double-dealing exposed. Kitchen erupts. Pepper accuses Potato of being Garlic's ally. Celery drops a pot on his own foot. Chef Tomatino must decide: eliminate Garlic or respect the game?",
        "cliffhanger": "Chef Tomatino: 'The one going home tonight... is ME.'",
    },
]
