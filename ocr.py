import re
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps

_ocr_instances = {}

SUPPORTED_LANGUAGE_EXAMPLES = "en, ro, tr, ru, de, fr, es, it, pt"
SUPPORTED_ROTATIONS = {0, 90, 180, 270}


class OcrSetupError(RuntimeError):
    """Raised when the OCR engine is not installed correctly."""


def _plain_list(value):
    if value is None:
        return None
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def _plain_score(value):
    if value is None:
        return None
    return float(value)


def normalize_rotations(rotations):
    if rotations is None:
        return (0,)

    if isinstance(rotations, str):
        values = [value.strip() for value in rotations.split(",") if value.strip()]
    else:
        values = list(rotations)

    if not values:
        return (0,)

    normalized = []
    for value in values:
        try:
            rotation = int(value) % 360
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "--ocr-rotations must contain only degrees: 0, 90, 180, 270"
            ) from exc

        if rotation not in SUPPORTED_ROTATIONS:
            raise ValueError(
                "--ocr-rotations supports only these values: 0, 90, 180, 270"
            )

        if rotation not in normalized:
            normalized.append(rotation)

    return tuple(normalized)


def _normalized_text(text):
    return " ".join(re.findall(r"[a-z0-9]+", str(text).lower()))


def _box_points(box):
    if not box or len(box) < 4:
        return []

    try:
        left, top, right, bottom = (float(value) for value in box[:4])
    except (TypeError, ValueError):
        return []

    return [
        (left, top),
        (right, top),
        (right, bottom),
        (left, bottom),
    ]


def _coerce_points(points):
    if not points:
        return []

    point_pairs = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return []

        try:
            point_pairs.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            return []

    return point_pairs


def _rotate_image(image, rotation):
    if rotation == 0:
        return image.copy()
    if rotation == 90:
        return image.transpose(Image.Transpose.ROTATE_90)
    if rotation == 180:
        return image.transpose(Image.Transpose.ROTATE_180)
    if rotation == 270:
        return image.transpose(Image.Transpose.ROTATE_270)

    raise ValueError(f"Unsupported rotation: {rotation}")


def _map_point_to_original(point, rotation, original_width, original_height):
    x, y = point

    if rotation == 0:
        original_x, original_y = x, y
    elif rotation == 90:
        original_x, original_y = original_width - y, x
    elif rotation == 180:
        original_x, original_y = original_width - x, original_height - y
    elif rotation == 270:
        original_x, original_y = y, original_height - x
    else:
        raise ValueError(f"Unsupported rotation: {rotation}")

    original_x = min(max(0.0, original_x), float(original_width))
    original_y = min(max(0.0, original_y), float(original_height))
    return original_x, original_y


def _entry_box_from_points(points):
    if not points:
        return None

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [
        int(round(min(xs))),
        int(round(min(ys))),
        int(round(max(xs))),
        int(round(max(ys))),
    ]


def _map_entry_to_original(entry, rotation, original_size):
    original_width, original_height = original_size
    mapped_entry = dict(entry)
    mapped_entry["source_rotation"] = rotation
    mapped_entry["layout_box"] = entry.get("box")
    mapped_entry["layout_poly"] = entry.get("poly")

    original_points = _coerce_points(entry.get("poly"))
    if not original_points:
        original_points = _box_points(entry.get("box"))

    if not original_points:
        return mapped_entry

    mapped_points = [
        _map_point_to_original(point, rotation, original_width, original_height)
        for point in original_points
    ]
    mapped_entry["original_box"] = _entry_box_from_points(mapped_points)
    mapped_entry["original_poly"] = [
        [int(round(x)), int(round(y))]
        for x, y in mapped_points
    ]
    return mapped_entry


def _box_iou(first, second):
    first_box = first.get("layout_box") or first.get("box")
    second_box = second.get("layout_box") or second.get("box")
    if not first_box or not second_box:
        return 0.0

    first_left, first_top, first_right, first_bottom = first_box
    second_left, second_top, second_right, second_bottom = second_box

    overlap_width = max(0, min(first_right, second_right) - max(first_left, second_left))
    overlap_height = max(0, min(first_bottom, second_bottom) - max(first_top, second_top))
    intersection = overlap_width * overlap_height
    if intersection <= 0:
        return 0.0

    first_area = max(1, (first_right - first_left) * (first_bottom - first_top))
    second_area = max(1, (second_right - second_left) * (second_bottom - second_top))
    return intersection / (first_area + second_area - intersection)


def _entry_quality(entry):
    text = str(entry.get("text", ""))
    score = entry.get("score")
    if score is None:
        score = 0.5

    length_bonus = min(len(_normalized_text(text)), 40) / 100
    return float(score) + length_bonus


