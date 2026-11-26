#!/usr/bin/env python3
"""
generate_videos.py
──────────────────
Main pipeline: generate 9:16 MP4 clips via Gemini Omni 1.2 Flash (Veo engine).

Modes:
  --mode draft  (default) → renders ALL scenes at 360p into drafts_360p/
  --mode final            → renders ONLY approved scenes at 720p into finals_720p/
                            (1080p / 4K are blocked unless --allow-upsampled is passed)

Reference images: when reference_images[] lists local paths, up to 6 PNGs/JPEGs
are attached to the request to anchor character/environment consistency.

Usage:
    python scripts/generate_videos.py <project_dir> [options]

Options:
    --mode {draft,final}   Rendering mode (default: draft).
    --dry-run              Print plan + cost in USD & INR; NO API calls.
    --overwrite            Re-generate existing output files.
    --allow-upsampled      Unlock 1080p / 4K resolutions in final mode.
    --scene <id>           Limit to this scene id (repeatable).
"""

from __future__ import annotations

import argparse
import sys
import traceback
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BLOCKED_RESOLUTIONS,
    COST_PER_SECOND,
    INR_PER_USD,
    MAX_REFERENCE_IMAGES,
    Scene,
    ensure_project_dirs,
    fmt_cost,
    generate_single_video,
    get_api_key,
    load_scenes,
    poll_operation,
    print_separator,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate 9:16 MP4 clips via Gemini Omni 1.2 Flash."
    )
    p.add_argument("project_dir", type=Path)
    p.add_argument("--mode", choices=["draft", "final"], default="draft",
                   help="draft=360p all scenes, final=720p approved only.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--allow-upsampled", action="store_true",
                   help="Unlock 1080p/4K resolutions (normally blocked).")
    p.add_argument("--scene", dest="scene_ids", action="append", metavar="ID", default=[])
    return p.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _effective_resolution(scene: Scene, mode: str) -> str:
    """Draft always uses 360p; final uses the scene's declared resolution (default 720p)."""
    if mode == "draft":
        return "360p"
    # In final mode, honour whatever is in scenes.json (default is 720p)
    return scene.resolution if scene.resolution != "360p" else "720p"


def _output_path(scene: Scene, project_dir: Path, mode: str) -> Path:
    if mode == "draft":
        return scene.draft_path(project_dir)
    return scene.final_path(project_dir)


def _filter(
    scenes: list[Scene],
    scene_ids: list[str],
    project_dir: Path,
    mode: str,
    overwrite: bool,
    allow_upsampled: bool,
) -> list[tuple[Scene, str]]:
    """Return (scene, skip_reason) pairs."""
    out = []
    for s in scenes:
        if scene_ids and s.id not in scene_ids:
            out.append((s, "not in --scene filter"))
            continue

        if mode == "final" and not s.approved:
            out.append((s, "not approved (set \"approved\": true in scenes.json)"))
            continue

        res = _effective_resolution(s, mode)
        if res in BLOCKED_RESOLUTIONS and not allow_upsampled:
            out.append((s, f"{res} is blocked – pass --allow-upsampled to unlock"))
            continue

        dest = _output_path(s, project_dir, mode)
        if dest.exists() and not overwrite:
            out.append((s, f"already exists ({dest.name}) – use --overwrite"))
            continue

        out.append((s, ""))
    return out


def _has_ref_images(scene: Scene, project_dir: Path) -> bool:
    return bool(scene.resolved_reference_paths(project_dir))


def _print_plan(
    filtered: list[tuple[Scene, str]],
    project_dir: Path,
    mode: str,
    dry_run: bool,
) -> float:
    to_do   = [(s, r) for s, r in filtered if not r]
    to_skip = [(s, r) for s, r in filtered if r]

    tag = "[DRY RUN] " if dry_run else ""
    print_separator()
    print(f"  {tag}Video generation plan  ▸  {project_dir.name}  ▸  mode={mode}")
    print_separator()

    total = 0.0

    if to_do:
        print(f"\n  🎬  To generate ({len(to_do)} scene{'s' if len(to_do)>1 else ''}):\n")
        for s, _ in to_do:
            res = _effective_resolution(s, mode)
            cost = s.cost_usd(res)
            total += cost
            refs = s.resolved_reference_paths(project_dir)
            ref_count = min(len(refs), MAX_REFERENCE_IMAGES)
            ref_txt = f"{ref_count} attached" if ref_count else "none"
            dest = _output_path(s, project_dir, mode).name

            print(f"    • [{s.id}]  →  {dest}")
            print(f"      model      : {s.model}")
            print(f"      duration   : {s.duration_seconds}s")
            print(f"      resolution : {res}")
            print(f"      references : {ref_txt}")
            print(f"      cost       : {fmt_cost(cost)}")
            print()

    if to_skip:
        print(f"  ⏭  Skipped ({len(to_skip)}):\n")
        for s, r in to_skip:
            print(f"    • [{s.id}]  {r}")
        print()

    print_separator()
    print(f"  Estimated total  :  {fmt_cost(total)}")
    print_separator()
    return total


