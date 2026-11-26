import json
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ANIM_REPO = ROOT_DIR / "claude-animation-skills"
ANIM_SKILLS_DIR = ANIM_REPO / "skills"
ANIM_KIT_DIR = ANIM_REPO / "kit"
ANIM_EXPORTS_DIR = ROOT_DIR / "animation_exports"
ANIM_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

SKILL_CATALOG = {
    "map-route": {
        "title": "🗺️ Map Route (3D City)",
        "badge": "Three.js / 3D",
        "desc": "A clean white 3D city with parks & river. Colored route draws itself from start to destination, red pin bounces, and ETA counts down.",
        "default_spec": {
            "destination": "Iron Yard Gym",
            "minutes": 9,
            "distance": 2.8,
            "unit": "km",
            "places": ["North Quay", "Botanic Gardens", "Market Hall", "Elm Park", "The Canal"],
            "accent": "#2f7cf6",
            "seed": 7
        }
    },
    "graph": {
        "title": "📈 Graph / Stat Count-Up",
        "badge": "GSAP Motion",
        "desc": "A smooth line draws itself on dark/light grid while a big headline number counts up with the tip to its final value.",
        "default_spec": {
            "label": "Followers",
            "values": [1.2, 2.1, 3.4, 5.0, 9.0, 24.0, 51.0, 78.0, 100.0],
            "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"],
            "final": 100000,
            "prefix": "",
            "suffix": "",
            "decimals": 0,
            "dark": True
        }
    },
    "dan-koe": {
        "title": "🧠 Dan Koe Style (Minimal B&W)",
        "badge": "Canvas / Line Art",
        "desc": "A single white dot on pure black grows into a hairline tree that splits at every step, the tips light up with pulse ring & sparks, and quiet lines swap.",
        "default_spec": {
            "lines": ["one choice.", "then the next."],
            "depth": 9,
            "seed": 5,
            "light": False
        }
    },
    "kurzgesagt": {
        "title": "🪐 Kurzgesagt Space Explainer",
        "badge": "Vector Space",
        "desc": "Flat vector space explainer shot. Deep navy-purple space, twinkling stars, flat planets lit from one side with dark crescent and soft glow.",
        "default_spec": {
            "lines": ["Could every planet fit", "between Earth and the Moon?", "At its farthest, yes."],
            "tag": "They all fit"
        }
    },
    "breakdown": {
        "title": "📱 3D Exploded View Breakdown",
        "badge": "Three.js / 3D",
        "desc": "A floating 3D phone comes apart layer by layer (glass, display, frame, board, battery, back) with leader lines & labels.",
        "default_spec": {
            "title": "Phone",
            "subtitle": "Exploded view",
            "labels": [
                ["Cover glass", "toughened · 0.6 mm"],
                ["OLED display", "6.3 in · 120 Hz"],
                ["Titanium frame", "grade 5 · 7.8 mm"],
                ["Logic board", "3 nm chip · 8 GB"],
                ["Battery", "3,582 mAh"],
                ["Back glass", "matte · magnet ring"]
            ],
            "time": "9:41",
            "date": "Saturday 1 November",
            "accent": "#F08A5D"
        }
    },
    "low-poly": {
        "title": "🐕 Low-Poly Retro 3D (PS1 / N64)",
        "badge": "Three.js / Retro",
        "desc": "PS1/N64 era chunky low-poly aesthetic with wobbly vertices, dithering and flat warm lighting. The train platform snow scene.",
        "default_spec": {
            "lines": ["he waited every day", "for almost 10 years"],
            "sign": "SHIBUYA",
            "prev": "EBISU",
            "next": "HARAJUKU",
            "snow": True
        }
    },
    "minecraft": {
        "title": "🧱 Minecraft Voxel Builder",
        "badge": "Three.js / Voxel",
        "desc": "Minecraft-style blocky voxel cottage that builds itself block by block with bounce, dust puffs, warm glowing windows, and rising smoke.",
        "default_spec": {
            "lines": ["block by block", "home."]
        }
    },
    "minimalistic-graphics": {
        "title": "🪜 Minimalistic Line Steps",
        "badge": "Minimal Motion",
        "desc": "Thin outlined geometric steps rise one by one, a white dot hops up them, an orbit draws around it, and quiet typography shifts.",
        "default_spec": {
            "lines": ["every step feels small.", "until you look back."],
            "steps": 5,
            "light": False
        }
    },
    "stick-figure": {
        "title": "✏️ Stick Figure Explainer",
        "badge": "Engine (Voice + Story)",
        "desc": "2D cartoon reel with thick outlines, expressive stick characters, whip transitions, and word-by-word timed captions.",
        "default_spec": {
            "topic": "What if you stopped sleeping for 7 days?",
            "characters": ["hero", "doctor"],
            "voice": "af_bella"
        }
    },
    "zach-d-films": {
        "title": "🩺 Zack D. Films 3D Explainer",
        "badge": "Engine / 3D Cartoon",
        "desc": "3D cartoon 'what if' explainer short in Zack D. Films style. Procedural characters, slow-motion impacts, red force ripples & whip cuts.",
        "default_spec": {
            "topic": "Could a penny dropped from the Empire State Building kill you?",
            "character": "pedestrian",
            "voice": "am_adam"
        }
    }
}


