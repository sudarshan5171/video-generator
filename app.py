"""
Dual Studio: 9:16 Video Generator
Switch seamlessly between:
  1. ⚡ Code Motion Animations (Claude Animation Skills: Three.js, GSAP, HyperFrames, 1080x1920)
  2. 🤖 Gemini Omni Video AI (Prompt-to-Video generation using Gemini Omni 1.2 Flash & Veo)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import streamlit as st
from PIL import Image

# Add scripts directory to import path
ROOT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from animation_runner import (
    ANIM_EXPORTS_DIR,
    ANIM_REPO,
    ANIM_SKILLS_DIR,
    SKILL_CATALOG,
    prepare_live_preview_html,
    render_animation_skill,
)
from utils import (
    INR_PER_USD,
    MODEL_CONFIGS,
    PROJECTS_DIR,
    Project,
    Scene,
    calculate_image_cost,
    calculate_video_cost,
    edit_clip,
    format_cost_str,
    generate_reference_image,
    generate_single_video,
    generate_storyboard_with_ai,
    generate_voiceover_tts,
    get_api_key,
    get_genai_client,
    get_video_model_config,
    normalize_model_id,
    reroll_scene_visual_prompt,
    slugify,
    stitch_project_clips,
)

# ---------------------------------------------------------------------------
# App Configuration & Styles
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Dual Studio — 9:16 Short Creator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.1rem;
        font-weight: 800;
        background: linear-gradient(90deg, #FF6B6B 0%, #4ECDC4 50%, #45B649 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 2px;
    }
    .sub-header {
        font-size: 1.0rem;
        color: #8892b0;
        margin-bottom: 18px;
    }
    .skill-card {
        background: #1A1D24;
        border: 1px solid #2E3440;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 14px;
    }
    .badge-code {
        background: rgba(78, 205, 196, 0.2);
        color: #4ECDC4;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-ai {
        background: rgba(255, 107, 107, 0.2);
        color: #FF6B6B;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-free {
        background: rgba(69, 182, 73, 0.2);
        color: #45B649;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .cost-card {
        background: #1E222B;
        border: 1px solid #333A48;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar: Engine Mode Switcher
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 🎬 Video Generation Engine")
    
    studio_mode = st.radio(
        "Select Engine Mode",
        options=[
            "⚡ Code Motion Studio (Animation Skills)",
            "🤖 Gemini Omni Studio (Prompt-to-Video)",
        ],
        index=0,
        help="Switch between instant local code animations (Three.js/GSAP) and AI video prompt generation (Gemini Omni / Veo)."
    )

    st.divider()

    if "Code Motion" in studio_mode:
        st.markdown("#### ⚡ Motion Skills Overview")
        st.markdown(
            """
            - **Engine**: Three.js, GSAP, WebGL, HyperFrames
            - **Resolution**: Native vertical **1080x1920 (9:16)**
            - **Cost**: **$0.00 / FREE** (runs 100% locally)
            - **Output**: MP4 video + `.sheet.jpg` contact sheet
            """
        )
        st.caption(f"📁 Skills Source: `claude-animation-skills/`")
        
        # Gallery of recent renders
        st.markdown("---")
        st.markdown("#### 📂 Recent Code Renders")
        recent_mp4s = sorted(ANIM_EXPORTS_DIR.glob("*.mp4"), key=os.path.getmtime, reverse=True)[:5]
        if recent_mp4s:
            for p in recent_mp4s:
                st.caption(f"🎥 `{p.name}` ({p.stat().st_size // 1024} KB)")
        else:
            st.caption("No animations rendered yet.")

    else:
        # Gemini Mode Sidebar
        st.markdown("#### 🤖 Gemini Video Config")
        if "custom_api_key" not in st.session_state:
            st.session_state.custom_api_key = get_api_key()

        with st.expander("🔑 Gemini API Key Status", expanded=not bool(st.session_state.custom_api_key)):
            key_input = st.text_input(
                "Gemini API Key",
                value=st.session_state.custom_api_key,
                type="password",
                help="Requires a Paid Tier Gemini API Key for Gemini Omni video generation.",
            )
            if key_input != st.session_state.custom_api_key:
                st.session_state.custom_api_key = key_input
                st.rerun()

        # Project Selector & Management
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        available_slugs = [
            item.name for item in sorted(PROJECTS_DIR.iterdir())
            if item.is_dir() and not item.name.startswith(".") and ((item / "project.json").exists() or (item / "scenes.json").exists())
        ]
        if not available_slugs:
            available_slugs = ["default_project"]
            p_init = Project(title="Default Project", slug="default_project")
            p_init.save()

        if "active_slug" not in st.session_state or st.session_state.active_slug not in available_slugs:
            st.session_state.active_slug = available_slugs[0]

        selected_slug = st.selectbox(
            "Active Project",
            options=available_slugs,
            index=available_slugs.index(st.session_state.active_slug) if st.session_state.active_slug in available_slugs else 0,
        )
        st.session_state.active_slug = selected_slug

        # Project Actions: New Project & Clear Project
        st.markdown("##### 📁 Project Controls")

        @st.dialog("➕ Create New Project")
        def dialog_new_project():
            new_proj_name = st.text_input("Project Name")
            c_d1, c_d2 = st.columns(2)
            with c_d1:
                if st.button("Create", type="primary", use_container_width=True):
                    if new_proj_name.strip():
                        new_slug = slugify(new_proj_name.strip())
                        if not new_slug:
                            new_slug = f"project_{len(available_slugs) + 1}"
                        new_p = Project(title=new_proj_name.strip(), slug=new_slug)
                        new_p.scenes = [
                            Scene(
                                scene_number=1,
                                id="scene_01",
                                filename="01_scene.mp4",
                                duration_seconds=5,
                                visual_prompt="",
                            )
                        ]
                        new_p.save()
                        st.session_state.active_slug = new_slug
                        st.rerun()
            with c_d2:
                if st.button("Cancel", use_container_width=True):
                    st.rerun()

        @st.dialog("🗑️ Clear Old Data")
        def dialog_clear_data():
            st.write("Choose what you would like to clear:")
            
            # Option 1: Clear current project only
            if st.button(f"🧹 Clear Current Project ({st.session_state.active_slug})", use_container_width=True):
                cur_pdir = Project.get_project_dir(st.session_state.active_slug)
                if cur_pdir.exists():
                    for sub_d in ["references", "drafts_360p", "finals_720p", "exports", "clips", "keyframes"]:
                        target_d = cur_pdir / sub_d
                        if target_d.exists():
                            shutil.rmtree(target_d)
                    cur_proj = Project.load(cur_pdir) or Project(title="Project", slug=st.session_state.active_slug)
                    cur_proj.scenes = [
                        Scene(
                            scene_number=1,
                            id="scene_01",
                            filename="01_scene.mp4",
                            duration_seconds=5,
                            visual_prompt="",
                        )
                    ]
                    cur_proj.voiceover_script = ""
                    cur_proj.save()
                st.rerun()

            st.markdown("---")

            # Option 2: Clear all projects old data
            if st.button("🔥 Clear ALL Old Projects Data", type="primary", use_container_width=True):
                for p_item in PROJECTS_DIR.iterdir():
                    if p_item.is_dir() and not p_item.name.startswith("."):
                        for sub_d in ["references", "drafts_360p", "finals_720p", "exports", "clips", "keyframes"]:
                            target_d = p_item / sub_d
                            if target_d.exists():
                                shutil.rmtree(target_d)
                        clean_proj = Project(title=p_item.name, slug=p_item.name)
                        clean_proj.scenes = [
                            Scene(
                                scene_number=1,
                                id="scene_01",
                                filename="01_scene.mp4",
                                duration_seconds=5,
                                visual_prompt="",
                            )
                        ]
                        clean_proj.save()
                st.rerun()

        c_proj_new, c_proj_clr = st.columns(2)
        with c_proj_new:
            if st.button("➕ New Project", use_container_width=True):
                dialog_new_project()
        with c_proj_clr:
            if st.button("🗑️ Clear Data", use_container_width=True):
                dialog_clear_data()

        pdir = Project.get_project_dir(st.session_state.active_slug)
        project = Project.load(pdir)
        if not project:
            project = Project(title=st.session_state.active_slug, slug=st.session_state.active_slug)
            project.scenes = [
                Scene(
                    scene_number=1,
                    id="scene_01",
                    filename="01_scene.mp4",
                    duration_seconds=5,
                    visual_prompt="",
                )
            ]
            project.save()

        # Omni model selector
        video_model_options = list(MODEL_CONFIGS["video_models"].keys())
        default_video_model = st.selectbox(
            "Video Model",
            options=video_model_options,
            index=0,  # gemini-omni-1.2-flash
        )

# ===========================================================================
# MODE 1: CODE MOTION STUDIO (11 CLAUDE ANIMATION SKILLS)
# ===========================================================================

if "Code Motion" in studio_mode:
    st.markdown('<div class="main-header">⚡ Code Motion Studio</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">'
        'Generate high-retention 9:16 vertical motion graphic reels in pure code '
        '(Three.js, WebGL, GSAP, HyperFrames). 100% offline & zero API cost.'
        '</div>',
        unsafe_allow_html=True,
    )

    skill_names = list(SKILL_CATALOG.keys())
    
    col_nav, col_stage = st.columns([1.1, 2.3])

    with col_nav:
        st.markdown("### 🎨 Select Skill")
        selected_skill_name = st.selectbox(
            "Choose Animation Style",
            options=skill_names,
            format_func=lambda k: f"{SKILL_CATALOG[k]['title']}",
            index=0,
        )

        skill_meta = SKILL_CATALOG[selected_skill_name]
        st.markdown(
            f"""
            <div class="skill-card">
                <span class="badge-code">{skill_meta['badge']}</span> &nbsp;
                <span class="badge-free">1080x1920 (9:16)</span>
                <p style="margin-top:8px; font-size:0.9rem; color:#ccc;">{skill_meta['desc']}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Quick Links / Presets
        st.caption(f"📁 Skill Definition: `skills/{selected_skill_name}/SKILL.md`")

    with col_stage:
        st.markdown(f"### ⚙️ {skill_meta['title']}")

        default_spec = skill_meta["default_spec"]
        
        # Dedicated interactive forms for the most popular skills
        spec_to_run = {}

        if selected_skill_name == "map-route":
            c1, c2 = st.columns(2)
            with c1:
                destination = st.text_input("Destination Name", value=default_spec["destination"])
                distance = st.number_input("Distance", min_value=0.1, max_value=100.0, value=float(default_spec["distance"]), step=0.5)
                unit = st.selectbox("Unit", ["km", "mi"], index=0)
            with c2:
                minutes = st.number_input("Estimated Minutes", min_value=1, max_value=300, value=int(default_spec["minutes"]), step=1)
                accent = st.color_picker("Route Accent Color", value=default_spec["accent"])
                seed = st.number_input("Map Seed (Variation)", min_value=1, max_value=999, value=int(default_spec["seed"]))

            places_str = st.text_input("5 Street/Place Labels (comma-separated)", value=", ".join(default_spec["places"]))
            places_list = [p.strip() for p in places_str.split(",") if p.strip()][:5]

            spec_to_run = {
                "destination": destination,
                "minutes": int(minutes),
                "distance": float(distance),
                "unit": unit,
                "places": places_list,
                "accent": accent,
                "seed": int(seed),
            }

        elif selected_skill_name == "graph":
            c1, c2 = st.columns(2)
            with c1:
                label = st.text_input("Metric Label", value=default_spec["label"])
                final_val = st.number_input("Final Number Landing", min_value=0, max_value=100000000, value=int(default_spec["final"]))
                prefix = st.text_input("Prefix", value=default_spec["prefix"])
                suffix = st.text_input("Suffix", value=default_spec["suffix"])
            with c2:
                dark_mode = st.toggle("Dark Theme (Black Background)", value=default_spec["dark"])
                decimals = st.number_input("Decimals", min_value=0, max_value=3, value=int(default_spec["decimals"]))
                values_str = st.text_input("Data Curve Points (comma-separated)", value=", ".join(str(v) for v in default_spec["values"]))
                labels_str = st.text_input("X-Axis Labels (comma-separated)", value=", ".join(default_spec["labels"]))

            try:
                vals = [float(x.strip()) for x in values_str.split(",") if x.strip()]
            except ValueError:
                vals = default_spec["values"]
            lbls = [x.strip() for x in labels_str.split(",") if x.strip()]

            spec_to_run = {
                "label": label,
                "values": vals,
                "labels": lbls,
                "final": final_val,
                "prefix": prefix,
                "suffix": suffix,
                "decimals": int(decimals),
                "dark": dark_mode,
            }

        elif selected_skill_name == "dan-koe":
            c1, c2 = st.columns(2)
            with c1:
                l1 = st.text_input("Line 1 (Quiet lowercase line)", value=default_spec["lines"][0])
                l2 = st.text_input("Line 2 (Second line swap)", value=default_spec["lines"][1])
            with c2:
                depth = st.slider("Branching Depth", min_value=5, max_value=12, value=int(default_spec["depth"]))
                seed = st.number_input("Tree Seed", min_value=1, max_value=999, value=int(default_spec["seed"]))
                light_mode = st.toggle("Light Background (Default is Pure Black)", value=default_spec["light"])

            spec_to_run = {
                "lines": [l1, l2],
                "depth": int(depth),
                "seed": int(seed),
                "light": light_mode,
            }

        elif selected_skill_name == "kurzgesagt":
            l1 = st.text_input("Header Question", value=default_spec["lines"][0])
            l2 = st.text_input("Middle Context", value=default_spec["lines"][1])
            l3 = st.text_input("Punchline / Answer", value=default_spec["lines"][2])
            tag = st.text_input("Rounded Tag Badge", value=default_spec["tag"])
            spec_to_run = {
                "lines": [l1, l2, l3],
                "tag": tag,
            }

        elif selected_skill_name == "breakdown":
            c1, c2 = st.columns(2)
            with c1:
                title = st.text_input("Device Title", value=default_spec["title"])
                subtitle = st.text_input("Subtitle", value=default_spec["subtitle"])
                accent = st.color_picker("Accent Line Color", value=default_spec["accent"])
            with c2:
                time_str = st.text_input("Screen Clock Time", value=default_spec["time"])
                date_str = st.text_input("Screen Date", value=default_spec["date"])

            st.caption("6 Exploded Layers (Layer name & short spec note):")
            labels = default_spec["labels"]
            spec_to_run = {
                "title": title,
                "subtitle": subtitle,
                "labels": labels,
                "time": time_str,
                "date": date_str,
                "accent": accent,
            }

        elif selected_skill_name == "low-poly":
            c1, c2 = st.columns(2)
            with c1:
                l1 = st.text_input("Caption Line 1", value=default_spec["lines"][0])
                l2 = st.text_input("Caption Line 2", value=default_spec["lines"][1])
            with c2:
                station = st.text_input("Platform Station Sign", value=default_spec["sign"])
                snow = st.toggle("Snow Weather Effect", value=default_spec["snow"])

            spec_to_run = {
                "lines": [l1, l2],
                "sign": station,
                "prev": default_spec.get("prev", "EBISU"),
                "next": default_spec.get("next", "HARAJUKU"),
                "snow": snow,
            }

        elif selected_skill_name == "minecraft":
            c1, c2 = st.columns(2)
            with c1:
                l1 = st.text_input("First Line", value=default_spec["lines"][0])
            with c2:
                l2 = st.text_input("Second Line (Bold Pixel Landing)", value=default_spec["lines"][1])

            spec_to_run = {
                "lines": [l1, l2],
            }

        elif selected_skill_name == "minimalistic-graphics":
            c1, c2 = st.columns(2)
            with c1:
                l1 = st.text_input("Line 1", value=default_spec["lines"][0])
                l2 = st.text_input("Line 2", value=default_spec["lines"][1])
            with c2:
                steps_count = st.slider("Number of Steps", min_value=3, max_value=8, value=int(default_spec["steps"]))
                light_bg = st.toggle("White Background", value=default_spec["light"])

            spec_to_run = {
                "lines": [l1, l2],
                "steps": int(steps_count),
                "light": light_bg,
            }

        elif selected_skill_name == "stick-figure":
            c1, c2 = st.columns(2)
            with c1:
                topic = st.text_input("Explainer Topic / Question", value=default_spec["topic"])
                char1 = st.selectbox("Hero Character", ["hero", "warrior", "detective", "scientist"], index=0)
            with c2:
                char2 = st.selectbox("Counterpart Character", ["doctor", "rival", "boss", "enemy"], index=0)
                voice_tone = st.selectbox("Voice Tone", ["af_bella (Dynamic)", "am_adam (Energetic)"], index=0)
            spec_to_run = {
                "topic": topic,
                "characters": [char1, char2],
                "voice": voice_tone.split()[0],
            }

        elif selected_skill_name == "zach-d-films":
            c1, c2 = st.columns(2)
            with c1:
                topic = st.text_input("3D Cartoon Explainer Question", value=default_spec["topic"])
                char_role = st.selectbox("Focus Character", ["pedestrian", "athlete", "driver", "astronaut"], index=0)
            with c2:
                slow_mo = st.toggle("Slow-Motion Impact Focus", value=True)
                ripple_sfx = st.toggle("Red Force Ripple Overlay", value=True)
            spec_to_run = {
                "topic": topic,
                "character": char_role,
                "slow_motion": slow_mo,
                "ripple_sfx": ripple_sfx,
                "voice": "am_adam",
            }

        else:
            # General JSON Editor for full control
            st.info(f"Using JSON specification for `{selected_skill_name}`:")
            spec_json_str = st.text_area("Spec (JSON)", value=json.dumps(default_spec, indent=2), height=220)
            try:
                spec_to_run = json.loads(spec_json_str)
            except Exception as e:
                st.error(f"Invalid JSON: {e}")
                spec_to_run = default_spec

        # Advanced JSON Overrides Expander
        with st.expander("🛠️ Inspect / Edit Raw JSON Spec"):
            custom_json_input = st.text_area("JSON Payload", value=json.dumps(spec_to_run, indent=2), height=140, key=f"raw_json_{selected_skill_name}")
            try:
                spec_to_run = json.loads(custom_json_input)
            except Exception:
                pass

        # Live Interactive HTML/WebGL Preview Tab
        with st.expander("👁️ Live Interactive Browser Preview", expanded=False):
            preview_html = prepare_live_preview_html(selected_skill_name, spec_to_run)
            if preview_html:
                st.caption("Live 60 FPS animation preview rendered in your browser before export:")
                st.components.v1.html(preview_html, height=480, scrolling=False)
            else:
                st.info("Live interactive preview is available for HTML/Canvas/Three.js skills.")

        # Resolution, Duration & Frame Rate Controls
        st.markdown("#### ⏱️ Video Timing, Script & Canvas Size")
        c_res1, c_res2, c_res3 = st.columns([1.5, 1, 1])
        with c_res1:
            res_options = {
                "1080x1920 (9:16 Vertical Reel / Shorts)": "1080x1920",
                "720x1280 (9:16 Fast HD)": "720x1280",
                "540x960 (9:16 Lightweight Preview)": "540x960",
                "1080x1080 (1:1 Square Feed)": "1080x1080",
                "1920x1080 (16:9 Landscape YouTube)": "1920x1080",
            }
            selected_res_label = st.selectbox(
                "📐 Resolution & Ratio",
                options=list(res_options.keys()),
                index=0,
                help="Select your target canvas size and ratio. Scaled with high-quality Lanczos filtering."
            )
            selected_res_val = res_options[selected_res_label]
        with c_res2:
            duration_hold = st.slider(
                "⏱️ End Hold (seconds)",
                min_value=1.0,
                max_value=10.0,
                value=2.0,
                step=0.5,
                help="How long the final frame and punchline pause on screen before looping."
            )
            spec_to_run["hold"] = float(duration_hold)
        with c_res3:
            fps_choice = st.selectbox(
                "🎞️ Frame Rate",
                options=[30, 60],
                index=0,
                help="30 fps is standard for social reels. 60 fps provides ultra-fluid playback."
            )

        # Execution Controls
        col_btn_snap, col_btn_render = st.columns([1, 1.5])
        with col_btn_snap:
            snap_clicked = st.button("📸 Fast Snapshot (--snap)", use_container_width=True, help="Renders a single high-res frame at t=3.5s in 2 seconds.")
        with col_btn_render:
            render_clicked = st.button(f"⚡ Render Video ({selected_res_val})", type="primary", use_container_width=True)

        if snap_clicked or render_clicked:
            is_snap = bool(snap_clicked)
            action_name = f"snapshot ({selected_res_val})" if is_snap else f"full video ({selected_res_val})"
            
            with st.spinner(f"Rendering {action_name} for '{selected_skill_name}' via HyperFrames…"):
                result = render_animation_skill(
                    skill_name=selected_skill_name,
                    spec=spec_to_run,
                    snap_only=is_snap,
                    snap_time=3.5,
                    resolution=selected_res_val,
                    fps=fps_choice,
                )

            if not result["success"]:
                st.error(f"Render Error:\n{result.get('error')}")
            else:
                st.success(f"Successfully rendered {action_name}!")
                
                # Display output preview
                prev_col1, prev_col2 = st.columns([1.5, 1])
                
                with prev_col1:
                    if result.get("mp4") and result["mp4"].exists():
                        st.video(str(result["mp4"]))
                        with open(result["mp4"], "rb") as f:
                            st.download_button(
                                f"⬇️ Download MP4 ({selected_res_val})",
                                data=f.read(),
                                file_name=f"{selected_skill_name}_{selected_res_val}.mp4",
                                mime="video/mp4",
                                use_container_width=True,
                            )
                
                with prev_col2:
                    if result.get("sheet") and result["sheet"].exists():
                        st.image(str(result["sheet"]), caption="Contact Sheet (with Safe Zone overlay)", use_container_width=True)
                    elif is_snap:
                        # For snap, look for the generated image
                        snap_files = list(ANIM_EXPORTS_DIR.glob(f"{selected_skill_name}*snap*.png")) + list(ANIM_EXPORTS_DIR.glob(f"{selected_skill_name}*.png"))
                        if snap_files:
                            st.image(str(snap_files[-1]), caption="Snap Frame", use_container_width=True)


