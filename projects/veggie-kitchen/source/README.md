# Archived video pipeline source

The original 14 Python modules are included for review, together with their
historical dependency list. Start with `generate_episode.py`, then
`script_generator.py`, `image_generator.py`, `animate_scenes.py`,
`voice_generator.py`, `whisper_sync.py` and `video_assembler.py`.

The code joins scene descriptions, generated media, subtitle timing and FFmpeg
assembly. `characters.py` holds the fictional cast; `story_engine.py` handles
continuity. Legacy upload/comment experiments and the one-off episode repair
script are preserved source, not part of a verified publishing workflow.

The pipeline requires provider credentials, FFmpeg and generated intermediate
assets. Its dependency list and provider names are historical; a fresh provider
run was not performed. Some scripts execute work directly when run or imported.
Use the offline portfolio verifier for syntax checking without invoking them.

Personal provider configuration, account tokens, generated bulk assets and
upload credentials are excluded. The finished episode is a retained artifact,
not evidence that the entire pipeline can be rerun unchanged today.

[Project and preview](../README.md)
