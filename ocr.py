from importlib.util import find_spec

_ocr = None


class OcrSetupError(RuntimeError):
    """Raised when the OCR engine is not installed correctly."""


def _get_ocr():
    global _ocr

    if _ocr is None:
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
            _ocr = PaddleOCR(lang="en")
        except RuntimeError as exc:
            if "paddlepaddle" in str(exc).lower():
                raise OcrSetupError(
                    "PaddleOCR needs the 'paddlepaddle' runtime, but it is not "
                    "installed in this virtual environment. Install the CPU "
                    "runtime with: python -m pip install paddlepaddle"
                ) from exc
            raise

    return _ocr


def _extract_texts_from_result(result):
    texts = []

    for page in result or []:
        if isinstance(page, dict):
            texts.extend(text for text in page.get("rec_texts", []) if text)
            continue

        # PaddleOCR 2.x returned a nested list shaped like:
        # [[box, (text, confidence)], ...]
        for line in page or []:
            try:
                text = line[1][0]
            except (IndexError, TypeError):
                continue
            if text:
                texts.append(text)

    return texts


def extract_text(image_path):
    ocr = _get_ocr()
    return _extract_texts_from_result(ocr.predict(image_path))
