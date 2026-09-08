import argparse
import sys
from pathlib import Path
from time import perf_counter

from matcher import fix_book_titles_from_entries
from ocr import OcrSetupError, extract_text_entries, normalize_rotations
from recommender import recommend_books

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Read a bookshelf photo and recommend related books."
    )
    parser.add_argument(
        "image_path",
        nargs="?",
        default="bookshelf_rupam.jpeg",
        help="Path to the bookshelf image.",
    )
    parser.add_argument(
        "--ocr-lang",
        default="en",
        help="PaddleOCR language code to use for text recognition.",
    )
    parser.add_argument(
        "--ocr-rotations",
        default="0,90,180,270",
        help=(
            "Comma-separated OCR rotations to try. Use 0 for fastest single "
            "pass, or 0,90,180,270 for vertical/upside-down spine text."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Number of recommendations to print.",
    )
    parser.add_argument(
        "--min-ocr-score",
        type=float,
        default=0.7,
        help="Minimum OCR confidence score to keep, from 0.0 to 1.0.",
    )
    parser.add_argument(
        "--offline-title-matching",
        action="store_true",
        help="Skip online title lookup and use cleaned OCR text only.",
    )
    parser.add_argument(
        "--max-title-lookups",
        type=int,
        default=15,
        help="Maximum online title lookup attempts.",
    )
    parser.add_argument(
        "--skip-recommendations",
        action="store_true",
        help="Stop after printing detected titles.",
    )
    return parser.parse_args()


def _elapsed(start_time):
    return f"{perf_counter() - start_time:.1f}s"


def main():
    args = parse_args()

    if args.limit < 1:
        print("--limit must be at least 1")
        raise SystemExit(2)

    if not 0 <= args.min_ocr_score <= 1:
        print("--min-ocr-score must be between 0.0 and 1.0")
        raise SystemExit(2)

    if args.max_title_lookups < 0:
        print("--max-title-lookups must be 0 or greater")
        raise SystemExit(2)

    try:
        ocr_rotations = normalize_rotations(args.ocr_rotations)
    except ValueError as exc:
        print(exc)
        raise SystemExit(2) from exc

    if not Path(args.image_path).is_file():
        print(f"Image file not found: {args.image_path}")
        raise SystemExit(2)

    print(f"Reading image: {args.image_path}")
    print(f"Running OCR with language: {args.ocr_lang}")
    print(f"OCR rotations: {', '.join(str(rotation) for rotation in ocr_rotations)}")

    try:
        start_time = perf_counter()
        ocr_entries = extract_text_entries(
            args.image_path,
            lang=args.ocr_lang,
            rotations=ocr_rotations,
        )
    except OcrSetupError as exc:
        print(f"OCR setup error: {exc}")
        raise SystemExit(1) from exc

    filtered_entries = [
        entry
        for entry in ocr_entries
        if entry["score"] is None or entry["score"] >= args.min_ocr_score
    ]

    print(
        f"OCR completed in {_elapsed(start_time)}; kept {len(filtered_entries)} "
        f"of {len(ocr_entries)} text fragments."
    )

    print("\nOCR texts used for matching:")
    for entry in filtered_entries:
        score = entry["score"]
        score_label = "n/a" if score is None else f"{score:.3f}"
        box = entry.get("box")
        box_label = f" box={box}" if box else ""
        rotation = entry.get("source_rotation", 0)
        print(f"  [{score_label}] rot={rotation:>3} {entry['text']!r}{box_label}")

    start_time = perf_counter()
    print("\nProcessing possible book titles...")
    titles = fix_book_titles_from_entries(
        filtered_entries,
        use_online_lookup=not args.offline_title_matching,
        max_online_queries=args.max_title_lookups,
    )
    print(f"Title processing completed in {_elapsed(start_time)}; found {len(titles)} titles.")

    print("\nFixed book titles:")
    for title in titles:
        print(title)

    if args.skip_recommendations:
        return

    if not titles:
        print("\nNo titles detected; skipping recommendations.")
        return

    start_time = perf_counter()
    print("\nGenerating recommendations...")
    recommendations = recommend_books(titles, limit=args.limit)
    print(
        f"Recommendation lookup completed in {_elapsed(start_time)}; "
        f"found {len(recommendations)} recommendations."
    )

    print("\nRecommended books:")
    for recommendation in recommendations:
        print(f"{recommendation['title']} - {recommendation['reason']}")


if __name__ == "__main__":
    main()
