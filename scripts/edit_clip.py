#!/usr/bin/env python3
"""
edit_clip.py
────────────
Multi-turn conversational editing on an existing clip via Gemini Omni 1.2 Flash.
Instead of re-rolling a full 15s generation, describe a targeted change
(lighting, weather, background, speed, colour grade, etc.) and get a revised clip.

Each call opens a NEW editing turn. The script is stateless; pass the previously
edited output as --clip on subsequent runs to chain edits.

Usage:
    python scripts/edit_clip.py \\
        --clip   projects/sample_short/drafts_360p/01_zeus_thunderbolt.mp4 \\
        --edit-prompt "Change the sky to a blood-red sunset. Keep Zeus and the foreground identical." \\
        --output projects/sample_short/drafts_360p/01_zeus_thunderbolt_v2.mp4

    # Second turn (chain on the previous output):
    python scripts/edit_clip.py \\
        --clip   projects/sample_short/drafts_360p/01_zeus_thunderbolt_v2.mp4 \\
        --edit-prompt "Add a flock of ravens silhouetted against the red sky." \\
        --output projects/sample_short/drafts_360p/01_zeus_thunderbolt_v3.mp4

Options:
    --clip <path>           Existing MP4 clip to edit. Required.
    --edit-prompt <text>    Natural-language description of the desired change. Required.
    --output <path>         Where to save the revised clip. Required.
    --dry-run               Print plan + cost estimate without calling the API.
    --overwrite             Overwrite the output file if it already exists.
    --model <id>            Override the Gemini model (default: gemini-omni-1.2-flash).
    --resolution <tier>     Cost tier for estimate: 360p|720p|1080p|4K (default: 360p).
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
    DEFAULT_MODEL,
    INR_PER_USD,
    edit_clip,
    fmt_cost,
    get_api_key,
    poll_operation,
    print_separator,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Multi-turn clip editing via Gemini Omni 1.2 Flash."
    )
    p.add_argument("--clip", required=True, type=Path,
                   help="Path to the existing MP4 clip to edit.")
    p.add_argument("--edit-prompt", required=True,
                   help="Describe what to change in natural language.")
    p.add_argument("--output", required=True, type=Path,
                   help="Destination path for the edited clip.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"Gemini model to use (default: {DEFAULT_MODEL}).")
    p.add_argument("--resolution", default="360p",
                   choices=list(COST_PER_SECOND.keys()),
                   help="Resolution tier for cost estimate (default: 360p).")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Plan printer
# ---------------------------------------------------------------------------

def _print_plan(args: argparse.Namespace, estimated_duration_s: int = 15) -> None:
    rate = COST_PER_SECOND.get(args.resolution, COST_PER_SECOND["360p"])
    cost_usd = rate * estimated_duration_s
    cost_inr = cost_usd * INR_PER_USD

    tag = "[DRY RUN] " if args.dry_run else ""
    print_separator()
    print(f"  {tag}Clip edit plan")
    print_separator()
    print(f"  Input clip    : {args.clip}")
    print(f"  Edit prompt   : {args.edit_prompt!r}")
    print(f"  Output        : {args.output}")
    print(f"  Model         : {args.model}")
    print(f"  Resolution    : {args.resolution}")
    print(f"  Est. duration : up to {estimated_duration_s}s (matches source clip)")
    print(f"  Est. cost     : {fmt_cost(cost_usd)}")
    print_separator()


# ---------------------------------------------------------------------------
# Live edit
# ---------------------------------------------------------------------------

def _save_video(result, dest: Path) -> None:
    videos = (
        getattr(result, "videos", None)
        or getattr(result, "generated_videos", None)
        or []
    )
    if not videos:
        raise RuntimeError("No video returned (possible safety block).")

    v = videos[0]
    uri = getattr(getattr(v, "video", None), "uri", None)
    if uri:
        urllib.request.urlretrieve(uri, dest)
        return
    vbytes = getattr(getattr(v, "video", None), "video_bytes", None)
    if vbytes:
        dest.write_bytes(vbytes)
        return
    if isinstance(v, (bytes, bytearray)):
        dest.write_bytes(v)
        return
    raise RuntimeError(f"Unrecognised video result shape: {type(v)}")


def run(args: argparse.Namespace) -> None:
    clip_path: Path = args.clip.resolve()
    out_path: Path  = args.output.resolve()

    # --- pre-flight checks ---
    if not clip_path.exists():
        if args.dry_run:
            print(f"  [NOTE] Input clip does not exist yet (dry-run only): {clip_path}")
        else:
            sys.exit(f"[ERROR] Input clip not found: {clip_path}")

    if out_path.exists() and not args.overwrite:
        sys.exit(
            f"[ERROR] Output already exists: {out_path}\n"
            "        Pass --overwrite to replace it."
        )

    if clip_path.suffix.lower() not in (".mp4", ".mov", ".webm"):
        print(f"[WARN] Unexpected file extension '{clip_path.suffix}' – proceeding anyway.")

    # Estimate duration from filename convention or default to 15s
    _print_plan(args, estimated_duration_s=15)

    if args.dry_run:
        print("\n  [DRY RUN] No API calls made. Remove --dry-run to execute.\n")
        return

    api_key = get_api_key()
    from google import genai

    client = genai.Client(api_key=api_key)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"  🎞️  Reading clip: {clip_path.name}  ({clip_path.stat().st_size // 1024} KB)")
    print(f"  🚀  Submitting edit request to {args.model}…")

    edit_clip(
        client=client,
        input_clip_path=clip_path,
        edit_prompt=args.edit_prompt,
        output_clip_path=out_path,
        model_id=args.model,
    )

    print_separator()
    print(f"  ✅  Edited clip saved → {out_path}")
    print_separator()


if __name__ == "__main__":
    run(parse_args())