def prepare_live_preview_html(skill_name: str, spec: dict) -> str:
    """
    Generates a standalone HTML document with embedded CSS/JS and the spec injected,
    ready to render inside an iframe for instant 60 FPS live preview.
    """
    skill_dir = ANIM_SKILLS_DIR / skill_name
    template_path = skill_dir / "template.html"
    if not template_path.exists():
        return ""

    html_content = template_path.read_text(encoding="utf-8")
    data = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/")
    
    # Calculate duration
    dur = 4.0
    if skill_name == "dan-koe":
        depth = spec.get("depth", 9)
        dur = 0.3 + (depth - 1) * 0.25 + 0.27 + 1.43
    elif skill_name == "map-route":
        dur = 4.5
    elif skill_name == "graph":
        dur = 4.0
    elif skill_name == "minimalistic-graphics":
        dur = 4.0
    elif skill_name == "kurzgesagt":
        dur = 4.5
    elif skill_name == "breakdown":
        dur = 5.0
    elif skill_name == "low-poly":
        dur = 5.0
    elif skill_name == "minecraft":
        dur = 4.5

    filled = html_content.replace("__SPEC__", data).replace("__DURATION__", f"{dur:.3f}")

    # Inject local absolute / direct paths for GSAP and Three.js so iframe loads without broken relative links
    vendor_gsap = (ANIM_KIT_DIR / "vendor" / "gsap.min.js").read_text(encoding="utf-8", errors="ignore")
    # In-line GSAP
    filled = filled.replace('<script src="vendor/gsap.min.js"></script>', f'<script>{vendor_gsap}</script>')
    filled = filled.replace('<script src="../vendor/gsap.min.js"></script>', f'<script>{vendor_gsap}</script>')

    return filled


def render_animation_skill(
    skill_name: str,
    spec: dict,
    snap_only: bool = False,
    snap_time: float = 3.5,
    resolution: str = "1080x1920",
    fps: int = 30,
) -> dict:
    """
    Renders an animation skill using claude-animation-skills build.py or engine.
    Supports resolution scaling (e.g. 1080x1920, 720x1280, 1920x1080, 1080x1080).
    Returns a dict with paths to the generated mp4, sheet, and status.
    """
    skill_dir = ANIM_SKILLS_DIR / skill_name
    build_py = skill_dir / "build.py"
    
    if not build_py.exists():
        return {
            "success": False,
            "error": f"Skill '{skill_name}' does not have build.py entrypoint."
        }

    output_stem = f"{skill_name}_{os.getpid()}"
    spec_path = ANIM_EXPORTS_DIR / f"{output_stem}.spec.json"
    
    # Save spec
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)

    cmd = [sys.executable, str(build_py), str(spec_path)]
    if snap_only:
        cmd.extend(["--snap", str(snap_time)])

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ANIM_EXPORTS_DIR),
            capture_output=True,
            text=True,
            check=True
        )
        
        mp4_path = ANIM_EXPORTS_DIR / f"{output_stem}.spec.mp4"
        sheet_path = ANIM_EXPORTS_DIR / f"{output_stem}.spec.sheet.jpg"

        # Apply custom resolution scaling if requested and video exists
        if mp4_path.exists() and not snap_only and resolution and resolution != "1080x1920":
            try:
                target_w, target_h = [int(x) for x in resolution.split("x")]
                scaled_mp4 = ANIM_EXPORTS_DIR / f"{output_stem}.{resolution}.mp4"
                scale_cmd = [
                    "ffmpeg", "-y", "-i", str(mp4_path),
                    "-vf", f"scale={target_w}:{target_h}:flags=lanczos",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
                    "-c:a", "copy",
                    str(scaled_mp4)
                ]
                subprocess.run(scale_cmd, capture_output=True, text=True, check=True)
                if scaled_mp4.exists():
                    mp4_path = scaled_mp4
            except Exception as e:
                print(f"Resolution scaling note: {e}")

        # If snapshot was requested and needs scaling
        snap_files = list(ANIM_EXPORTS_DIR.glob(f"{output_stem}*snap*.png"))
        if snap_only and snap_files and resolution and resolution != "1080x1920":
            try:
                target_w, target_h = [int(x) for x in resolution.split("x")]
                orig_snap = snap_files[-1]
                scaled_snap = ANIM_EXPORTS_DIR / f"{output_stem}.{resolution}.snap.png"
                scale_cmd = [
                    "ffmpeg", "-y", "-i", str(orig_snap),
                    "-vf", f"scale={target_w}:{target_h}:flags=lanczos",
                    str(scaled_snap)
                ]
                subprocess.run(scale_cmd, capture_output=True, text=True, check=True)
            except Exception:
                pass
        
        return {
            "success": True,
            "mp4": mp4_path if mp4_path.exists() else None,
            "sheet": sheet_path if sheet_path.exists() else None,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }
    except subprocess.CalledProcessError as exc:
        return {
            "success": False,
            "error": exc.stderr or exc.stdout or str(exc)
        }
