import argparse
import json
import sys

from groq_bookshelf import (
    DEFAULT_GROQ_MODEL,
    GroqBookshelfError,
    analyze_bookshelf_images,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test Groq vision on bookshelf photos."
    )
    parser.add_argument(
        "images",
        nargs="*",
        default=["bookshelf_rupam.jpeg"],
        help="One to five bookshelf image paths.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_GROQ_MODEL,
        help="Groq vision model to use.",
    )
    parser.add_argument(
        "--language",
        default="auto",
        help="Book language hint, or 'auto'.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of recommendations to request.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.limit < 1:
        print("--limit must be at least 1", file=sys.stderr)
        raise SystemExit(2)

    try:
        result = analyze_bookshelf_images(
            args.images,
            model=args.model,
            language=args.language,
            recommendation_limit=args.limit,
        )
    except GroqBookshelfError as exc:
        print(f"Groq bookshelf check failed: {exc}", file=sys.stderr)
        if "GROQ_API_KEY" in str(exc):
            print(
                "\nOption 1, edit .env:\n"
                "GROQ_API_KEY=your_groq_api_key_here\n"
                "\nOption 2, PowerShell environment variable:\n"
                '$env:GROQ_API_KEY = "your_groq_api_key_here"\n'
                "python groq_check.py bookshelf.jpg",
                file=sys.stderr,
            )
        raise SystemExit(1) from exc

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
