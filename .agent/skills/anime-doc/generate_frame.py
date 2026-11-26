import os
import sys
import argparse
from pathlib import Path
from google import genai
from google.genai import types

STYLE_LOCK = (
    "1990s classic Japanese cel-animation style inspired by Ramayana: The Legend of Prince Rama, "
    "clean hand-drawn ink outlines, warm hand-painted watercolor and gouache backgrounds, "
    "soft vintage film grain, authentic ancient Indian royal armor and jewelry, "
    "dramatic golden-hour lighting, 16:9 widescreen cinematic frame, "
    "no 3D CGI, no modern glossy anime shading, no text or watermarks."
)

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


def generate_anime_frame(prompt: str, output_path: str, model: str = "gemini-2.5-flash-image"):
    _load_dotenv_if_needed()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: Set GEMINI_API_KEY or GOOGLE_API_KEY in your environment.", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    full_prompt = f"{prompt.strip()}, {STYLE_LOCK}"

    response = client.models.generate_content(
        model=model,
        contents=[full_prompt],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio="16:9",
            ),
        ),
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            with open(out, "wb") as f:
                f.write(part.inline_data.data)
            print(f"Saved 16:9 anime frame -> {out}")
            return

    print("Error: No image returned from API.", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True, help="Scene description")
    parser.add_argument("--out", required=True, help="Output PNG path")
    parser.add_argument("--model", default="gemini-2.5-flash-image")
    args = parser.parse_args()
    generate_anime_frame(args.prompt, args.out, args.model)