def _deduplicate_entries(entries):
    selected = []

    for entry in sorted(entries, key=_entry_quality, reverse=True):
        normalized = _normalized_text(entry.get("text", ""))
        if not normalized:
            continue

        duplicate = False
        for existing in selected:
            if entry.get("source_rotation", 0) != existing.get("source_rotation", 0):
                continue

            existing_normalized = _normalized_text(existing.get("text", ""))
            iou = _box_iou(entry, existing)

            if normalized == existing_normalized and iou >= 0.45:
                duplicate = True
                break

            same_text_region = iou >= 0.85
            text_contains_other = (
                normalized in existing_normalized
                or existing_normalized in normalized
            )
            if same_text_region and text_contains_other:
                duplicate = True
                break

        if not duplicate:
            selected.append(entry)

    return sorted(
        selected,
        key=lambda entry: (
            entry.get("source_rotation", 0),
            (entry.get("layout_box") or entry.get("box") or [0, 0, 0, 0])[1],
            (entry.get("layout_box") or entry.get("box") or [0, 0, 0, 0])[0],
        ),
    )


def _get_ocr(lang="en"):
    lang = lang or "en"

    if lang not in _ocr_instances:
        if find_spec("paddle") is None:
            raise OcrSetupError(
                "PaddleOCR needs the 'paddlepaddle' runtime, but it is not "
                "installed in this virtual environment. Install the CPU "
                "runtime with: python -m pip install paddlepaddle"
            )

        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OcrSetupError(
                "PaddleOCR is not installed in this project's virtual "
                "environment. Install it with: python -m pip install paddleocr"
            ) from exc

        try:
            _ocr_instances[lang] = PaddleOCR(lang=lang)
        except ValueError as exc:
            if "No models are available" in str(exc):
                raise OcrSetupError(
                    f"Unsupported PaddleOCR language code: {lang!r}. Try a "
                    f"language code such as: {SUPPORTED_LANGUAGE_EXAMPLES}."
                ) from exc
            raise
        except RuntimeError as exc:
            if "paddlepaddle" in str(exc).lower():
                raise OcrSetupError(
                    "PaddleOCR needs the 'paddlepaddle' runtime, but it is not "
                    "installed in this virtual environment. Install the CPU "
                    "runtime with: python -m pip install paddlepaddle"
                ) from exc
            raise

    return _ocr_instances[lang]


def _extract_entries_from_result(result):
    entries = []

    for page in result or []:
        if isinstance(page, dict):
            texts = page.get("rec_texts", [])
            scores = page.get("rec_scores", [])
            boxes = page.get("rec_boxes", [])
            polys = page.get("rec_polys", [])

            for index, text in enumerate(texts):
                if not text:
                    continue

                score = scores[index] if index < len(scores) else None
                box = boxes[index] if index < len(boxes) else None
                poly = polys[index] if index < len(polys) else None
                entries.append(
                    {
                        "text": text,
                        "score": _plain_score(score),
                        "box": _plain_list(box),
                        "poly": _plain_list(poly),
                    }
                )

            continue

        # PaddleOCR 2.x returned a nested list shaped like:
        # [[box, (text, confidence)], ...]
        for line in page or []:
            try:
                box = line[0]
                text = line[1][0]
                score = line[1][1]
            except (IndexError, TypeError):
                continue
            if text:
                entries.append(
                    {
                        "text": text,
                        "score": _plain_score(score),
                        "box": _plain_list(box),
                        "poly": _plain_list(box),
                    }
                )

    return entries


def extract_text_entries(image_path, lang="en", rotations=(0,)):
    rotations = normalize_rotations(rotations)
    ocr = _get_ocr(lang)
    image_path = Path(image_path)
    all_entries = []

    with Image.open(image_path) as source_image:
        source_image = ImageOps.exif_transpose(source_image).convert("RGB")
        original_size = source_image.size

        with TemporaryDirectory(prefix="bookshelf_ai_ocr_") as temp_dir:
            temp_dir = Path(temp_dir)

            for rotation in rotations:
                rotated_image = _rotate_image(source_image, rotation)
                rotated_path = temp_dir / f"ocr_rotation_{rotation}.png"
                rotated_image.save(rotated_path)

                result = ocr.predict(str(rotated_path))
                entries = _extract_entries_from_result(result)
                all_entries.extend(
                    _map_entry_to_original(entry, rotation, original_size)
                    for entry in entries
                )

    return _deduplicate_entries(all_entries)


def extract_text(image_path, lang="en", min_score=0.0, rotations=(0,)):
    entries = extract_text_entries(image_path, lang, rotations=rotations)
    return [
        entry["text"]
        for entry in entries
        if entry["score"] is None or entry["score"] >= min_score
    ]
