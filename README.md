# 📚 Bookshelf AI

An intelligent book discovery tool that reads your bookshelf from a photo and recommends new books to read.

Point it at a photo of your bookshelf — it extracts the titles using OCR, validates them against Open Library, and generates personalized recommendations based on your collection.

Everything runs locally with no API keys required.

---

## ✨ Features

- 📸 Extracts book titles from bookshelf photos using PaddleOCR
- 🔍 Cleans and validates detected titles via the Open Library API
- 🌍 Detects the language of your bookshelf automatically
- 🤖 Recommends new books based on genres, subjects, and themes in your collection
- 🔌 No API keys or external accounts needed

---

## 📂 Project Structure

```
main.py           Entry point — runs the full pipeline
ocr.py            OCR engine wrapper (PaddleOCR)
matcher.py        Title cleaning and Open Library matching
recommender.py    Book recommendation engine
requirements.txt  Python dependencies
bookshelf.jpg     Sample bookshelf image for testing
```

---

## 🧰 Requirements

- Python 3.9 or higher
- Internet connection (for Open Library API queries)
- PaddleOCR models are downloaded automatically on first run

---

## 📦 Installation

Clone the repository:

```bash
git clone https://github.com/rustamdurdyyev/Bookshelf-AI
cd Bookshelf-AI
```

(Optional) Create a virtual environment:

```bash
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

> Note: PaddleOCR will download its models on the first run. This may take a minute.

---

## 🚀 Usage

Run the pipeline on the default sample image:

```bash
python main.py
```

To use your own bookshelf photo, edit the `image_path` variable at the top of `main.py`:

```python
image_path = "your_bookshelf.jpg"
```

---

## 🧠 How It Works

1. **OCR** — PaddleOCR scans the image and extracts raw text from book spines
2. **Title Cleaning** — Noise, fragments, and split lines are filtered and merged
3. **Validation** — Each candidate title is matched against Open Library to get the canonical title
4. **Recommendations** — Subjects and genres from your matched books are used to find new titles you might enjoy

---

## 🔄 Supported Image Formats

`.jpg`, `.jpeg`, `.png`, `.webp`

Works best with clear, well-lit photos where book spines are visible and upright.

---

## 📜 License

This project is open-source. Feel free to use, modify, and share.