# ===========================================================================
# MODE 2: GEMINI OMNI VIDEO AI STUDIO (REFERENCE IMAGES -> VIDEO GENERATION)
# ===========================================================================

else:
    st.markdown('<div class="main-header">🤖 Gemini Omni Video AI</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sub-header">'
        f'Upload reference images at one place, specify visual prompt & settings, and generate video directly with Gemini Omni / Veo. '
        f'Project: <b>{project.title}</b> (<code>projects/{project.slug}/</code>)'
        f'</div>',
        unsafe_allow_html=True,
    )

    pdir = project.dir_path()
    refs_dir = pdir / "references"
    drafts_dir = pdir / "drafts_360p"
    finals_dir = pdir / "finals_720p"
    refs_dir.mkdir(parents=True, exist_ok=True)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    finals_dir.mkdir(parents=True, exist_ok=True)

    # Ensure at least 1 scene exists
    if not project.scenes:
        project.scenes = [
            Scene(
                scene_number=1,
                id="scene_01",
                filename="01_scene.mp4",
                duration_seconds=5,
                visual_prompt="",
            )
        ]
        project.save()

    active_scene = project.scenes[0]

    # Two columns: Left (Reference Images & Prompt) | Right (Generated Video & Cost)
    col_input, col_output = st.columns([1.3, 1.2])

    with col_input:
        existing_refs = sorted([f for f in refs_dir.glob("*") if f.is_file() and f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]])

        # Header with Clear Data button
        c_ref_head1, c_ref_head2 = st.columns([2, 1])
        with c_ref_head1:
            st.markdown("### 🖼️ 1. Reference Images")
            st.caption("Upload characters, style references, or scenes. All uploaded images are used for visual continuity.")
        with c_ref_head2:
            if existing_refs:
                if st.button("🗑️ Clear All Images", use_container_width=True):
                    for rf in existing_refs:
                        try:
                            rf.unlink()
                        except Exception:
                            pass
                    st.rerun()

        uploaded_refs = st.file_uploader(
            "Upload reference images",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="single_ref_uploader",
            label_visibility="collapsed"
        )
        if uploaded_refs:
            for f in uploaded_refs:
                dest = refs_dir / (slugify(Path(f.name).stem) + ".png")
                dest.write_bytes(f.getbuffer())
            st.success(f"Added {len(uploaded_refs)} reference image(s)!")
            st.rerun()

        # Refresh existing refs after upload
        existing_refs = sorted([f for f in refs_dir.glob("*") if f.is_file() and f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]])

        # Display current reference images with delete buttons
        if existing_refs:
            st.markdown(f"**Current References ({len(existing_refs)}):**")
            cols = st.columns(min(len(existing_refs), 4))
            for idx, ref_f in enumerate(existing_refs):
                with cols[idx % 4]:
                    st.image(str(ref_f), caption=ref_f.name, use_container_width=True)
                    if st.button("🗑️ Remove", key=f"del_ref_{ref_f.name}", use_container_width=True):
                        try:
                            ref_f.unlink()
                            st.rerun()
                        except Exception:
                            pass
        else:
            st.info("No reference images uploaded yet. (Optional, but recommended for style/character continuity)")

        st.markdown("---")
        st.markdown("### ✍️ 2. Visual Prompt & Generation Settings")

        active_scene.visual_prompt = st.text_area(
            "Visual Prompt (Describe action, mood, camera movements, environment)",
            value=active_scene.visual_prompt,
            height=120,
            key="omni_visual_prompt_input"
        )

        c_opt1, c_opt2 = st.columns(2)
        with c_opt1:
            active_scene.duration_seconds = st.slider(
                "Duration (seconds)",
                min_value=3,
                max_value=15,
                value=int(active_scene.duration_seconds or 5),
                key="omni_duration_slider",
                help="Video length between 3 and 15 seconds."
            )
        with c_opt2:
            res_choice = st.selectbox(
                "Draft Resolution",
                options=["360p", "720p"],
                index=0,
                key="omni_resolution_select",
                help="360p is recommended for fast draft preview."
            )

        # Automatically bind all existing reference images to scene
        active_scene.reference_images = [f.name for f in existing_refs]
        active_scene.draft_model = default_video_model

        # Cost calculation & confirmation
        cost_usd, cost_inr = calculate_video_cost(default_video_model, res_choice, active_scene.duration_seconds)
        st.markdown(
            f"""
            <div class="cost-card">
                <b>Estimated Generation Cost:</b> {format_cost_str(cost_usd, cost_inr)}
                <br><span style="font-size: 0.85rem; color: #8892b0;">Model: <code>{default_video_model}</code> ({res_choice}, {active_scene.duration_seconds}s)</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        confirm_gen = st.checkbox(
            f"I approve this live video generation ({format_cost_str(cost_usd, cost_inr)})",
            key="confirm_omni_gen"
        )

        btn_generate = st.button("🚀 Generate Video with Gemini Omni", type="primary", use_container_width=True)

        if btn_generate:
            if not confirm_gen:
                st.warning("⚠️ Please check the confirmation box above to approve the API generation.")
            elif not active_scene.visual_prompt.strip():
                st.warning("⚠️ Please enter a visual prompt for the video.")
            else:
                project.save()
                try:
                    client = get_genai_client(st.session_state.custom_api_key)
                    with st.spinner("Generating video using Gemini Omni AI…"):
                        out_path = generate_single_video(
                            client,
                            active_scene,
                            pdir,
                            mode="draft" if res_choice == "360p" else "final",
                            custom_model_id=default_video_model
                        )
                    st.success(f"Video generated successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Generation error: {e}")

    with col_output:
        st.markdown("### 🎬 Generated Video")
        
        # Look for generated video
        draft_video = active_scene.draft_path(pdir)
        final_video = active_scene.final_path(pdir)
        display_video = final_video if final_video.exists() else (draft_video if draft_video.exists() else None)

        if display_video and display_video.exists():
            st.video(str(display_video))
            st.caption(f"File: `{display_video.name}` ({display_video.stat().st_size // 1024} KB)")

            with open(display_video, "rb") as vf:
                st.download_button(
                    "⬇️ Download Video (.mp4)",
                    data=vf.read(),
                    file_name=f"{project.slug}_video.mp4",
                    mime="video/mp4",
                    use_container_width=True
                )
        else:
            st.info("No video generated yet for this project. Upload your reference images, write your prompt, and click **Generate Video**.")
