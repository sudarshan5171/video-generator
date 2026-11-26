"""
Shared utilities, model registry, Pydantic schemas, and media processing
for the Short Studio 9:16 YouTube Shorts pipeline.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from dotenv import load_dotenv
import imageio_ffmpeg
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Directories & Constants
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT_DIR / "projects"
INR_PER_USD = 85.0
POLL_INTERVAL_SECONDS = 10
COST_PER_IMAGE_IMAGEN = 0.039
DEFAULT_MODEL = "gemini-omni-1.2-flash"
MAX_REFERENCE_IMAGES = 6
BLOCKED_RESOLUTIONS = {"1080p", "4k"}

COST_PER_SECOND: dict[str, float] = {
    "360p":  0.023,
    "720p":  0.070,
    "1080p": 0.104,
    "4k":    0.209,
    "4K":    0.209,
}

def print_separator() -> None:
    print("─" * 64)

def fmt_cost(usd: float) -> str:
    inr = usd * INR_PER_USD
    return f"~${usd:.4f} USD  (~₹{inr:.2f} INR)"

def ensure_project_dirs(project_dir: Path) -> None:
    for sub in ("references", "drafts_360p", "finals_720p", "exports"):
        (project_dir / sub).mkdir(parents=True, exist_ok=True)

def load_scenes(scenes_json: Path) -> list:
    """Parse scenes.json or project.json → list of Scene objects."""
    with scenes_json.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    scenes_data = raw.get("scenes", raw) if isinstance(raw, dict) else raw
    scenes = []
    for s in scenes_data:
        try:
            scenes.append(
                Scene(
                    scene_number=int(s.get("scene_number", len(scenes) + 1)),
                    id=s.get("id", f"scene_{len(scenes) + 1:02d}"),
                    filename=s.get("filename", f"{len(scenes) + 1:02d}_scene.mp4"),
                    voiceover_segment=s.get("voiceover_segment", ""),
                    duration_seconds=int(s.get("duration_seconds", 8)),
                    visual_prompt=s.get("prompt", s.get("visual_prompt", "")),
                    draft_model=s.get("model", s.get("draft_model", DEFAULT_MODEL)),
                    final_model=s.get("model", s.get("final_model", DEFAULT_MODEL)),
                    resolution=s.get("resolution", "360p"),
                    approved=bool(s.get("approved", False)),
                    reference_images=s.get("reference_images", []),
                    reference_prompt=s.get("reference_prompt"),
                )
            )
        except Exception as exc:
            print(f"[WARN] Skipping scene: {exc}", file=sys.stderr)
    return scenes

def poll_operation(operation, label: str = "operation"):
    from google import genai
    elapsed = 0
    while not getattr(operation, "done", False):
        elapsed += POLL_INTERVAL_SECONDS
        print(f"  ⏳  [{label}] waiting… {elapsed}s elapsed")
        time.sleep(POLL_INTERVAL_SECONDS)
        operation = operation.refresh() if hasattr(operation, "refresh") else operation
    err = getattr(operation, "error", None)
    if err:
        raise RuntimeError(f"Operation '{label}' failed: {err}")
    return operation


def normalize_model_id(model_id: Optional[str]) -> str:
    """Automatically upgrade deprecated model IDs to supported Google Gemini models."""
    if not model_id:
        return "gemini-3.8-flash"
    m = model_id.strip()
    if m in ("gemini-2.5-flash", "gemini-2.0-flash", "models/gemini-2.5-flash", "models/gemini-2.0-flash"):
        return "gemini-3.8-flash"
    if m in ("gemini-2.5-flash-image", "gemini-3-pro-image", "models/gemini-2.5-flash-image", "models/gemini-3-pro-image"):
        return "gemini-3.1-flash-image"
    return m


# ---------------------------------------------------------------------------
# Dynamic Model Registry
# ---------------------------------------------------------------------------

MODEL_CONFIGS = {
    "script_models": [
        {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash Lite (Lowest Cost & Fastest)"},
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash"},
    ],
    "image_models": [
        {
            "id": "gemini-3.1-flash-lite-image",
            "name": "Gemini 3.1 Flash Lite Image (Lowest Cost — $0.025)",
            "cost_usd": 0.025,
        },
        {
            "id": "gemini-2.5-flash-image",
            "name": "Gemini 2.5 Flash Image ($0.039)",
            "cost_usd": 0.039,
        },
        {
            "id": "gemini-3.1-flash-image",
            "name": "Gemini 3.1 Flash Image ($0.039)",
            "cost_usd": 0.039,
        },
    ],
    "video_models": {
        "gemini-omni-1.2-flash": {
            "name": "Gemini Omni 1.2 Flash (Default — ~₹6.8/s)",
            "family": "omni",
            "duration_type": "range",
            "duration_range": (3, 15),
            "duration_step": 1,
            "default_duration": 4,
            "resolutions": ["360p", "720p", "1080p"],
            "default_draft_res": "360p",
            "default_final_res": "720p",
            "rates": {"360p": 0.080, "720p": 0.120, "1080p": 0.200},
        },
        "veo-3.1-lite-generate-001": {
            "name": "Veo 3.1 Lite (720p @ $0.080/s)",
            "family": "veo",
            "duration_type": "choices",
            "duration_choices": [4, 6, 8],
            "default_duration": 4,
            "resolutions": ["720p", "1080p"],
            "default_draft_res": "720p",
            "default_final_res": "720p",
            "rates": {"720p": 0.080, "1080p": 0.120},
        },
    },
}


def get_video_model_config(model_id: str) -> dict:
    """Return model config dict, falling back to sensible dynamic defaults for custom IDs."""
    if model_id in MODEL_CONFIGS["video_models"]:
        return MODEL_CONFIGS["video_models"][model_id]

    is_veo = "veo" in model_id.lower()
    if is_veo:
        return {
            "name": f"Custom Veo ({model_id})",
            "family": "veo",
            "duration_type": "choices",
            "duration_choices": [4, 6, 8],
            "default_duration": 8,
            "resolutions": ["720p", "1080p", "4k"],
            "default_draft_res": "720p",
            "default_final_res": "720p",
            "rates": {"720p": 0.080, "1080p": 0.120, "4k": 0.350},
        }

    return {
        "name": f"Custom Omni/Video ({model_id})",
        "family": "omni",
        "duration_type": "range",
        "duration_range": (3, 15),
        "duration_step": 1,
        "default_duration": 8,
        "resolutions": ["360p", "720p", "1080p"],
        "default_draft_res": "360p",
        "default_final_res": "720p",
        "rates": {"360p": 0.023, "720p": 0.070, "1080p": 0.104},
    }


def calculate_video_cost(model_id: str, resolution: str, duration_seconds: int) -> Tuple[float, float]:
    """Return (cost_usd, cost_inr) for a video clip."""
    cfg = get_video_model_config(model_id)
    rates = cfg.get("rates", {})
    rate = rates.get(resolution.lower(), rates.get("360p", 0.023))
    usd = rate * duration_seconds
    inr = usd * INR_PER_USD
    return usd, inr


def calculate_image_cost(model_id: str) -> Tuple[float, float]:
    """Return (cost_usd, cost_inr) for generating a reference still."""
    for item in MODEL_CONFIGS["image_models"]:
        if item["id"] == model_id:
            usd = item["cost_usd"]
            return usd, usd * INR_PER_USD
    usd = 0.035
    return usd, usd * INR_PER_USD


def format_cost_str(usd: float, inr: float) -> str:
    return f"${usd:.3f} USD (~₹{inr:.2f} INR)"


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class Scene(BaseModel):
    scene_number: int = 1
    id: str = "scene_01"
    filename: str = "01_scene.mp4"
    voiceover_segment: str = ""
    duration_seconds: int = 8
    visual_prompt: str = ""
    draft_model: str = "gemini-omni-1.2-flash"
    final_model: str = "gemini-omni-1.2-flash"
    resolution: str = "360p"
    approved: bool = False
    reference_images: List[str] = Field(default_factory=list)
    reference_prompt: Optional[str] = None

    @property
    def stem(self) -> str:
        return Path(self.filename).stem

    @property
    def model(self) -> str:
        return self.draft_model

    @property
    def prompt(self) -> str:
        return self.visual_prompt

    def draft_path(self, project_dir: Path) -> Path:
        return project_dir / "drafts_360p" / self.filename

    def final_path(self, project_dir: Path) -> Path:
        return project_dir / "finals_720p" / self.filename

    def reference_path(self, project_dir: Path) -> Path:
        return project_dir / "references" / f"{self.stem}.png"

    def cost_usd(self, resolution: Optional[str] = None) -> float:
        res = resolution or self.resolution
        rate = COST_PER_SECOND.get(res, COST_PER_SECOND["360p"])
        return rate * self.duration_seconds

    def reference_cost_usd(self) -> float:
        return COST_PER_IMAGE_IMAGEN if self.reference_prompt else 0.0

    def resolved_reference_paths(self, project_dir: Path) -> List[Path]:
        paths = []
        for raw in self.reference_images:
            p = Path(raw)
            if not p.is_absolute():
                p = project_dir / "references" / p
            paths.append(p)
        return paths


class Project(BaseModel):
    title: str = "Untitled Short"
    slug: str = "untitled_short"
    idea: str = ""
    language: str = "English"
    target_duration: int = 60
    voiceover_script: str = ""
    reference_prompts: List[str] = Field(default_factory=list)
    default_script_model: str = "gemini-3.8-flash"
    default_reference_model: str = "gemini-3.1-flash-image"
    default_draft_video_model: str = "gemini-omni-1.2-flash"
    default_final_video_model: str = "gemini-omni-1.2-flash"
    scenes: List[Scene] = Field(default_factory=list)

    @classmethod
    def get_project_dir(cls, slug: str) -> Path:
        return PROJECTS_DIR / slug

    def dir_path(self) -> Path:
        return self.get_project_dir(self.slug)

    def ensure_directories(self) -> None:
        pdir = self.dir_path()
        for sub in ("references", "drafts_360p", "finals_720p", "exports"):
            (pdir / sub).mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        pdir = self.dir_path()
        self.ensure_directories()
        json_path = pdir / "project.json"
        with json_path.open("w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, project_dir: Path) -> Optional["Project"]:
        json_path = project_dir / "project.json"
        if json_path.exists():
            with json_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Seamless migration for legacy / deprecated model IDs
            if "default_script_model" in data:
                data["default_script_model"] = normalize_model_id(data["default_script_model"])
            if "default_reference_model" in data:
                data["default_reference_model"] = normalize_model_id(data["default_reference_model"])
            return cls(**data)

        # Legacy fallback: convert scenes.json if present
        scenes_json = project_dir / "scenes.json"
        if scenes_json.exists():
            with scenes_json.open("r", encoding="utf-8") as f:
                raw_scenes = json.load(f)
            slug = project_dir.name
            scenes_list = []
            for idx, s in enumerate(raw_scenes, start=1):
                scenes_list.append(
                    Scene(
                        scene_number=idx,
                        id=s.get("id", f"scene_{idx:02d}"),
                        filename=s.get("filename", f"{idx:02d}_scene.mp4"),
                        voiceover_segment=s.get("voiceover_segment", ""),
                        duration_seconds=int(s.get("duration_seconds", 8)),
                        visual_prompt=s.get("prompt", s.get("visual_prompt", "")),
                        draft_model=s.get("model", "gemini-omni-1.2-flash"),
                        final_model=s.get("model", "gemini-omni-1.2-flash"),
                        resolution=s.get("resolution", "360p"),
                        approved=bool(s.get("approved", False)),
                        reference_images=s.get("reference_images", []),
                        reference_prompt=s.get("reference_prompt"),
                    )
                )
            project = cls(
                title=slug.replace("_", " ").title(),
                slug=slug,
                scenes=scenes_list,
            )
            project.save()
            return project

        return None


# ---------------------------------------------------------------------------
# Structured Output Schema for Storyboard Generation
# ---------------------------------------------------------------------------

class StoryboardSceneOutput(BaseModel):
    scene_number: int
    voiceover_segment: str
    duration_seconds: int
    visual_prompt: str


class StoryboardOutput(BaseModel):
    title: str
    voiceover_script: str
    scenes: List[StoryboardSceneOutput]
    reference_prompts: List[str]


# ---------------------------------------------------------------------------
# API Key and Client
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY", "")
    return key.strip()


def get_genai_client(api_key: Optional[str] = None):
    from google import genai
    key = (api_key or get_api_key()).strip()
    if not key or key == "your_key_here":
        raise ValueError("GEMINI_API_KEY is not set. Please provide a valid Paid Gemini API key.")
    return genai.Client(api_key=key)


# ---------------------------------------------------------------------------
# Media Generation & Polling Operations
# ---------------------------------------------------------------------------

def poll_operation_progress(client, operation, callback=None, label: str = "generating"):
    """
    Poll an operation until done, calling callback(elapsed_seconds) every interval.
    """
    elapsed = 0
    while not getattr(operation, "done", False):
        if callback:
            callback(elapsed)
        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
        operation = client.operations.get(operation)

    err = getattr(operation, "error", None)
    if err:
        raise RuntimeError(f"API operation '{label}' failed: {err}")
    return operation


def save_video_from_result(result, dest_path: Path) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    videos = getattr(result, "generated_videos", None) or getattr(result, "videos", None) or []
    if not videos:
        raise RuntimeError("No video returned in result (possible safety filter block).")

    v = videos[0]
    # Check for direct uri or video_bytes
    video_obj = getattr(v, "video", v)
    uri = getattr(video_obj, "uri", None)
    if uri:
        urllib.request.urlretrieve(uri, dest_path)
        return dest_path

    vbytes = getattr(video_obj, "video_bytes", None)
    if vbytes:
        dest_path.write_bytes(vbytes)
        return dest_path

    if isinstance(video_obj, (bytes, bytearray)):
        dest_path.write_bytes(video_obj)
        return dest_path

    raise RuntimeError(f"Unrecognized video format in response: {type(video_obj)}")


def generate_single_video(
    client,
    scene: Scene,
    project_dir: Path,
    mode: str = "draft",
    custom_model_id: Optional[str] = None,
    progress_callback=None,
) -> Path:
    """
    Generate a video clip for a scene using the requested model & resolution.
    Automatically routes gemini-omni-* models to Google's Interactions API,
    and veo-* models to client.models.generate_videos.
    """
    import base64
    import json
    import requests
    from google.genai import types

    model = custom_model_id or (scene.final_model if mode == "final" else scene.draft_model)
    model = normalize_model_id(model)
    resolution = scene.resolution if mode == "final" else "360p"
    dest_path = scene.final_path(project_dir) if mode == "final" else scene.draft_path(project_dir)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve local reference images
    ref_paths = []
    for ref_name in scene.reference_images:
        p = project_dir / "references" / ref_name
        if p.exists():
            ref_paths.append(p)

    # Omni Models Route (Google Interactions API)
    if "omni" in model.lower():
        api_key = get_api_key()
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }

        # Continuity prompt enhancement
        continuity_instruction = (
            " Maintain strict visual continuity with the provided reference images: preserve the character's facial features, "
            "hair style, costume/armor, accessories, colors, lighting tone, and environment atmosphere without changes."
            if ref_paths else ""
        )

        prompt_text = (
            f"Cinematic 9:16 vertical video ({resolution}, {scene.duration_seconds} seconds). "
            f"{scene.visual_prompt}.{continuity_instruction}"
        )

        input_items = []
        for ref_p in ref_paths:
            img_b64 = base64.b64encode(ref_p.read_bytes()).decode("utf-8")
            mime = "image/png" if ref_p.suffix.lower() == ".png" else "image/jpeg"
            input_items.append({"type": "image", "data": img_b64, "mime_type": mime})

        if input_items:
            input_items.append({"type": "text", "text": prompt_text})
            payload_input = input_items
        else:
            payload_input = prompt_text

        payload = {
            "model": model,
            "input": payload_input,
        }

        url = "https://generativelanguage.googleapis.com/v1beta/interactions"
        # Video generation can take 2-5 minutes on Google servers; increase read timeout to 600s
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=600)
        except requests.exceptions.Timeout:
            raise RuntimeError(
                "Video generation timed out on Google's server (>10 minutes). "
                "Google's video models can be under heavy load. Please try again or switch to 'Veo 3.1 Lite' which uses async long-running polling."
            )

        if resp.status_code != 200:
            err_msg = resp.text
            try:
                err_msg = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                pass
            raise RuntimeError(f"Omni Video Generation error ({resp.status_code}): {err_msg}")

        data = resp.json()
        video_bytes = None
        for step in data.get("steps", []):
            for item in step.get("content", []):
                if isinstance(item, dict) and item.get("type") == "video" and "data" in item:
                    video_bytes = base64.b64decode(item["data"])
                    break
            if video_bytes:
                break

        if not video_bytes:
            raise RuntimeError(f"No video data returned from Omni API: {json.dumps(data)[:400]}")

        dest_path.write_bytes(video_bytes)
        return dest_path

    # Veo Models Route (SDK generate_videos)
    video_config_kwargs = {
        "duration_seconds": scene.duration_seconds,
        "aspect_ratio": "9:16",
    }
    if resolution:
        video_config_kwargs["resolution"] = resolution

    config = types.GenerateVideosConfig(**video_config_kwargs)

    image_arg = None
    if ref_paths:
        first_img = ref_paths[0]
        image_arg = types.Image.from_file(location=str(first_img))

    operation = client.models.generate_videos(
        model=model,
        prompt=scene.visual_prompt,
        image=image_arg,
        config=config,
    )

    poll_operation_progress(
        client=client,
        operation=operation,
        callback=progress_callback,
        label=f"{scene.id} ({model})",
    )
    save_video_from_result(operation.result, dest_path)
    return dest_path


def generate_reference_image(
    client,
    prompt: str,
    output_path: Path,
    model_id: str = "gemini-3.1-flash-image",
) -> Path:
    """Generate a 9:16 PNG reference still using Gemini Image models (with Imagen fallback)."""
    import io
    from PIL import Image
    from google.genai import types

    model_id = normalize_model_id(model_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = None

    # Method 1: Multimodal Gemini Image Generation (gemini-3.1-flash-image, etc.)
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=(
                f"A high quality, photorealistic, cinematic 9:16 vertical orientation portrait or scene still image. "
                f"8K resolution, detailed textures, dramatic lighting:\n\n{prompt}"
            ),
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                    raw_bytes = part.inline_data.data
                    break
    except Exception:
        pass

    # Method 2: Fallback to generate_images (for Imagen models)
    if not raw_bytes:
        try:
            config = types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="9:16",
            )
            response = client.models.generate_images(
                model=model_id,
                prompt=prompt,
                config=config,
            )
            images = getattr(response, "generated_images", [])
            if images:
                img_data = images[0].image
                raw_bytes = getattr(img_data, "image_bytes", img_data)
        except Exception as exc:
            raise RuntimeError(f"Error generating image with {model_id}: {exc}")

    if not raw_bytes:
        raise RuntimeError(f"No image returned from reference model {model_id} (possible safety filter block).")

    # Standardize and save as PNG format
    try:
        pil_img = Image.open(io.BytesIO(raw_bytes))
        pil_img.save(output_path, "PNG")
    except Exception:
        output_path.write_bytes(raw_bytes)

    return output_path


def edit_clip(
    client,
    input_clip_path: Path,
    edit_prompt: str,
    output_clip_path: Path,
    model_id: str = "gemini-omni-1.2-flash",
    progress_callback=None,
) -> Path:
    """Perform multi-turn conversational video edit on an existing clip."""
    import base64
    import json
    import requests
    from google.genai import types

    if not input_clip_path.exists():
        raise FileNotFoundError(f"Source clip not found: {input_clip_path}")

    model_id = normalize_model_id(model_id)
    output_clip_path.parent.mkdir(parents=True, exist_ok=True)
    video_bytes = input_clip_path.read_bytes()

    # Omni Video Edit via Interactions API
    if "omni" in model_id.lower():
        api_key = get_api_key()
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        vid_b64 = base64.b64encode(video_bytes).decode("utf-8")
        payload = {
            "model": model_id,
            "input": [
                {"type": "video", "data": vid_b64, "mime_type": "video/mp4"},
                {"type": "text", "text": f"[VIDEO EDIT] Modify the provided 9:16 vertical video clip with this instruction:\n{edit_prompt}\nPreserve overall character design, structure, and composition."}
            ]
        }
        url = "https://generativelanguage.googleapis.com/v1beta/interactions"
        resp = requests.post(url, headers=headers, json=payload, timeout=240)
        if resp.status_code != 200:
            err_msg = resp.text
            try:
                err_msg = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                pass
            raise RuntimeError(f"Omni Video Edit error ({resp.status_code}): {err_msg}")

        data = resp.json()
        edited_bytes = None
        for step in data.get("steps", []):
            for item in step.get("content", []):
                if isinstance(item, dict) and item.get("type") == "video" and "data" in item:
                    edited_bytes = base64.b64decode(item["data"])
                    break
            if edited_bytes:
                break

        if not edited_bytes:
            raise RuntimeError(f"No edited video returned from Omni API: {json.dumps(data)[:400]}")

        output_clip_path.write_bytes(edited_bytes)
        return output_clip_path

    # Veo fallback
    try:
        operation = client.models.generate_videos(
            model=model_id,
            video=types.Video(video_bytes=video_bytes, mime_type="video/mp4"),
            prompt=edit_prompt,
            config=types.GenerateVideosConfig(aspect_ratio="9:16"),
        )
    except Exception:
        combined_prompt = (
            f"[VIDEO EDIT] Modify the provided clip with this instruction:\n{edit_prompt}\n"
            f"Preserve overall structure, framerate, and composition."
        )
        operation = client.models.generate_videos(
            model=model_id,
            prompt=combined_prompt,
            config=types.GenerateVideosConfig(aspect_ratio="9:16"),
        )

    poll_operation_progress(
        client=client,
        operation=operation,
        callback=progress_callback,
        label=f"edit {input_clip_path.name}",
    )
    save_video_from_result(operation.result, output_clip_path)
    return output_clip_path


# ---------------------------------------------------------------------------
# FFmpeg Video Stitching & Audio Merging
# ---------------------------------------------------------------------------

def stitch_project_clips(
    clip_paths: List[Path],
    output_path: Path,
    audio_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """
    Concatenate multiple 9:16 video clips and optionally merge voiceover audio
    into a production-ready MP4 using imageio-ffmpeg.
    Standardizes all inputs to 720x1280 @ 30fps.
    """
    if not clip_paths:
        return False, "No video clips provided to stitch."

    valid_clips = [p for p in clip_paths if p.exists() and p.stat().st_size > 0]
    if not valid_clips:
        return False, "None of the specified clip files exist on disk."

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    n = len(valid_clips)
    input_args = []
    filter_parts = []
    concat_inputs = []

    for idx, clip in enumerate(valid_clips):
        input_args.extend(["-i", str(clip)])
        # Standardize resolution to 720x1280 (9:16) with letterboxing/pillarboxing if needed
        filter_parts.append(
            f"[{idx}:v]scale=720:1280:force_original_aspect_ratio=decrease,"
            f"pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{idx}]"
        )
        concat_inputs.append(f"[v{idx}]")

    concat_str = "".join(concat_inputs) + f"concat=n={n}:v=1:a=0[outv]"
    filter_parts.append(concat_str)
    full_filter = "; ".join(filter_parts)

    cmd = [ffmpeg_exe, "-y"] + input_args

    if audio_path and audio_path.exists() and audio_path.stat().st_size > 0:
        cmd.extend(["-i", str(audio_path)])
        audio_idx = n
        cmd.extend([
            "-filter_complex", full_filter,
            "-map", "[outv]",
            "-map", f"{audio_idx}:a",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            str(output_path),
        ])
    else:
        cmd.extend([
            "-filter_complex", full_filter,
            "-map", "[outv]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, "Video successfully stitched!"
    except subprocess.CalledProcessError as exc:
        return False, f"FFmpeg stitching error: {exc.stderr}"


def generate_voiceover_tts(
    client,
    text: str,
    output_mp3_path: Path,
    voice_name: str = "Charon",
) -> Path:
    """
    Generate voiceover audio from text using Gemini TTS and encode to MP3.
    Supported preset voices: Charon, Puck, Kore, Fenrir, Aoede.
    """
    from google.genai import types

    output_mp3_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = f"Read the following text directly as audio without any extra commentary:\n\n{text}"

    # Try gemini-2.5-flash-preview-tts or gemini-3.8-flash-tts
    tts_model = "gemini-2.5-flash-preview-tts"
    response = client.models.generate_content(
        model=tts_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
        ),
    )

    raw_pcm = None
    if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                raw_pcm = part.inline_data.data
                break

    if not raw_pcm:
        raise RuntimeError("No audio data received from Gemini TTS.")

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.Popen(
        [
            ffmpeg_exe, "-y",
            "-f", "s16le",
            "-ar", "24000",
            "-ac", "1",
            "-i", "pipe:0",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(output_mp3_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _, err = proc.communicate(input=raw_pcm)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg audio encoding failed: {err.decode('utf-8', errors='ignore')}")
    return output_mp3_path


# ---------------------------------------------------------------------------
# AI Storyboard Generator
# ---------------------------------------------------------------------------

def generate_storyboard_with_ai(
    client,
    title: str,
    idea: str,
    language: str = "English",
    target_duration: int = 60,
    model_id: str = "gemini-3.8-flash",
    revision_notes: Optional[str] = None,
    previous_script: Optional[str] = None,
) -> StoryboardOutput:
    """
    Generate an end-to-end 1-minute YouTube Shorts storyboard using Pydantic structured output.
    Supports retry with revision notes and preserves English visual prompts for Veo/Omni.
    """
    from google.genai import types

    model_id = normalize_model_id(model_id)

    system_instruction = (
        "You are an expert viral YouTube Shorts producer and mythology/history documentarian. "
        "Create high-retention, cinematic, fast-paced 9:16 vertical short scripts. "
        "Each short must feature an engaging hook, high-tension middle, and a memorable takeaway. "
        f"LANGUAGE REQUIREMENT: The title, voiceover_script, and voiceover_segment of every scene MUST be written in {language}. "
        "CRITICAL INSTRUCTION: All visual_prompt fields (for AI video generation models like Veo and Gemini Omni) "
        "and reference_prompts MUST ALWAYS BE WRITTEN IN DETAILED ENGLISH to ensure optimal video quality and motion accuracy. "
        "CHARACTER CONSISTENCY REQUIREMENT: For every scene featuring characters, the visual_prompt must explicitly describe "
        "the character's age, physical appearance, face, hairstyle, clothing/armor, ornaments, and held weapons/props so their look remains consistent. "
        "DEDICATED CHARACTER & SETTING REFERENCES: You MUST generate 2 to 3 detailed reference_prompts dedicated specifically "
        "to full-body or 9:16 portrait stills of the main characters (e.g. Barbarika with his three arrows and quiver, Lord Krishna in traditional attire) "
        "and key mythological settings. These reference stills will be rendered first and used as image anchors for video consistency. "
        "The voiceover script must read naturally for professional TTS (like ElevenLabs). "
        "SCENE STRUCTURE & DURATION CONSTRAINTS: Break the short into AT MOST 4 chronological scenes (MAXIMUM 4 CLIPS TOTAL). "
        "Each scene's duration_seconds must be at most 15 seconds (e.g., 15s + 15s + 15s + 15s = 60s total; never exceed 15 seconds per scene, and never more than 4 scenes)."
    )

    prompt = (
        f"Title/Subject: {title}\n"
        f"Core Idea/Mythological Concept: {idea}\n"
        f"Requested Language for Title & Voiceover: {language}\n"
        f"Target Total Duration: {target_duration} seconds (divided across a maximum of 4 scenes of up to 15 seconds each).\n"
    )

    if previous_script:
        prompt += f"\nPrevious Voiceover Script:\n{previous_script}\n"
    if revision_notes:
        prompt += f"\nREVISION / RETRY INSTRUCTIONS:\n{revision_notes}\nPlease refine the storyline, voiceover, and visual prompts specifically following these revision notes.\n"

    prompt += "\nGenerate the complete YouTube Short package according to the structured schema (max 4 scenes, max 15s each)."

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=StoryboardOutput,
        temperature=0.75,
    )

    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=config,
    )

    if not response.text:
        raise RuntimeError("AI model returned an empty response.")

    output = StoryboardOutput.model_validate_json(response.text)
    # Hard guardrails: exactly at most 4 scenes, each capped at 15 seconds
    output.scenes = output.scenes[:4]
    for idx, s in enumerate(output.scenes, start=1):
        s.scene_number = idx
        s.duration_seconds = max(3, min(15, s.duration_seconds))
    return output


def reroll_scene_visual_prompt(
    client,
    voiceover_segment: str,
    current_prompt: str,
    tweak_instruction: str = "",
    model_id: str = "gemini-3.8-flash",
) -> str:
    """Reroll or enhance a single scene's visual prompt in English for Veo / Gemini Omni."""
    from google.genai import types

    model_id = normalize_model_id(model_id)

    system_instruction = (
        "You are an expert AI video prompt engineer for Google Veo and Gemini Omni. "
        "Write a cinematic, detailed 9:16 vertical video prompt in English describing camera angles, "
        "lighting, character appearance, motion, speed, and textures. "
        "Return ONLY the final visual prompt text without quotation marks or conversational commentary."
    )

    prompt = (
        f"Scene voiceover: {voiceover_segment}\n"
        f"Current visual prompt: {current_prompt}\n"
    )
    if tweak_instruction.strip():
        prompt += f"Specific improvement/direction: {tweak_instruction}\n"
    prompt += "Generate an improved, cinematic, photorealistic 9:16 vertical prompt in English."

    resp = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.8,
        ),
    )
    return resp.text.strip() if resp.text else current_prompt


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:32] or "project"