# ---------------------------------------------------------------------------
# Live generation
# ---------------------------------------------------------------------------

def _build_image_parts(scene: Scene, project_dir: Path):
    """Return a list of genai Image objects for all valid reference images."""
    from google.genai import types as T

    parts = []
    for p in scene.resolved_reference_paths(project_dir)[:MAX_REFERENCE_IMAGES]:
        if not p.exists():
            print(f"  [WARN] Reference image not found, skipping: {p}")
            continue
        suffix = p.suffix.lower()
        mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
        parts.append(T.Image(image_bytes=p.read_bytes(), mime_type=mime))
    return parts


def _save_video(result, dest: Path) -> None:
    """Extract video bytes from an operation result and write to dest."""
    # Try the most common SDK shapes
    videos = (
        getattr(result, "videos", None)
        or getattr(result, "generated_videos", None)
        or []
    )
    if not videos:
        raise RuntimeError("No video data in response (possible safety block).")

    v = videos[0]
    # Shape 1: v.video.uri  (signed URL)
    uri = getattr(getattr(v, "video", None), "uri", None)
    if uri:
        urllib.request.urlretrieve(uri, dest)
        return
    # Shape 2: v.video.video_bytes
    vbytes = getattr(getattr(v, "video", None), "video_bytes", None)
    if vbytes:
        dest.write_bytes(vbytes)
        return
    # Shape 3: raw bytes
    if isinstance(v, (bytes, bytearray)):
        dest.write_bytes(v)
        return
    raise RuntimeError(f"Unrecognised video result shape: {type(v)}")


def _generate_one(
    scene: Scene,
    project_dir: Path,
    mode: str,
    client,
) -> None:
    res = _effective_resolution(scene, mode)
    dest = _output_path(scene, project_dir, mode)
    ref_count = len(scene.reference_images)

    print(f"  🚀  [{scene.id}] {mode.upper()} | {res} | {scene.duration_seconds}s "
          f"| refs={ref_count} → {dest.name}")

    generate_single_video(
        client=client,
        scene=scene,
        project_dir=project_dir,
        mode=mode,
    )
    print(f"  ✅  [{scene.id}] Saved → {dest}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    project_dir = args.project_dir.resolve()
    scenes_json = project_dir / "scenes.json"

    if not scenes_json.exists():
        sys.exit(f"[ERROR] scenes.json not found in {project_dir}")

    scenes = load_scenes(scenes_json)
    ensure_project_dirs(project_dir)

    filtered = _filter(
        scenes,
        scene_ids=args.scene_ids,
        project_dir=project_dir,
        mode=args.mode,
        overwrite=args.overwrite,
        allow_upsampled=args.allow_upsampled,
    )

    _print_plan(filtered, project_dir, args.mode, args.dry_run)

    if args.dry_run:
        print("\n  [DRY RUN] No API calls made. Remove --dry-run to execute.\n")
        return

    api_key = get_api_key()
    from google import genai
    client = genai.Client(api_key=api_key)

    ok = err = 0
    for scene, skip in [(s, r) for s, r in filtered if not r]:
        try:
            _generate_one(scene, project_dir, args.mode, client)
            ok += 1
        except Exception as exc:
            err += 1
            print(f"  ❌  [{scene.id}] FAILED: {exc}", file=sys.stderr)
            traceback.print_exc()

    print_separator()
    print(f"  Done — {ok} generated, {err} failed.")
    print_separator()


if __name__ == "__main__":
    run(parse_args())
