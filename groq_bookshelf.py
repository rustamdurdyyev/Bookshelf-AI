import base64
import json
import os
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageOps


GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "qwen/qwen3.8-27b"
MODEL_IMAGE_LIMITS = {
    "qwen/qwen3.6-27b": 5,
    "qwen/qwen3.8-27b": 3,
}
DEFAULT_MAX_IMAGES_PER_REQUEST = 3
MAX_IMAGE_BYTES = 19 * 1024 * 1024
LOCAL_ENV_FILE = Path(__file__).resolve().parent / ".env"
PLACEHOLDER_GROQ_API_KEY = "your_groq_api_key_here"


class GroqBookshelfError(RuntimeError):
    """Raised when the Groq bookshelf analysis cannot be completed."""


def _resize_for_vision(image, max_side):
    width, height = image.size
    longest_side = max(width, height)
    if longest_side <= max_side:
        return image

    scale = max_side / longest_side
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _jpeg_bytes(image_path, max_side=1800):
    try:
        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image = _resize_for_vision(image, max_side=max_side)

            quality = 92
            while quality >= 60:
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=quality, optimize=True)
                payload = buffer.getvalue()
                if len(payload) <= MAX_IMAGE_BYTES:
                    return payload
                quality -= 8
    except OSError as exc:
        raise GroqBookshelfError(f"Could not read image: {image_path}") from exc

    raise GroqBookshelfError(
        f"Image is still too large after resizing: {image_path}"
    )


def _image_data_url(image_path):
    image_bytes = _jpeg_bytes(image_path)
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded_image}"


def _extract_json_object(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise GroqBookshelfError("Groq did not return a JSON object.")

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GroqBookshelfError("Groq returned invalid JSON.") from exc


def _clean_env_value(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _usable_api_key(value):
    value = (value or "").strip()
    if not value or value == PLACEHOLDER_GROQ_API_KEY:
        return None
    return value


def load_local_groq_api_key(env_path=LOCAL_ENV_FILE):
    env_path = Path(env_path)
    if not env_path.is_file():
        return None

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise GroqBookshelfError(f"Could not read local env file: {env_path}") from exc

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()

        key, separator, value = line.partition("=")
        if separator and key.strip() == "GROQ_API_KEY":
            return _usable_api_key(_clean_env_value(value))

    return None


def _analysis_prompt(language, recommendation_limit):
    language_instruction = (
        "Auto-detect the language of the books."
        if language == "auto"
        else f"Prefer {language} when reading visible book text."
    )

    return f"""
Analyze the bookshelf photo or photos and recommend books.

{language_instruction}

Return only valid JSON with this exact shape:
{{
  "detected_books": [
    {{
      "title": "book title if visible",
      "author": "author if visible, otherwise empty string",
      "confidence": "high|medium|low",
      "visible_text": "the shelf text that supports this guess",
      "image_index": 1
    }}
  ],
  "shelf_profile": {{
    "languages": ["detected language names"],
    "genres": ["likely genres"],
    "notes": "short summary of the shelf"
  }},
  "recommendations": [
    {{
      "title": "recommended book title",
      "author": "author name if known",
      "genre": "genre",
      "why": "one short reason connected to the detected shelf",
      "confidence": "high|medium|low"
    }}
  ],
  "photo_quality_notes": ["short note only if an image is blurry, cropped, or hard to read"]
}}

Rules:
- Recommend {recommendation_limit} books.
- Do not invent exact detected book titles when the spine text is unreadable.
- If a book is uncertain, include it with low confidence and explain the visible text.
- Avoid recommending a book that is already detected on the shelf.
- Keep reasons practical and specific to the user's shelf.
""".strip()


def _build_content(image_paths, language, recommendation_limit):
    content = [
        {
            "type": "text",
            "text": _analysis_prompt(language, recommendation_limit),
        }
    ]

    for index, image_path in enumerate(image_paths, start=1):
        content.append({"type": "text", "text": f"Bookshelf image {index}:"})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": _image_data_url(image_path),
                },
            }
        )

    return content


def analyze_bookshelf_images(
    image_paths,
    api_key=None,
    model=DEFAULT_GROQ_MODEL,
    language="auto",
    recommendation_limit=5,
    timeout=120,
):
    api_key = (
        _usable_api_key(api_key)
        or _usable_api_key(os.environ.get("GROQ_API_KEY"))
        or load_local_groq_api_key()
    )
    if not api_key:
        raise GroqBookshelfError(
            "Missing GROQ_API_KEY. Set it in your environment or in the local .env file."
        )

    image_paths = [Path(path) for path in image_paths]
    max_images = MODEL_IMAGE_LIMITS.get(model, DEFAULT_MAX_IMAGES_PER_REQUEST)
    if not image_paths:
        raise GroqBookshelfError("At least one image path is required.")
    if len(image_paths) > max_images:
        raise GroqBookshelfError(
            f"Groq model {model} supports up to {max_images} images "
            "per request. Try fewer photos first."
        )

    for image_path in image_paths:
        if not image_path.is_file():
            raise GroqBookshelfError(f"Image file not found: {image_path}")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful book discovery assistant. You read book "
                    "spines from shelf photos and return concise JSON only."
                ),
            },
            {
                "role": "user",
                "content": _build_content(
                    image_paths,
                    language=language,
                    recommendation_limit=recommendation_limit,
                ),
            },
        ],
        "temperature": 0.2,
        "top_p": 1,
        "max_completion_tokens": 2500,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(
            GROQ_CHAT_COMPLETIONS_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Bookshelf-AI/0.1",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        response_payload = response.json()
    except requests.HTTPError as exc:
        response = exc.response
        error_body = response.text if response is not None else str(exc)
        status_code = response.status_code if response is not None else "unknown"
        raise GroqBookshelfError(
            f"Groq API error {status_code}: {error_body}"
        ) from exc
    except requests.Timeout as exc:
        raise GroqBookshelfError("Groq API request timed out.") from exc
    except requests.RequestException as exc:
        raise GroqBookshelfError(f"Could not reach Groq API: {exc}") from exc
    except ValueError as exc:
        raise GroqBookshelfError("Groq response was not valid JSON.") from exc

    try:
        message = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GroqBookshelfError("Groq response did not contain message content.") from exc

    result = _extract_json_object(message)
    result["_model"] = model
    return result
