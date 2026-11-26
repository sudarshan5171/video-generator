# Video Generator — Agent Rules

## Safety: Never Run Live Without Explicit Permission

- **Never** execute `generate_videos.py`, `generate_references.py`, or `edit_clip.py`
  without the `--dry-run` flag unless the user has **explicitly** said to run it live
  in that message (e.g., "run it now", "generate for real", "execute — no dry-run").
- When in doubt, always add `--dry-run` and show the cost estimate first, then ask the
  user to confirm before proceeding.

## Default Model & Rendering Settings

- **Model**: always default to `gemini-omni-1.2-flash`. Never substitute another model
  unless the user explicitly requests it.
- **Aspect ratio**: always `9:16` vertical for all video and reference image generation.
- **Draft resolution**: always `360p`. Never draft at 720p, 1080p, or 4K.
- **Final resolution**: always `720p` for approved finals. Never generate at `1080p` or
  `4K` unless the user explicitly passes `--allow-upsampled` and confirms the cost.
- **Never** suggest or use `1080p` or `4K` as a default or recommendation.

## Duration: Always Explicit, Always Matched to Voiceover

- Every scene **must** have an explicit `duration_seconds` value between 3 and 15.
- The value must be matched to the actual voiceover or narration length for that scene.
- **Never** default to the maximum (15s) blindly. If the voiceover timing is unknown,
  ask the user before writing or editing `scenes.json`.
