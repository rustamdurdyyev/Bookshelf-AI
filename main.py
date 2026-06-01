import sys

from matcher import fix_book_titles
from ocr import OcrSetupError, extract_text
from recommender import recommend_books

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

image_path = sys.argv[1] if len(sys.argv) > 1 else "Bookshelf_rupam.jpeg"

try:
    texts = extract_text(image_path)
except OcrSetupError as exc:
    print(f"OCR setup error: {exc}")
    raise SystemExit(1) from exc

print("\nRaw OCR texts:")
for t in texts:
    print(f"  {t!r}")

titles = fix_book_titles(texts, use_online_lookup=True)

print("\nFixed book titles:")
for title in titles:
    print(title)

recommendations = recommend_books(titles, limit=3)

print("\nRecommended books:")
for recommendation in recommendations:
    print(f"{recommendation['title']} - {recommendation['reason']}")
