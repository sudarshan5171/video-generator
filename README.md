# 🎬 Short Studio — Browser-Based 9:16 AI Video Creator

A complete, browser-based **Streamlit Short Studio (`app.py`)** for generating, editing, and stitching viral 9:16 vertical mythological & historical YouTube Shorts using the official `google-genai` SDK and paid Gemini API keys.

---

## 🚀 Quick Start (Browser UI)

Launch the full interactive studio in your browser:

```bash
# 1. Activate virtual environment
source .venv/bin/activate

# 2. Launch Streamlit Studio
streamlit run app.py
```

The browser UI will open automatically at `http://localhost:8501`.

---

## 🌟 Key Features

1. **Multi-Model Dynamic Registry:**
   - **Script & Storyboard:** `gemini-2.5-flash` (Default), `gemini-2.5-pro`
   - **Reference Images:** `gemini-2.5-flash-image` (Default), `imagen-4.0-fast-generate-001`, `imagen-4.0-generate-001`
   - **Video Generation:**
     - `gemini-omni-1.2-flash` (Default): 3–15s slider, 360p ($0.023/s), 720p ($0.070/s), 1080p ($0.104/s)
     - `veo-3.1-lite-generate-001`: 4, 6, 8s selector, 720p ($0.050/s), 1080p ($0.080/s)
     - `veo-3.1-fast-generate-preview`: 4, 6, 8s selector, 720p ($0.100/s), 1080p ($0.120/s), 4k ($0.300/s)
     - `veo-3.1-generate-preview`: 4, 6, 8s selector, 720p ($0.400/s), 1080p ($0.400/s), 4k ($0.600/s)
   - **Custom Model ID Overrides:** Text input overrides for every category to test new Gemini/Veo model strings without touching code.

2. **Step-by-Step 3-Tab Workflow:**
   - **Tab 1: Idea & Voiceover Script:**
     - AI Storyboard generator using Pydantic Structured Outputs.
     - Automatically creates a 1-minute voiceover script timed for ElevenLabs, 5–8 scene breakdowns with visual prompts, and 2–3 reference prompts.
     - Copyable ElevenLabs block + direct audio upload (`voiceover.mp3`).
   - **Tab 2: References & Scene Clips:**
     - Collapsible Reference Images gallery & 9:16 PNG generator for character/costume consistency.
     - **Batch Render Missing Drafts** at 360p.
     - **Scene-by-Scene Cards:** inline video player, per-scene model selector, dynamic duration/resolution controls, reference image multiselect, "Save & Retry", and multi-turn conversational editing.
     - Approval checkbox (`approved: true`) for final render gating.
   - **Tab 3: Final Render & Stitch Short:**
     - Renders approved scenes at high resolution (720p default; 1080p/4K unlocked via confirmation).
     - Sequence checklist showing clip source (final preferred, draft fallback).
     - **"Add Clips Together (Stitch Video)"** using `imageio-ffmpeg` to concatenate all 9:16 clips and merge voiceover audio.
     - Inline video preview + direct download button for `stitched_short.mp4`.

3. **Live Cost Calculator & Guardrails:**
   - Real-time USD and INR calculations (`1 USD = 85 INR`).
   - Zero automatic paid API calls on page load — every generation requires an explicit button click and cost confirmation checkbox.

---

## 📁 Project Structure

```
video-generator/
├── app.py                     # Browser-based Streamlit Short Studio
├── requirements.txt           # Python dependencies
├── .env.example               # Copy to .env and set GEMINI_API_KEY
├── .gitignore                 # Excludes .env, .venv/, projects/, __pycache__/
├── scripts/
│   ├── utils.py               # Shared models, registry, schemas, stitcher & polling
│   ├── generate_references.py # CLI: Imagen reference stills
│   ├── generate_videos.py     # CLI: Draft & Final video rendering
│   └── edit_clip.py           # CLI: Multi-turn conversational editing
└── projects/
    └── sample_short/          # Example project
        ├── project.json       # Title, script, scenes, models configuration
        ├── references/        # 9:16 character and background PNGs
        ├── drafts_360p/       # 360p motion test clips
        ├── finals_720p/       # High-res approved final clips
        └── exports/           # stitched_short.mp4 & voiceover.mp3
```

---

## 🛠️ CLI Usage (Optional)

You can also run stages directly from the command line using `--dry-run`:

```bash
# 1. Preview reference stills plan
python scripts/generate_references.py projects/sample_short --dry-run

# 2. Preview 360p draft video generation plan
python scripts/generate_videos.py projects/sample_short --mode draft --dry-run

# 3. Preview 720p approved finals plan
python scripts/generate_videos.py projects/sample_short --mode final --dry-run

# 4. Preview conversational clip edit plan
python scripts/edit_clip.py \
    --clip projects/sample_short/drafts_360p/01_zeus_thunderbolt.mp4 \
    --edit-prompt "Change the sky to a blood-red sunset." \
    --output projects/sample_short/drafts_360p/01_zeus_thunderbolt_v2.mp4 \
    --dry-run
```
