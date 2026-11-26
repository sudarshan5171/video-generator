#!/usr/bin/env python3
"""
generate_references.py
──────────────────────
Stage 0 (optional): generate cheap 9:16 static PNG reference images for
each scene using Imagen 3 so you can lock character/armor/environment
consistency BEFORE spending video credits.

Usage:
    python scripts/generate_references.py <project_dir> [options]

Options:
    --dry-run           Print plan + cost; make NO API calls.
    --overwrite         Re-generate references that already exist.
    --scene <id>        Process only this scene id (repeatable).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    COST_PER_IMAGE_IMAGEN,
    INR_PER_USD,
    Scene,
    ensure_project_dirs,
    fmt_cost,
    get_api_key,
    load_scenes,
    print_separator,
)

IMAGEN_MODEL = "imagen-3.0-generate-002"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Stage 0 – Generate 9:16 PNG character/scene reference images."
    )
    p.add_argument("project_dir", type=Path, help="Project folder containing scenes.json.")
    p.add_argument("--dry-run", action="store_true", help="No API calls; just print the plan.")
    p.add_argument("--overwrite", action="store_true", help="Re-generate existing references.")
    p.add_argument("--scene", dest="scene_ids", action="append", metavar="ID", default=[],
                   help="Limit to this scene id (repeatable).")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filter(
    scenes: list[Scene],
    scene_ids: list[str],
    project_dir: Path,
    overwrite: bool,
) -> list[tuple[Scene, str]]:
    """Return (scene, skip_reason) pairs. skip_reason='' means 'process this'."""
    out = []
    for s in scenes:
        if not s.reference_prompt:
            out.append((s, "no reference_prompt – skipped"))
            continue
        if scene_ids and s.id not in scene_ids:
            out.append((s, "not in --scene filter"))
            continue
        dest = s.reference_path(project_dir)
        if dest.exists() and not overwrite:
            out.append((s, f"already exists ({dest.name}) – use --overwrite to redo"))
            continue
        out.append((s, ""))
    return out


def _print_plan(
    filtered: list[tuple[Scene, str]],
    project_dir: Path,
    dry_run: bool,
) -> float:
    to_do   = [(s, r) for s, r in filtered if not r]
    to_skip = [(s, r) for s, r in filtered if r]

    tag = "[DRY RUN] " if dry_run else ""
    print_separator()
    print(f"  {tag}Reference generation plan  ▸  {project_dir.name}")
    print_separator()

    total = 0.0

    if to_do:
        print(f"\n  🖼  To generate ({len(to_do)} scene{'s' if len(to_do)>1 else ''}):\n")
        for s, _ in to_do:
            cost = s.reference_cost_usd()
            total += cost
            print(f"    • [{s.id}]  →  {s.reference_path(project_dir).name}")
            print(f"      model  : {IMAGEN_MODEL}")
            print(f"      size   : 768 × 1360 px  (≈ 9:16)")
            print(f"      cost   : {fmt_cost(cost)}")
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

def _generate_one(scene: Scene, project_dir: Path, client) -> None:
    from google.genai import types as T

    dest = scene.reference_path(project_dir)
    print(f"  🚀  [{scene.id}] Generating reference image → {dest.name}")

    resp = client.models.generate_images(
        model=IMAGEN_MODEL,
        prompt=scene.reference_prompt,
        config=T.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="9:16",
        ),
    )

    images = getattr(resp, "generated_images", [])
    if not images:
        raise RuntimeError("Imagen returned no images (possible safety block).")

    img_obj = images[0].image
    raw: bytes = getattr(img_obj, "image_bytes", img_obj)
    dest.write_bytes(raw)
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

    filtered = _filter(scenes, args.scene_ids, project_dir, args.overwrite)
    _print_plan(filtered, project_dir, args.dry_run)

    if args.dry_run:
        print("\n  [DRY RUN] No API calls made. Remove --dry-run to execute.\n")
        return

    api_key = get_api_key()
    from google import genai
    client = genai.Client(api_key=api_key)

    ok = err = 0
    for scene, skip in [(s, r) for s, r in filtered if not r]:
        try:
            _generate_one(scene, project_dir, client)
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
