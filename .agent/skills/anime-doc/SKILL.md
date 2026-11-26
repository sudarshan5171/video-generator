# Anime-Doc Skill (16:9 Classic 90s Anime + Tactical War Maps)

## Purpose
Produce 16:9 (1920x1080) long-form historical and mythological documentary chapters in a unified 1990s cel-animation style (*Ramayana: The Legend of Prince Rama*) combined with matching watercolor-parchment 2D tactical diagrams.

## Pipeline Rules
1. **Audio-First Timing:**
   - Measure `./vo.mp3` duration first. Total video length = `audio_duration + 1.0s` tail padding.
   - Run word-level alignment against the provided Hindi script to drive exact scene cuts and rolling 3–5 word Devanagari subtitles.

2. **Visual Generation (API-Assisted):**
   - For every narrative/character beat (every 6–10 seconds), generate a 16:9 PNG using:
     `python .agent/skills/anime-doc/generate_frame.py --prompt "<scene>" --out "./assets/frames/scene_XX.png"`
   - **Character Consistency:** Keep identical visual descriptors across all prompts (e.g., *Arjuna: tall warrior, golden Mukut crown, dark blue dhoti, white Gandiva bow*; *Krishna: blue-skinned charioteer, peacock feather in crown, yellow Pitambara*; *Bhishma: towering elder warrior, white beard, silver-white armor and cape*).
   - Reuse already-generated frames in `./assets/frames/` on re-renders unless the user explicitly asks to regenerate a specific scene.

3. **Zero Static Frames (HTML/GSAP Motion Layer):**
   - Animate every generated PNG inside a `1920x1080` HTML/GSAP stage:
     - **Camera Motion:** Smooth Ken Burns slow zoom-in (`scale 1.0 -> 1.12`), slow pan left/right, or dramatic punch-zoom + micro-shake on impact lines.
     - **Atmospheric Canvas Overlay:** Subtle drifting golden dust/embers, wind streaks, or anime speed-lines on action beats.
     - **Transitions:** Clean 0.35s cross-dissolves or fast whip-pans with whoosh SFX.

4. **Watercolor Tactical Maps (Vyuha & Battlefield Diagrams):**
   - Whenever the script explains a military formation (Vyuha) or troop movement, render a top-down 2D Canvas/SVG diagram styled to match the anime palette:
     - Warm parchment/terracotta watercolor background (no plain black grids).
     - Hand-inked dark brown/gold formation lines, glowing directional arrows, and clean Hindi/English badges in dark semi-transparent pills.

5. **Hindi Captions & Final Mix:**
   - Place rolling Devanagari subtitles at **Y: 88%** (safe 16:9 bottom zone) inside a dark semi-transparent pill with gold keyword highlights.
   - Mix `./vo.mp3` with subtle code-generated SFX (-14 dB) in FFmpeg and render final `1920x1080` 30fps MP4.