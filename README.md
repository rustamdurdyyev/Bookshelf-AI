# Bookshelf AI

An experimental local book discovery tool that reads a bookshelf photo, extracts possible book titles with OCR, matches those titles against online book data, and recommends books related to the detected shelf.

The current pipeline runs locally, but it still needs an internet connection for book lookup and recommendation metadata.

![Bookshelf AI](Bookshelf_AI.jpg)

## What It Does

- Reads text from bookshelf photos using PaddleOCR, including rotated OCR passes.
- Groups OCR fragments by detected layout position.
- Cleans noisy OCR fragments into possible title and author candidates.
- Optionally matches candidate titles with Google Books and Open Library.
- Uses Open Library metadata to infer language, subjects, and related books.
- Prints detected titles and recommended books in the terminal.

## Project Structure

```text
main.py           Entry point for the full pipeline
streamlit_app.py  Streamlit interface for upload/camera plus Groq vision
ocr.py            PaddleOCR setup and OCR result parsing
matcher.py        Layout-aware OCR cleanup and optional Google Books title matching
recommender.py    Open Library based recommendation engine
requirements.txt  Python dependencies
bookshelf.jpg     Sample bookshelf image for testing
```

## Requirements

- Python 3.9 or higher
- Internet connection for Groq API requests in the Streamlit app
- A Groq API key saved locally in `.env` or in Streamlit Cloud secrets

The Streamlit deployment uses a lightweight Groq vision pipeline. The older
local OCR pipeline is still available, but its heavier dependencies live in
`requirements-ocr.txt`.

## Installation

Clone the repository:

```bash
git clone https://github.com/rustamdurdyyev/Bookshelf-AI
cd Bookshelf-AI
```

Create and activate a virtual environment:

```bash
python -m venv .venv
```

On Windows:

```bash
.venv\Scripts\activate
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

To use the older local OCR command-line pipeline, install its optional
dependencies too:

```bash
python -m pip install -r requirements-ocr.txt
```

## Usage

Run the pipeline with the default image configured in `main.py`:

```bash
python main.py
```

Run it with a specific bookshelf photo:

```bash
python main.py bookshelf.jpg
```

Choose an OCR language when the shelf is not primarily English:

```bash
python main.py bookshelf.jpg --ocr-lang ro
python main.py bookshelf_turkish.png --ocr-lang tr
python main.py bookshelf_russian.webp --ocr-lang ru
```

Change the number of recommendations:

```bash
python main.py bookshelf.jpg --limit 5
```

Adjust OCR confidence filtering:

```bash
python main.py bookshelf.jpg --min-ocr-score 0.6
```

Control OCR rotations:

```bash
python main.py bookshelf.jpg --ocr-rotations 0
python main.py bookshelf.jpg --ocr-rotations 0,90,180,270
```

Control how many online title lookups are attempted:

```bash
python main.py bookshelf.jpg --max-title-lookups 10
```

Skip online title matching and use only cleaned OCR text:

```bash
python main.py bookshelf.jpg --offline-title-matching
```

Debug OCR and title extraction without generating recommendations:

```bash
python main.py bookshelf.jpg --skip-recommendations
```

Supported image formats include `.jpg`, `.jpeg`, `.png`, and `.webp`.

## Test Groq Vision

You can also test Groq vision before adding the Streamlit interface. This sends
local bookshelf photos to Groq and prints detected books plus
recommendations as JSON.

Set your API key locally. Do not commit it to the repository. The local `.env`
file is ignored by Git, so you can put your real key there:

```text
GROQ_API_KEY=your_groq_api_key_here
```

You can also set the key only for your current terminal session.

On Windows PowerShell:

```powershell
$env:GROQ_API_KEY = "your_groq_api_key_here"
```

Run the Groq check:

```bash
python groq_check.py bookshelf.jpg
```

Run it with a few photos:

```bash
python groq_check.py bookshelf.jpg bookshelf_rupam.jpeg --limit 5
```

Use a language hint when helpful:

```bash
python groq_check.py bookshelf_turkish.png --language Turkish
```

The default Groq model is `qwen/qwen3.8-27b`, because it supports vision and
JSON mode with the model access currently available to this project.

## Run Streamlit Locally

After setting `GROQ_API_KEY` in `.env`, start the local app:

```bash
streamlit run streamlit_app.py
```

The Streamlit interface lets you upload bookshelf images, capture camera photos,
choose the Groq model, and generate detected books plus recommendations.

## Deploy on Streamlit Community Cloud

Push this repository to GitHub, then create a new app at Streamlit Community
Cloud with:

- Repository: `rustamdurdyyev/Bookshelf-AI`
- Branch: your deployment branch
- Main file path: `streamlit_app.py`

In Advanced settings, add this secret:

```toml
GROQ_API_KEY = "your_groq_api_key_here"
```

Do not commit `.env` or `.streamlit/secrets.toml`; both are ignored by Git.

## How It Works

1. OCR: `ocr.py` extracts raw text from the image at one or more rotations.
2. Layout grouping: `matcher.py` groups nearby OCR boxes that likely belong to the same book, whether the text is arranged in rows or columns.
3. Cleanup: `matcher.py` removes noise, tries top-to-bottom and bottom-to-top column reading order, merges split title fragments, and avoids using nearby author-only rows as titles.
4. Matching: `matcher.py` can search Google Books and Open Library using title candidates and nearby author hints.
5. Recommendation: `recommender.py` searches Open Library for language and subject metadata, then recommends related titles.

## Current Limitations

- OCR defaults to English unless `--ocr-lang` is provided.
- Mixed-language shelves may need multiple runs with different OCR languages.
- Multi-rotation OCR is slower than a single OCR pass.
- Layout-aware title matching is still heuristic and may need manual review for difficult photos.
- Recommendations are only as good as the detected title list.
- There is no review step yet for confirming detected books before recommendations are generated.

## Suggested Next Improvements

1. Add stricter title matching with confidence thresholds.
2. Cache Google Books and Open Library responses.
3. Add a confirmation step before generating recommendations.
4. Include OCR bounding boxes in debug output.

## License

This project is open source. Feel free to use, modify, and share.
