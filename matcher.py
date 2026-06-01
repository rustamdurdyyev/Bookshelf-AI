from difflib import SequenceMatcher
import json
import re
import unicodedata
from urllib.parse import urlencode
from urllib.request import urlopen


CONNECTOR_WORDS = {
    "a",
    "al",
    "ale",
    "and",
    "cu",
    "de",
    "din",
    "lui",
    "of",
    "si",
    "sub",
    "the",
}

OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"


def _strip_accents(text):
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _clean_line(text):
    text = _strip_accents(str(text))
    text = text.replace("•", " ")
    text = text.replace("·", " ")
    text = text.replace("|", "I")
    text = re.sub(r"[^A-Za-z0-9\s:,.!?'-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,:;-")


def _normalized_text(text):
    text = _strip_accents(text).lower()
    words = re.findall(r"[a-z0-9]+", text)
    return " ".join(words)


def _is_noise(text):
    words = _normalized_text(text).split()

    if not words:
        return True
    if len(words) == 1:
        word = words[0]
        if len(word) <= 2 and not word.isdigit():
            return True
        if word.isdigit() and len(word) < 3:
            return True
    if all(word.isdigit() for word in words):
        return True

    return False


def _should_join_with_next(current, next_line):
    current_words = _normalized_text(current).split()
    next_words = _normalized_text(next_line).split()

    if not current_words or not next_words:
        return False
    if current_words[-1] in CONNECTOR_WORDS:
        return True
    if len(current_words) == 1 and current_words[0] in CONNECTOR_WORDS:
        return True
    if len(next_words) == 1 and next_words[0] in CONNECTOR_WORDS:
        return True
    if current_words[0].isdigit() and len(current_words) <= 4:
        return True
    if current.isupper() and next_line.isupper() and len(current_words) <= 3:
        return True

    return False


def _merge_split_lines(lines):
    merged = []
    index = 0

    while index < len(lines):
        current = lines[index]

        while index + 1 < len(lines) and _should_join_with_next(
            current, lines[index + 1]
        ):
            current = f"{current} {lines[index + 1]}"
            index += 1

        merged.append(current)
        index += 1

    return merged


def _candidate_phrases(lines, max_joined_lines=3):
    candidates = list(lines)

    for start in range(len(lines)):
        parts = []
        for end in range(start, min(start + max_joined_lines, len(lines))):
            parts.append(lines[end])
            if end == start:
                continue
            phrase = " ".join(parts)
            if len(_normalized_text(phrase)) >= 4:
                candidates.append(phrase)

    return _dedupe(candidates)


def _similarity(left, right):
    return SequenceMatcher(None, _normalized_text(left), _normalized_text(right)).ratio()


def _search_open_library(query, timeout=5):
    params = urlencode({"title": query, "limit": 5, "fields": "title"})
    url = f"{OPEN_LIBRARY_SEARCH_URL}?{params}"

    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError:
        return None

    docs = payload.get("docs", [])
    if not docs:
        return None

    best_title = None
    best_score = 0.0

    for doc in docs:
        title = doc.get("title")
        if not title:
            continue

        score = _similarity(query, title)
        if score > best_score:
            best_title = title
            best_score = score

    if best_score >= 0.78:
        return _clean_line(best_title)

    return None


def _title_case_if_needed(text):
    words = text.split()

    if text.isupper() and len(words) <= 8:
        return " ".join(word.capitalize() if not word.isdigit() else word for word in words)

    return text


def _dedupe(items):
    seen = set()
    unique_items = []

    for item in items:
        key = _normalized_text(item)
        if key and key not in seen:
            unique_items.append(item)
            seen.add(key)

    return unique_items


def _fallback_titles(lines):
    titles = []

    for line in lines:
        if _looks_like_title(line):
            titles.append(_title_case_if_needed(line))

    return _dedupe(titles)


def _looks_like_title(text):
    words = _normalized_text(text).split()

    if len(words) >= 3:
        return True
    if text.isupper() and len(words) >= 1:
        if len(words) == 1 and len(words[0]) <= 4:
            return False
        return True
    if any(char.isdigit() for char in text) and len(words) >= 2:
        return True
    if len(words) == 2 and all(word[:1].isupper() for word in text.split()):
        return True

    return False


def fix_book_titles(raw_texts, use_online_lookup=False, max_online_queries=40):
    cleaned_lines = []

    for raw_text in raw_texts:
        line = _clean_line(raw_text)
        words = _normalized_text(line).split()
        is_connector = len(words) == 1 and words[0] in CONNECTOR_WORDS

        if line and (is_connector or not _is_noise(line)):
            cleaned_lines.append(line)

    merged_lines = _merge_split_lines(cleaned_lines)

    if not use_online_lookup:
        return _fallback_titles(merged_lines)

    fixed_titles = []
    query_count = 0

    for candidate in _candidate_phrases(merged_lines):
        title = None

        if query_count < max_online_queries:
            title = _search_open_library(candidate)
            query_count += 1

        if title:
            fixed_titles.append(title)

    fallback_titles = [
        _title_case_if_needed(line) for line in merged_lines if _looks_like_title(line)
    ]

    return _dedupe(fixed_titles + fallback_titles)
