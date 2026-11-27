import os
import sys
import json
import argparse
from pathlib import Path
from google import genai
from google.genai import types

SKILL_DIR = Path(__file__).resolve().parent
REFS_DIR = SKILL_DIR / "refs"
CHARS_JSON = SKILL_DIR / "characters.json"

STYLE_LOCK = (
    "1990s classic Japanese cel-animation style inspired by Ramayana: The Legend of Prince Rama, "
    "clean hand-drawn ink outlines, warm hand-painted watercolor and gouache backgrounds, "
    "soft vintage film grain, authentic ancient Indian royal armor and jewelry, "
    "dramatic golden-hour lighting, 16:9 widescreen cinematic frame, "
    "no 3D CGI, no modern glossy anime shading, no text or watermarks."
)

def load_character_refs(char_keys: list[str]) -> tuple[list[types.Part], list[str]]:
    if not CHARS_JSON.exists():
        print(f"Error: {CHARS_JSON} not found.", file=sys.stderr)
        sys.exit(1)

    char_map = json.loads(CHARS_JSON.read_text(encoding="utf-8"))
    parts = []
    loaded_names = []

    for raw_key in char_keys:
        key = raw_key.strip().lower()
        if not key:
            continue
        filename = char_map.get(key)
        if not filename:
            print(f"Warning: '{key}' not found in characters.json, skipping.", file=sys.stderr)
            continue

        img_path = REFS_DIR / filename
        if not img_path.exists():
            print(f"Warning: Reference image missing at {img_path}, skipping.", file=sys.stderr)
            continue

        mime = "image/jpeg" if img_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        parts.append(types.Part.from_bytes(data=img_path.read_bytes(), mime_type=mime))
        loaded_names.append(key)

    return parts, loaded_names

def _load_dotenv_if_needed():
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return
    for candidate in [Path.cwd() / ".env", Path(__file__).resolve().parents[3] / ".env"]:
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and v and k not in os.environ:
                    os.environ[k] = v


def generate_anime_frame(prompt: str, output_path: str, chars: str = "", model: str = "gemini-2.5-flash-image", aspect: str = "16:9"):
    _load_dotenv_if_needed()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: Set GEMINI_API_KEY or GOOGLE_API_KEY in your environment.", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    contents = []

    char_keys = [c for c in chars.split(",") if c.strip()] if chars else []
    ref_parts, loaded_names = load_character_refs(char_keys)

    if ref_parts:
        contents.extend(ref_parts)
        ref_note = (
            f"Use the provided reference image(s) for {', '.join(loaded_names)}. "
            "Strictly preserve their exact face, crown, hair, facial hair, armor colors, and design. "
            "Do NOT copy the plain parchment background from the reference images—place them naturally into the scene below. "
        )
    else:
        ref_note = ""

    style_lock = STYLE_LOCK
    if aspect == "9:16":
        style_lock = style_lock.replace("16:9 widescreen cinematic frame", "9:16 vertical cinematic frame")

    full_prompt = f"{ref_note}{prompt.strip()}, {style_lock}"
    contents.append(full_prompt)

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect,
            ),
        ),
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            out.write_bytes(part.inline_data.data)
            print(f"Saved {aspect} anime frame -> {out} (refs: {loaded_names or 'none'})")
            return

    print("Error: No image returned from API.", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True, help="Scene description")
    parser.add_argument("--out", required=True, help="Output PNG path")
    parser.add_argument("--chars", default="", help="Comma-separated character keys from characters.json")
    parser.add_argument("--model", default="gemini-2.5-flash-image")
    parser.add_argument("--aspect", default="16:9", help="Aspect ratio (e.g. 16:9 or 9:16)")
    args = parser.parse_args()
    generate_anime_frame(args.prompt, args.out, args.chars, args.model, args.aspect)