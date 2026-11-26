#!/usr/bin/env python3
"""
generate_keyframes.py
─────────────────────
Optional Stage 1: generate 9:16 PNG keyframes using Imagen so you can
inspect character/scene consistency before committing to Veo video generation.

Usage:
    python scripts/generate_keyframes.py <project_dir> [options]

Options:
    --dry-run       Print what would run; make NO API calls.
    --overwrite     Re-generate keyframes that already exist on disk.
    --scene <id>    Process only this scene id (can be repeated).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

# Allow running from project root or scripts/ dir
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    COST_PER_IMAGE_IMAGEN,
    Scene,
    ensure_dirs,
    get_api_key,
    load_scenes,
    print_separator,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 1 – Generate 9:16 PNG keyframes with Imagen."
    )
    parser.add_argument(
        "project_dir",
        type=Path,
        help="Path to the project folder (must contain scenes.json).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print plan without making any API calls.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-generate even if the keyframe already exists.",
    )
    parser.add_argument(
        "--scene",
        dest="scene_ids",
        action="append",
        metavar="ID",
        default=[],
        help="Process only this scene id. Repeatable.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def filter_scenes(
    scenes: list[Scene],
    scene_ids: list[str],
    project_dir: Path,
    overwrite: bool,
    dry_run: bool,
) -> list[tuple[Scene, str]]:
    """
    Returns a list of (scene, reason_skipped) tuples.
    reason_skipped is empty string if the scene should be processed.
    """
    result = []
    for scene in scenes:
        if not scene.keyframe_prompt:
            result.append((scene, "no keyframe_prompt – skipped"))
            continue
        if scene_ids and scene.id not in scene_ids:
            result.append((scene, "not in --scene filter – skipped"))
            continue
        kf_path = scene.keyframe_path(project_dir)
        if kf_path.exists() and not overwrite:
            result.append((scene, f"already exists ({kf_path.name}) – skipped (use --overwrite)"))
            continue
        result.append((scene, ""))
    return result


def print_plan(
    filtered: list[tuple[Scene, str]],
    project_dir: Path,
    dry_run: bool,
) -> float:
    """Print a human-readable plan. Returns estimated total cost."""
    to_process = [(s, r) for s, r in filtered if not r]
    to_skip = [(s, r) for s, r in filtered if r]

    print_separator()
    tag = "[DRY RUN] " if dry_run else ""
    print(f"  {tag}Keyframe generation plan for: {project_dir.name}")
    print_separator()

    total_cost = 0.0

    if to_process:
        print(f"\n  🖼  Scenes to generate ({len(to_process)}):\n")
        for scene, _ in to_process:
            cost = scene.estimated_keyframe_cost()
            total_cost += cost
            kf = scene.keyframe_path(project_dir).name
            print(f"    • [{scene.id}]  → {kf}")
            print(f"      model  : imagen-3.0-generate-002")
            print(f"      size   : 768×1360 (≈ 9:16)")
            print(f"      cost   : ~${cost:.4f}")
            print()

    if to_skip:
        print(f"  ⏭  Scenes to skip ({len(to_skip)}):\n")
        for scene, reason in to_skip:
            print(f"    • [{scene.id}]  {reason}")
        print()

    print_separator()
    print(f"  Estimated total cost: ~${total_cost:.4f}")
    print_separator()
    return total_cost


def generate_keyframe(scene: Scene, project_dir: Path, client) -> None:
    """Call Imagen and save the first returned image as a PNG."""
    from google import genai
    from google.genai import types as genai_types

    out_path = scene.keyframe_path(project_dir)
    print(f"  🚀 [{scene.id}] Generating keyframe → {out_path.name}")

    response = client.models.generate_images(
        model="imagen-3.0-generate-002",
        prompt=scene.keyframe_prompt,
        config=genai_types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="9:16",
            # safety_filter_level="BLOCK_MEDIUM_AND_ABOVE",  # adjust if needed
        ),
    )

    images = response.generated_images
    if not images:
        raise RuntimeError("Imagen returned no images (possible safety block).")

    # Save using Pillow (or raw bytes)
    img_data = images[0].image
    if hasattr(img_data, "image_bytes"):
        raw = img_data.image_bytes
    else:
        raw = img_data

    out_path.write_bytes(raw)
    print(f"  ✅ [{scene.id}] Saved → {out_path}")


def run(args: argparse.Namespace) -> None:
    project_dir: Path = args.project_dir.resolve()
    scenes_json = project_dir / "scenes.json"

    if not scenes_json.exists():
        sys.exit(f"[ERROR] scenes.json not found in {project_dir}")

    scenes = load_scenes(scenes_json)
    ensure_dirs(project_dir)

    filtered = filter_scenes(
        scenes,
        scene_ids=args.scene_ids,
        project_dir=project_dir,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )

    print_plan(filtered, project_dir, dry_run=args.dry_run)

    if args.dry_run:
        print("\n  [DRY RUN] No API calls made. Remove --dry-run to execute.\n")
        return

    # --- Live execution ---
    api_key = get_api_key()
    from google import genai

    client = genai.Client(api_key=api_key)

    to_process = [(s, r) for s, r in filtered if not r]
    success, failure = 0, 0

    for scene, _ in to_process:
        try:
            generate_keyframe(scene, project_dir, client)
            success += 1
        except Exception as exc:
            failure += 1
            print(f"  ❌ [{scene.id}] FAILED: {exc}", file=sys.stderr)
            traceback.print_exc()

    print_separator()
    print(f"  Done — {success} generated, {failure} failed.")
    print_separator()


if __name__ == "__main__":
    run(parse_args())
