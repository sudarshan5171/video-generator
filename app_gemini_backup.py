"""
Short Studio — 9:16 AI Video Creator (Streamlit App)
A complete browser-based workflow to produce mythological/historical YouTube Shorts
with dynamic AI model switching (Gemini Omni 1.2 Flash, Veo 3.1, Gemini 2.5, Imagen 4.0).
"""

from __future__ import annotations

import os
import shutil
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
# Streamlit App Configuration & Custom Styles
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Short Studio — 9:16 AI Video Creator",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(90deg, #FF6B6B 0%, #FFE66D 50%, #4ECDC4 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #8892b0;
        margin-bottom: 1.5rem;
    }
    .cost-card {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 10px;
        padding: 12px 16px;
        margin-bottom: 12px;
    }
    .scene-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 18px;
        margin-bottom: 20px;
    }
    .status-badge-approved {
        background: rgba(78, 205, 196, 0.2);
        color: #4ECDC4;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.82rem;
    }
    .status-badge-draft {
        background: rgba(255, 230, 109, 0.2);
        color: #FFE66D;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.82rem;
    }
    .status-badge-missing {
        background: rgba(255, 107, 107, 0.2);
        color: #FF6B6B;
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.82rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Session State & Project Discovery
# ---------------------------------------------------------------------------

def discover_projects() -> List[str]:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    slugs = []
    for item in sorted(PROJECTS_DIR.iterdir()):
        if item.is_dir() and not item.name.startswith("."):
            if (item / "project.json").exists() or (item / "scenes.json").exists():
                slugs.append(item.name)
    return slugs


available_slugs = discover_projects()

if "active_slug" not in st.session_state:
    st.session_state.active_slug = available_slugs[0] if available_slugs else None

if "custom_api_key" not in st.session_state:
    st.session_state.custom_api_key = get_api_key()


def load_active_project() -> Optional[Project]:
    if not st.session_state.active_slug:
        return None
    pdir = Project.get_project_dir(st.session_state.active_slug)
    proj = Project.load(pdir)
    return proj


project = load_active_project()

# ---------------------------------------------------------------------------
# Sidebar: Project Manager, Dynamic Models & Live Cost Calculator
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 🎬 Short Studio")
    st.caption("AI-Powered 9:16 YouTube Shorts Producer")

    # API Key Input
    with st.expander("🔑 Gemini API Key Status", expanded=not bool(st.session_state.custom_api_key)):
        key_input = st.text_input(
            "Paid Gemini API Key",
            value=st.session_state.custom_api_key,
            type="password",
            help="Loaded from .env or entered here.",
        )
        if key_input != st.session_state.custom_api_key:
            st.session_state.custom_api_key = key_input
        if st.session_state.custom_api_key:
            st.success("API Key configured")
        else:
            st.warning("Please provide a valid API key.")

    st.divider()

    # Project Selector & Creator
    st.subheader("📂 Project Workspace")
    current_idx = 0
    if available_slugs and st.session_state.active_slug in available_slugs:
        current_idx = available_slugs.index(st.session_state.active_slug)

    selected_slug = st.selectbox(
        "Active Project",
        options=available_slugs,
        index=current_idx if available_slugs else 0,
        help="Select a project folder from projects/",
    )
    if selected_slug and selected_slug != st.session_state.active_slug:
        st.session_state.active_slug = selected_slug
        st.rerun()

    # Form to create a new project
    with st.expander("➕ Create New Project"):
        new_title = st.text_input("Short Title", placeholder="e.g. Fall of Troy")
        if st.button("Create Project", use_container_width=True):
            if new_title.strip():
                new_slug = slugify(new_title)
                new_proj = Project(title=new_title.strip(), slug=new_slug)
                new_proj.save()
                st.session_state.active_slug = new_slug
                st.success(f"Created project: {new_slug}")
                st.rerun()
            else:
                st.error("Please enter a title.")

    st.divider()

    # Default Models Panel
    st.subheader("⚙️ Default Models Panel")

    # 1. Script Model
    script_model_options = [m["id"] for m in MODEL_CONFIGS["script_models"]]
    saved_script = normalize_model_id(project.default_script_model if project else "gemini-3.8-flash")
    script_idx = script_model_options.index(saved_script) if saved_script in script_model_options else 0
    default_script_model = st.selectbox(
        "Script & Storyboard Model",
        options=script_model_options,
        index=script_idx,
        help="Model used to generate voiceover scripts and scenes.",
    )
    custom_script_model = st.text_input("Custom Script Model ID (Optional)", placeholder="e.g. gemini-3.8-flash")
    active_script_model = normalize_model_id(custom_script_model.strip() or default_script_model)

    # 2. Reference Image Model
    image_model_options = [m["id"] for m in MODEL_CONFIGS["image_models"]]
    saved_img = normalize_model_id(project.default_reference_model if project else "gemini-3.1-flash-image")
    img_idx = image_model_options.index(saved_img) if saved_img in image_model_options else 0
    default_image_model = st.selectbox(
        "Reference Image Model",
        options=image_model_options,
        index=img_idx,
        help="Model used to generate 9:16 character and setting stills.",
    )
    custom_image_model = st.text_input("Custom Image Model ID (Optional)", placeholder="e.g. gemini-3.1-flash-image")
    active_image_model = normalize_model_id(custom_image_model.strip() or default_image_model)

    # 3. Draft Video Model
    video_model_options = list(MODEL_CONFIGS["video_models"].keys())
    default_draft_video_model = st.selectbox(
        "Draft Video Model",
        options=video_model_options,
        index=0,  # gemini-omni-1.2-flash
        help="Fast & cheap model for motion and framing tests.",
    )
    custom_draft_video_model = st.text_input("Custom Draft Video Model ID (Optional)")
    active_draft_video_model = custom_draft_video_model.strip() or default_draft_video_model

    # 4. Final Video Model
    default_final_video_model = st.selectbox(
        "Final Video Model",
        options=video_model_options,
        index=0,  # gemini-omni-1.2-flash
        help="High-quality model for approved scenes.",
    )
    custom_final_video_model = st.text_input("Custom Final Video Model ID (Optional)")
    active_final_video_model = custom_final_video_model.strip() or default_final_video_model

    # Apply defaults button
    if project and st.button("Apply Video Model to All Scenes", use_container_width=True):
        for s in project.scenes:
            s.draft_model = active_draft_video_model
            s.final_model = active_final_video_model
        project.default_draft_video_model = active_draft_video_model
        project.default_final_video_model = active_final_video_model
        project.default_script_model = active_script_model
        project.default_reference_model = active_image_model
        project.save()
        st.success("Applied models to all scenes!")
        st.rerun()

    st.divider()

    # Live Cost Calculator
    st.subheader("💰 Live Cost Calculator")
    st.caption("Exchange rate: 1 USD = 85 INR")

    total_draft_usd = 0.0
    total_final_approved_usd = 0.0
    missing_draft_usd = 0.0

    if project:
        pdir = project.dir_path()
        for s in project.scenes:
            # Draft cost
            d_usd, _ = calculate_video_cost(s.draft_model, "360p", s.duration_seconds)
            total_draft_usd += d_usd
            if not s.draft_path(pdir).exists():
                missing_draft_usd += d_usd

            # Approved final cost
            if s.approved:
                f_usd, _ = calculate_video_cost(s.final_model, s.resolution, s.duration_seconds)
                total_final_approved_usd += f_usd

    total_draft_inr = total_draft_usd * INR_PER_USD
    total_final_inr = total_final_approved_usd * INR_PER_USD
    missing_draft_inr = missing_draft_usd * INR_PER_USD

    st.markdown(
        f"""
        <div class="cost-card">
            <div style="font-size:0.85rem; color:#8892b0;">⚡ Total Draft Pass (360p)</div>
            <div style="font-size:1.15rem; font-weight:700; color:#FFE66D;">${total_draft_usd:.3f} USD</div>
            <div style="font-size:0.82rem; color:#aaa;">(~₹{total_draft_inr:.2f} INR)</div>
            <div style="font-size:0.75rem; color:#888; margin-top:4px;">Missing: ${missing_draft_usd:.3f} (~₹{missing_draft_inr:.2f})</div>
        </div>
        <div class="cost-card">
            <div style="font-size:0.85rem; color:#8892b0;">🏆 Approved Finals Pass</div>
            <div style="font-size:1.15rem; font-weight:700; color:#4ECDC4;">${total_final_approved_usd:.3f} USD</div>
            <div style="font-size:0.82rem; color:#aaa;">(~₹{total_final_inr:.2f} INR)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Main Page Header
# ---------------------------------------------------------------------------

st.markdown('<div class="main-header">Short Studio — 9:16 AI Video Creator</div>', unsafe_allow_html=True)
if project:
    st.markdown(f'<div class="sub-header">Working on: <b>{project.title}</b> (<code>projects/{project.slug}/</code>)</div>', unsafe_allow_html=True)
else:
    st.info("No project selected. Create or select a project in the sidebar to get started.")
    st.stop()

# ---------------------------------------------------------------------------
# Tabs Navigation
# ---------------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs([
    "🎬 Tab 1: Studio Director (Visuals & Continuity)",
    "🎙️ Tab 2: Voiceover & Audio",
    "🏆 Tab 3: Final Render & Stitch Short",
])

# ===========================================================================
# TAB 1: Studio Director (Visuals, Prompts & Continuity)
# ===========================================================================

with tab1:
    pdir = project.dir_path()
    refs_dir = pdir / "references"
    drafts_dir = pdir / "drafts_360p"
    finals_dir = pdir / "finals_720p"

    # --- Top Section: Upload / Manage Reference Images for Continuity ---
    with st.expander("🖼️ Upload Reference Images (Characters, Armor, Environment)", expanded=True):
        st.markdown("Upload your character and environment reference stills (PNG / JPEG). These images will lock character appearance, clothing, colors, and environment continuity across your video scenes.")

        col_up, col_preview = st.columns([1.5, 2])
        with col_up:
            uploaded_refs = st.file_uploader(
                "Upload reference stills (up to 6 images)",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                help="Uploaded files will be saved into projects/<project>/references/ and will anchor the visual continuity of your scenes.",
                key="user_ref_file_uploader",
            )
            if uploaded_refs:
                for uploaded_file in uploaded_refs:
                    safe_name = slugify(Path(uploaded_file.name).stem) + ".png"
                    dest_file = refs_dir / safe_name
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    # Convert / Save as standard PNG
                    try:
                        from PIL import Image
                        pil_img = Image.open(uploaded_file)
                        pil_img.save(dest_file, "PNG")
                    except Exception:
                        dest_file.write_bytes(uploaded_file.getbuffer())
                st.success(f"Saved {len(uploaded_refs)} reference image(s) to project!")
                st.rerun()

        with col_preview:
            existing_refs = sorted([f for f in refs_dir.glob("*.png") if f.is_file()])
            if existing_refs:
                st.markdown(f"**Current Reference Gallery ({len(existing_refs)}):**")
                ref_cols = st.columns(min(len(existing_refs), 4))
                for i, ref_file in enumerate(existing_refs):
                    with ref_cols[i % 4]:
                        st.image(str(ref_file), caption=ref_file.name, use_container_width=True)
                        if st.button("🗑️", key=f"del_ref_{ref_file.name}", help=f"Delete {ref_file.name}"):
                            try:
                                ref_file.unlink()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.info("No reference images uploaded yet. Upload reference images above to anchor your character's look.")

        # Optional: AI Image generation sub-expander if user still wants to generate one
        with st.expander("✨ Or Generate Reference Stills with AI (Optional)"):
            st.caption(f"Using Reference Model: `<b>{active_image_model}</b>` (~$0.039/image)", unsafe_allow_html=True)
            chosen_ref_prompt = st.text_area("Reference Visual Prompt (English)", value=project.reference_prompts[0] if project.reference_prompts else "9:16 vertical character portrait still image with cinematic lighting and high detail.", height=70)
            custom_ref_filename = st.text_input("Save As Filename", value="ref_character_1.png")
            img_usd, img_inr = calculate_image_cost(active_image_model)
            confirm_ref = st.checkbox(f"Confirm reference cost ({format_cost_str(img_usd, img_inr)})", key="confirm_ref_gen")
            if st.button("🎨 Generate Reference Still", type="secondary"):
                if not confirm_ref:
                    st.warning("Please confirm cost first.")
                else:
                    try:
                        client = get_genai_client(st.session_state.custom_api_key)
                        out_path = refs_dir / custom_ref_filename
                        with st.spinner(f"Generating reference still…"):
                            generate_reference_image(client, chosen_ref_prompt, out_path, model_id=active_image_model)
                        st.success(f"Generated {custom_ref_filename}!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error: {exc}")

    st.divider()

    # --- Scene Controls & Management ---
    col_sc_head, col_sc_actions = st.columns([2.5, 2])
    with col_sc_head:
        st.subheader("🎬 Scene Prompts & Video Generator")
        st.caption(f"Manage prompts, assign reference images for continuity, and generate video clips. (Max 4 scenes of up to 15s each)")

    with col_sc_actions:
        btn_c1, btn_c2 = st.columns([1, 1])
        with btn_c1:
            if st.button("➕ Add New Scene", use_container_width=True):
                if len(project.scenes) >= 4:
                    st.warning("Maximum of 4 scenes allowed for 1-minute Shorts.")
                else:
                    new_idx = len(project.scenes) + 1
                    project.scenes.append(
                        Scene(
                            scene_number=new_idx,
                            id=f"scene_{new_idx:02d}",
                            filename=f"{new_idx:02d}_scene.mp4",
                            voiceover_segment="",
                            duration_seconds=15,
                            visual_prompt="",
                            draft_model=active_draft_video_model,
                            final_model=active_final_video_model,
                            resolution="360p",
                            approved=False,
                            reference_images=[f.name for f in existing_refs][:6],
                        )
                    )
                    project.save()
                    st.rerun()
        with btn_c2:
            if len(project.scenes) > 1 and st.button("➖ Remove Last Scene", use_container_width=True):
                project.scenes.pop()
                project.save()
                st.rerun()

    # --- Batch Render Missing Drafts ---
    missing_scenes = [s for s in project.scenes if not s.draft_path(pdir).exists()]
    if missing_scenes:
        m_usd = sum(calculate_video_cost(s.draft_model, "360p", s.duration_seconds)[0] for s in missing_scenes)
        m_inr = m_usd * INR_PER_USD
        b_c1, b_c2 = st.columns([3, 1.5])
        with b_c1:
            st.markdown(f"**⚡ Missing Drafts ({len(missing_scenes)} clips):** Estimated cost: {format_cost_str(m_usd, m_inr)}")
        with b_c2:
            confirm_batch_draft = st.checkbox("Confirm batch cost", key="confirm_batch_draft")
            if st.button("⚡ Render All Missing Drafts (360p)", type="primary", use_container_width=True):
                if not confirm_batch_draft:
                    st.warning("Please check the cost confirmation checkbox.")
                else:
                    client = get_genai_client(st.session_state.custom_api_key)
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    for idx, sc in enumerate(missing_scenes):
                        status_text.text(f"Rendering scene {sc.scene_number}/{len(project.scenes)}: {sc.filename} with {sc.draft_model}…")
                        try:
                            generate_single_video(
                                client=client,
                                scene=sc,
                                project_dir=pdir,
                                mode="draft",
                                progress_callback=lambda el: status_text.text(f"Scene {sc.scene_number}: {el}s elapsed…"),
                            )
                        except Exception as e:
                            st.error(f"Scene {sc.id} error: {e}")
                        progress_bar.progress((idx + 1) / len(missing_scenes))
                    st.success("Batch draft rendering finished!")
                    st.rerun()

    st.write("")

    # --- Scene Cards ---
    available_ref_names = [f.name for f in refs_dir.glob("*.png")]

    for s_idx, scene in enumerate(project.scenes):
        draft_exists = scene.draft_path(pdir).exists()
        final_exists = scene.final_path(pdir).exists()

        badge_html = ""
        if final_exists:
            badge_html += ' <span class="status-badge-approved">🏆 FINAL RENDERED</span>'
        elif draft_exists:
            badge_html += ' <span class="status-badge-draft">⚡ DRAFT RENDERED (360p)</span>'
        else:
            badge_html += ' <span class="status-badge-missing">⏳ MISSING</span>'

        if scene.approved:
            badge_html += ' <span class="status-badge-approved">APPROVED FOR FINAL</span>'

        st.markdown(
            f"""
            <div class="scene-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div style="font-size:1.15rem; font-weight:700;">
                        Scene #{scene.scene_number} &nbsp; <code>{scene.id}</code> &nbsp; <i>{scene.filename}</i>
                    </div>
                    <div>{badge_html}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        card_col_media, card_col_controls = st.columns([1, 2])

        with card_col_media:
            # Inline video preview
            if final_exists:
                st.video(str(scene.final_path(pdir)))
                st.caption(f"Showing Final: `{scene.final_path(pdir).name}`")
            elif draft_exists:
                st.video(str(scene.draft_path(pdir)))
                st.caption(f"Showing Draft: `{scene.draft_path(pdir).name}`")
            else:
                st.markdown(
                    """
                    <div style="height:260px; background:rgba(255,255,255,0.02); border:1px dashed #555; border-radius:8px; display:flex; align-items:center; justify-content:center; color:#888;">
                        No clip rendered yet
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        with card_col_controls:
            # Voiceover segment (optional matching)
            sc_vo = st.text_input(
                "Voiceover Line (for narration timing & context)",
                value=scene.voiceover_segment,
                key=f"scene_vo_{scene.id}",
                placeholder="Narration spoken during this clip...",
            )
            scene.voiceover_segment = sc_vo

            # Per-Scene Model Selector & Live Scene Cost
            sc_cfg = get_video_model_config(scene.draft_model)
            cur_usd, cur_inr = calculate_video_cost(scene.draft_model, scene.resolution, scene.duration_seconds)
            st.caption(f"Scene Cost ({scene.resolution}, {scene.duration_seconds}s): **{format_cost_str(cur_usd, cur_inr)}**")

            sc_c1, sc_c2, sc_c3 = st.columns([2, 1, 1])

            with sc_c1:
                # Per-Scene Model Override Selector
                model_keys = list(MODEL_CONFIGS["video_models"].keys())
                model_idx = model_keys.index(scene.draft_model) if scene.draft_model in model_keys else 0
                selected_scene_model = st.selectbox(
                    "Model for this scene",
                    options=model_keys,
                    index=model_idx,
                    key=f"scene_model_{scene.id}",
                )
                scene.draft_model = selected_scene_model

            with sc_c2:
                # Dynamic Duration based on Model constraints
                cfg = get_video_model_config(selected_scene_model)
                if cfg.get("duration_type") == "choices":
                    choices = cfg.get("duration_choices", [4, 6, 8])
                    dur_idx = choices.index(scene.duration_seconds) if scene.duration_seconds in choices else 0
                    scene.duration_seconds = st.selectbox(
                        "Duration (s)",
                        options=choices,
                        index=dur_idx,
                        key=f"scene_dur_{scene.id}",
                    )
                else:
                    # Range 3-15 for Omni
                    scene.duration_seconds = st.slider(
                        "Duration (s)",
                        min_value=3,
                        max_value=15,
                        value=max(3, min(15, scene.duration_seconds)),
                        step=1,
                        key=f"scene_dur_{scene.id}",
                    )

            with sc_c3:
                # Resolution Selector
                res_options = cfg.get("resolutions", ["360p", "720p", "1080p"])
                res_idx = res_options.index(scene.resolution) if scene.resolution in res_options else 0
                scene.resolution = st.selectbox(
                    "Resolution",
                    options=res_options,
                    index=res_idx,
                    key=f"scene_res_{scene.id}",
                )

            # Editable Visual Prompt
            st.markdown("**Visual Prompt (English — describe scene motion, action, and angle):**")
            scene.visual_prompt = st.text_area(
                "Visual Prompt",
                value=scene.visual_prompt,
                key=f"scene_prompt_{scene.id}",
                height=90,
                label_visibility="collapsed",
                placeholder="e.g. Cinematic 9:16 vertical shot. The hero warrior steps forward into the mist, drawing his bow. Molten golden embers float in the air...",
            )

            # Reference Images Multiselect for Strict Continuity
            scene.reference_images = st.multiselect(
                "Attached Reference Images (Locks Continuity)",
                options=available_ref_names,
                default=[r for r in scene.reference_images if r in available_ref_names][:6],
                max_selections=6,
                key=f"scene_refs_{scene.id}",
                help="Select uploaded reference stills to anchor this character and environment look.",
            )

            # Approval Checkbox
            scene.approved = st.checkbox(
                "Approve for Final Render (Tab 3)",
                value=scene.approved,
                key=f"scene_appr_{scene.id}",
            )

            # Action Buttons Row
            btn_col1, btn_col2 = st.columns([1, 1])

            with btn_col1:
                clip_usd, clip_inr = calculate_video_cost(scene.draft_model, "360p", scene.duration_seconds)
                confirm_single_clip = st.checkbox(
                    f"Confirm {format_cost_str(clip_usd, clip_inr)}",
                    key=f"confirm_single_{scene.id}",
                )
                if st.button("🚀 Render This Clip", key=f"retry_btn_{scene.id}", use_container_width=True):
                    if not confirm_single_clip:
                        st.warning("Check confirmation to proceed.")
                    else:
                        project.save()
                        try:
                            client = get_genai_client(st.session_state.custom_api_key)
                            with st.spinner(f"Generating clip with {scene.draft_model}…"):
                                generate_single_video(
                                    client=client,
                                    scene=scene,
                                    project_dir=pdir,
                                    mode="draft",
                                )
                            st.success(f"Generated {scene.filename}!")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Error generating clip: {exc}")

            with btn_col2:
                # Conversational Edit Expander
                with st.expander("🛠️ Quick Conversational Edit"):
                    target_clip_for_edit = scene.final_path(pdir) if final_exists else scene.draft_path(pdir)
                    if not target_clip_for_edit.exists():
                        st.caption("Render a clip first to use conversational editing.")
                    else:
                        edit_instruction = st.text_input(
                            "Edit instruction",
                            placeholder="e.g. Add lightning flashes and make clouds darker",
                            key=f"edit_instr_{scene.id}",
                        )
                        edit_usd, edit_inr = calculate_video_cost("gemini-omni-1.2-flash", "360p", scene.duration_seconds)
                        confirm_edit = st.checkbox(f"Confirm edit ({format_cost_str(edit_usd, edit_inr)})", key=f"conf_edit_{scene.id}")
                        if st.button("Apply Edit to Clip", key=f"apply_edit_{scene.id}"):
                            if not confirm_edit:
                                st.warning("Please confirm cost.")
                            else:
                                try:
                                    client = get_genai_client(st.session_state.custom_api_key)
                                    with st.spinner("Applying edit…"):
                                        edit_clip(
                                            client=client,
                                            input_clip_path=target_clip_for_edit,
                                            edit_prompt=edit_instruction,
                                            output_clip_path=target_clip_for_edit,
                                            model_id=scene.draft_model,
                                        )
                                    st.success("Edit applied!")
                                    st.rerun()
                                except Exception as exc:
                                    st.error(f"Edit error: {exc}")

        st.markdown("---")

    # Save any changes in scene settings to project.json
    project.save()


# ===========================================================================
# TAB 2: Voiceover & Audio
# ===========================================================================

with tab2:
    pdir = project.dir_path()
    audio_dest = pdir / "exports" / "voiceover.mp3"

    st.markdown("### 🎙️ Voiceover & Audio Studio")
    st.caption("Write your voiceover script, generate high-quality AI speech using Gemini preset voice models, or upload your audio file.")

    col_script, col_audio = st.columns([3, 2])

    with col_script:
        st.subheader("📜 Voiceover Script")
        edited_script = st.text_area(
            "Full Voiceover Script (Editable)",
            value=project.voiceover_script,
            height=260,
            placeholder="Write or paste your voiceover script here in any language (Hindi, English, etc.)...",
            help="Refine your script here. Click Save Script to update project.json.",
        )
        if st.button("💾 Save Script Changes"):
            project.voiceover_script = edited_script
            project.save()
            st.success("Voiceover script saved!")

        with st.expander("📋 Copy Voiceover for ElevenLabs"):
            st.caption("Paste this text into ElevenLabs or your external TTS tool:")
            st.code(project.voiceover_script, language="text")

        with st.expander("✨ AI Storyboard & Script Assistant (Optional)"):
            st.caption("Need inspiration? You can ask AI to generate an outline or script:")
            ai_idea_notes = st.text_input("Story Idea or Topic", value=project.idea)
            ai_lang = st.selectbox("Script Language", ["Hindi (हिंदी)", "English", "Hinglish", "Spanish", "Tamil", "Telugu"])
            if st.button("🪄 Draft Script & Scenes with AI"):
                if not ai_idea_notes.strip():
                    st.error("Please enter a story idea.")
                else:
                    try:
                        client = get_genai_client(st.session_state.custom_api_key)
                        with st.spinner("Drafting storyboard with AI…"):
                            storyboard = generate_storyboard_with_ai(
                                client=client,
                                title=project.title,
                                idea=ai_idea_notes,
                                language=ai_lang,
                                target_duration=project.target_duration,
                                model_id=active_script_model,
                            )
                            project.voiceover_script = storyboard.voiceover_script
                            project.idea = ai_idea_notes
                            project.save()
                            st.success("Drafted script loaded into editor!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    with col_audio:
        st.subheader("🔊 Audio Generation & Upload")
        vo_tab_ai, vo_tab_upload = st.tabs(["🤖 Gemini Voice Generator", "📤 Upload Audio (.mp3/.wav)"])

        with vo_tab_ai:
            st.caption("Generate speech directly using Gemini preset voice models:")
            voice_options = {
                "Charon": "Charon (Deep, solemn, authoritative male — great for mythology)",
                "Puck": "Puck (Energetic, narrative, engaging male)",
                "Fenrir": "Fenrir (Intense, deep, resonant male)",
                "Kore": "Kore (Warm, calm, expressive female)",
                "Aoede": "Aoede (Melodic, dramatic, clear female)",
            }
            selected_voice_key = st.selectbox(
                "Voice Personality",
                options=list(voice_options.keys()),
                format_func=lambda k: voice_options[k],
                index=0,
                help="Choose a prebuilt voice personality for your voiceover narration.",
            )

            confirm_tts = st.checkbox("Confirm voiceover generation", key="confirm_tts")
            if st.button("🔊 Generate Voiceover", type="primary", use_container_width=True):
                if not project.voiceover_script.strip():
                    st.error("Voiceover script is empty. Write or paste a script in the box on the left.")
                elif not confirm_tts:
                    st.warning("Please check the confirmation box.")
                else:
                    try:
                        client = get_genai_client(st.session_state.custom_api_key)
                        with st.spinner(f"Generating voiceover with voice '{selected_voice_key}'…"):
                            generate_voiceover_tts(
                                client=client,
                                text=project.voiceover_script,
                                output_mp3_path=audio_dest,
                                voice_name=selected_voice_key,
                            )
                        st.success(f"Voiceover generated and saved to exports/voiceover.mp3!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error generating voiceover: {exc}")

        with vo_tab_upload:
            uploaded_audio = st.file_uploader(
                "Upload Voiceover Audio (.mp3 or .wav)",
                type=["mp3", "wav"],
                help="Uploaded audio is saved to exports/voiceover.mp3 and will be auto-stitched into the final video in Tab 3.",
            )
            if uploaded_audio is not None:
                audio_dest.parent.mkdir(parents=True, exist_ok=True)
                with open(audio_dest, "wb") as f:
                    f.write(uploaded_audio.getbuffer())
                st.success("Voiceover audio saved to exports/voiceover.mp3")

        st.markdown("---")
        if audio_dest.exists() and audio_dest.stat().st_size > 0:
            st.markdown("**Current Audio Track:**")
            st.audio(str(audio_dest))
            st.caption(f"Ready for Tab 3: `{audio_dest.name}` ({audio_dest.stat().st_size // 1024} KB)")
        else:
            st.info("No audio track generated or uploaded yet.")

# ===========================================================================
# TAB 3: Final Render & Stitch Full Short
# ===========================================================================

with tab3:
    pdir = project.dir_path()
    finals_dir = pdir / "finals_720p"
    drafts_dir = pdir / "drafts_360p"
    exports_dir = pdir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    stitched_output_path = exports_dir / "stitched_short.mp4"
    voiceover_path = exports_dir / "voiceover.mp3"

    st.markdown("### 🏆 Final Render & Video Stitching")
    st.caption("Render approved scenes at native high resolution and stitch the complete 9:16 YouTube Short.")

    # 1. Render Approved Finals
    approved_scenes = [s for s in project.scenes if s.approved]
    final_cost_usd = sum(calculate_video_cost(s.final_model, s.resolution, s.duration_seconds)[0] for s in approved_scenes)
    final_cost_inr = final_cost_usd * INR_PER_USD

    col_fin_info, col_fin_action = st.columns([3, 2])
    with col_fin_info:
        st.subheader("1. Render Approved Finals")
        st.markdown(f"Approved scenes: **{len(approved_scenes)}** of **{len(project.scenes)}**")
        st.markdown(f"Total Final Render Cost: **{format_cost_str(final_cost_usd, final_cost_inr)}**")

    with col_fin_action:
        if approved_scenes:
            # Guardrail for 1080p/4k
            has_high_res = any(s.resolution in ("1080p", "4k") for s in approved_scenes)
            allow_upsampled = True
            if has_high_res:
                allow_upsampled = st.checkbox("⚠️ Allow 1080p/4K resolution (costs more)", value=False)

            confirm_final = st.checkbox("Confirm final render cost", key="confirm_final_render")
            if st.button("🌟 Render Approved Finals", type="primary", use_container_width=True):
                if not confirm_final:
                    st.warning("Please check the cost confirmation checkbox.")
                elif has_high_res and not allow_upsampled:
                    st.error("Some scenes are set to 1080p/4K. Please check 'Allow 1080p/4K resolution' to proceed.")
                else:
                    client = get_genai_client(st.session_state.custom_api_key)
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    for idx, sc in enumerate(approved_scenes):
                        status_text.text(f"Rendering final scene {sc.scene_number}: {sc.filename} ({sc.final_model}, {sc.resolution})…")
                        try:
                            generate_single_video(
                                client=client,
                                scene=sc,
                                project_dir=pdir,
                                mode="final",
                                progress_callback=lambda el: status_text.text(f"Final scene {sc.scene_number}: {el}s elapsed…"),
                            )
                        except Exception as e:
                            st.error(f"Scene {sc.id} final render error: {e}")
                        progress_bar.progress((idx + 1) / len(approved_scenes))
                    st.success("Approved finals rendered successfully!")
                    st.rerun()
        else:
            st.info("No scenes are marked 'Approved for Final Render' yet. Go to Tab 2 and check 'Approve for Final Render' on approved scenes.")

    st.divider()

    # 2. Scene Sequence Checklist
    st.subheader("2. Sequence & Assembly Checklist")
    st.caption("The stitcher will assemble the clips in order, using high-res finals where available and falling back to 360p drafts.")

    clips_to_stitch = []
    checklist_data = []

    for s in project.scenes:
        fin_path = s.final_path(pdir)
        dft_path = s.draft_path(pdir)
        if fin_path.exists():
            status = "🏆 Final (High-Res)"
            chosen_clip = fin_path
        elif dft_path.exists():
            status = "⚡ Draft (360p)"
            chosen_clip = dft_path
        else:
            status = "❌ Missing"
            chosen_clip = None

        if chosen_clip:
            clips_to_stitch.append(chosen_clip)

        checklist_data.append({
            "Scene #": s.scene_number,
            "ID": s.id,
            "Duration": f"{s.duration_seconds}s",
            "Model": s.final_model if fin_path.exists() else s.draft_model,
            "Clip Source": status,
            "Voiceover Line": s.voiceover_segment[:50] + "..." if len(s.voiceover_segment) > 50 else s.voiceover_segment,
        })

    st.dataframe(checklist_data, use_container_width=True)

    st.divider()

    # 3. Stitch Video & Audio
    st.subheader("3. Add Clips Together (Stitch Video)")

    col_stitch_opts, col_stitch_btn = st.columns([2, 1])
    with col_stitch_opts:
        has_voiceover = voiceover_path.exists() and voiceover_path.stat().st_size > 0
        merge_vo = st.checkbox(
            "Merge Voiceover Audio (exports/voiceover.mp3)",
            value=has_voiceover,
            help="If checked, replaces clip audio with the uploaded voiceover track.",
        )
        if has_voiceover:
            st.caption(f"Audio detected: `{voiceover_path.name}` ({voiceover_path.stat().st_size // 1024} KB)")
        else:
            st.caption("No voiceover audio found in `exports/voiceover.mp3`. You can upload one in Tab 1.")

    with col_stitch_btn:
        stitch_btn = st.button("🎬 Add Clips Together (Stitch Video)", type="primary", use_container_width=True)

    if stitch_btn:
        if not clips_to_stitch:
            st.error("No rendered clips found to stitch. Please render drafts or finals first.")
        else:
            with st.spinner(f"Stitching {len(clips_to_stitch)} clips into {stitched_output_path.name} with FFmpeg…"):
                audio_file = voiceover_path if (merge_vo and has_voiceover) else None
                ok, msg = stitch_project_clips(
                    clip_paths=clips_to_stitch,
                    output_path=stitched_output_path,
                    audio_path=audio_file,
                )
                if ok:
                    st.success(f"Video stitched successfully! Saved to {stitched_output_path}")
                    st.rerun()
                else:
                    st.error(f"Stitching failed: {msg}")

    # 4. Final Video Player & Download
    if stitched_output_path.exists() and stitched_output_path.stat().st_size > 0:
        st.subheader("📺 Final Stitched YouTube Short")
        col_preview, col_download = st.columns([1, 2])
        with col_preview:
            st.video(str(stitched_output_path))
        with col_download:
            size_mb = stitched_output_path.stat().st_size / (1024 * 1024)
            st.markdown(f"**File:** `stitched_short.mp4` ({size_mb:.2f} MB)")
            st.markdown("Format: 9:16 Vertical MP4 (720x1280 @ 30fps H.264/AAC)")
            with open(stitched_output_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download stitched_short.mp4",
                    data=f,
                    file_name=f"{project.slug}_stitched_short.mp4",
                    mime="video/mp4",
                    type="primary",
                )
