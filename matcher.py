from difflib import SequenceMatcher
from functools import lru_cache
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

GOOGLE_BOOKS_SEARCH_URL = "https://www.googleapis.com/books/v1/volumes"
OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"

METADATA_WORDS = {
    "author",
    "authior",
    "bestselling",
    "headline",
    "oreilly",
    "press",
    "rentselling",
    "selling",
}

METADATA_PHRASES = {
    "best selling author",
    "bestselling author",
    "new york times",
    "o reilly",
    "rentselling authior",
    "st martin s press",
}

TITLE_WORD_HINTS = {
    "brood",
    "clash",
    "crows",
    "dance",
    "dangerous",
    "dragons",
    "game",
    "kings",
    "murders",
    "programming",
    "relic",
    "rose",
    "scala",
    "storm",
    "swords",
    "thrones",
    "vipers",
    "white",
    "women",
}

TITLE_VARIANT_STOP_WORDS = CONNECTOR_WORDS | {
    "at",
    "by",
    "for",
    "from",
    "in",
    "on",
    "to",
    "with",
}


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


@lru_cache(maxsize=256)
def _search_google_books(query, author=None, timeout=5):
    book_query = f"intitle:{query}"
    if author:
        book_query = f"{book_query} inauthor:{author}"

    params = urlencode(
        {
            "q": book_query,
            "maxResults": 5,
            "fields": "items/volumeInfo(title,authors)",
        }
    )
    url = f"{GOOGLE_BOOKS_SEARCH_URL}?{params}"

    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError:
        return None

    items = payload.get("items", [])
    if not items:
        return None

    best_match = None
    best_score = 0.0

    for item in items:
        volume_info = item.get("volumeInfo", {})
        title = volume_info.get("title")
        if not title:
            continue

        title_score = _similarity(query, title)
        score = title_score

        if author:
            author_scores = [
                _similarity(author, found_author)
                for found_author in volume_info.get("authors", [])
            ]
            author_score = max(author_scores, default=0.0)
            score = (title_score * 0.75) + (author_score * 0.25)

        if score > best_score:
            best_match = title
            best_score = score

    min_score = 0.58 if author else 0.62
    if best_score >= min_score:
        return _clean_line(best_match)

    return None


@lru_cache(maxsize=256)
def _search_open_library(query, author=None, timeout=8):
    params = {
        "title": query,
        "limit": 5,
        "fields": "title,author_name",
    }
    if author:
        params["author"] = author

    url = f"{OPEN_LIBRARY_SEARCH_URL}?{urlencode(params)}"

    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError:
        return None

    docs = payload.get("docs", [])
    if not docs:
        return None

    best_match = None
    best_score = 0.0

    for doc in docs:
        title = doc.get("title")
        if not title:
            continue

        title_score = _similarity(query, title)
        score = title_score

        if author:
            author_scores = [
                _similarity(author, found_author)
                for found_author in doc.get("author_name", [])
            ]
            author_score = max(author_scores, default=0.0)
            score = (title_score * 0.75) + (author_score * 0.25)

        if score > best_score:
            best_match = title
            best_score = score

    if best_score >= 0.48:
        return _clean_line(best_match)

    return None


def _meaningful_words(text):
    return {w for w in _normalized_text(text).split() if len(w) >= 4}


def _fragment_queries(text):
    words = _normalized_text(text).split()
    fragments = []
    for i in range(len(words)):
        if i + 2 <= len(words):
            frag = words[i:i + 2]
            if any(len(w) >= 4 for w in frag):
                fragments.append(" ".join(frag))
        if i + 3 <= len(words):
            frag = words[i:i + 3]
            if any(len(w) >= 4 for w in frag):
                fragments.append(" ".join(frag))
    return _dedupe(fragments)


@lru_cache(maxsize=256)
def _verify_title(title, timeout=5):
    params = urlencode({"q": f"intitle:\"{title}\"", "maxResults": 3, "fields": "items/volumeInfo/title"})
    url = f"{GOOGLE_BOOKS_SEARCH_URL}?{params}"
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError:
        return None
    for item in (payload.get("items") or []):
        found = item.get("volumeInfo", {}).get("title")
        if found and _similarity(title, found) >= 0.85:
            return _clean_line(found)
    return None


def _search_best_title(ocr_line, remaining_queries, author=None):
    ocr_words = _meaningful_words(ocr_line)
    query_count = 0

    search_attempts = []
    if author:
        search_attempts.append((ocr_line, author))
    search_attempts.append((ocr_line, None))

    for query, query_author in search_attempts:
        if query_count >= remaining_queries:
            break

        result = _search_google_books(query, query_author)
        query_count += 1
        if result is None:
            result = _search_open_library(query, query_author)
        if result and ocr_words & _meaningful_words(result):
            return result, query_count

    for fragment in _fragment_queries(ocr_line):
        if query_count >= remaining_queries:
            break

        result = _search_google_books(fragment)
        query_count += 1
        if result is None:
            result = _search_open_library(fragment)
        if result and ocr_words & _meaningful_words(result):
            return result, query_count

    return None, query_count


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


def _title_content_words(text):
    return [
        word
        for word in _normalized_text(text).split()
        if word not in TITLE_VARIANT_STOP_WORDS
    ]


def _same_title_variant(left, right):
    left_key = _normalized_text(left)
    right_key = _normalized_text(right)

    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True

    left_words = left_key.split()
    right_words = right_key.split()
    if len(left_words) == 2 and left_words == list(reversed(right_words)):
        return True

    left_content = set(_title_content_words(left))
    right_content = set(_title_content_words(right))

    if left_content and left_content == right_content:
        return True

    short_content, long_content = sorted(
        (left_content, right_content),
        key=len,
    )
    similarity = SequenceMatcher(None, left_key, right_key).ratio()

    if len(short_content) >= 2 and short_content <= long_content:
        return True
    if len(short_content) == 1 and short_content <= long_content and similarity >= 0.5:
        return True

    return similarity >= 0.9


def _title_quality(title):
    words = _normalized_text(title).split()
    content_words = _title_content_words(title)
    score = len(words) + (len(content_words) * 2)

    if any(word in CONNECTOR_WORDS for word in words):
        score += 1
    if len(content_words) <= 1:
        score -= 3
    if _looks_like_author(title):
        score -= 4

    return score


def _dedupe_titles(titles):
    unique_titles = []

    for title in titles:
        cleaned_title = _clean_line(title)
        if not cleaned_title:
            continue

        matching_index = next(
            (
                index
                for index, existing_title in enumerate(unique_titles)
                if _same_title_variant(cleaned_title, existing_title)
            ),
            None,
        )

        if matching_index is None:
            unique_titles.append(cleaned_title)
            continue

        if _title_quality(cleaned_title) > _title_quality(unique_titles[matching_index]):
            unique_titles[matching_index] = cleaned_title

    return unique_titles


def _candidate_lookup_score(text):
    words = _normalized_text(text).split()
    if not words:
        return 0

    score = min(len(words), 6)

    if any(word in CONNECTOR_WORDS for word in words):
        score += 3
    if any(char.isdigit() for char in text):
        score += 2
    if _looks_like_title(text):
        score += 2
    if len(words) == 1:
        score -= 3

    return score


def _natural_order_score(text):
    words = _normalized_text(text).split()
    if not words:
        return 0

    score = 0
    strong_trailing_connectors = CONNECTOR_WORDS - {"a"}
    strong_leading_connectors = strong_trailing_connectors - {"the"}

    if words[-1] in strong_trailing_connectors:
        score -= 4
    if words[0] in strong_leading_connectors:
        score -= 3

    for left, right in zip(words, words[1:]):
        if (left, right) in {("of", "the"), ("de", "la"), ("din", "lui")}:
            score += 2

    raw_words = re.findall(r"[A-Za-z][A-Za-z.'-]*", _strip_accents(text))
    if len(raw_words) >= 2:
        first_word = raw_words[0]
        last_word = raw_words[-1]
        if first_word[:1].islower() and last_word[:1].isupper():
            score -= 2
        elif first_word[:1].isupper() and last_word[:1].islower():
            score += 1

    return score


def _prioritized_candidates(lines):
    candidates = _candidate_phrases(lines)
    return sorted(
        candidates,
        key=lambda item: -(_candidate_lookup_score(item) + _natural_order_score(item)),
    )


def _entry_box(entry):
    box = entry.get("layout_box") or entry.get("box")
    if not box or len(box) < 4:
        return None

    try:
        left, top, right, bottom = (float(value) for value in box[:4])
    except (TypeError, ValueError):
        return None

    if right <= left or bottom <= top:
        return None

    return left, top, right, bottom


def _box_center_x(box):
    return (box[0] + box[2]) / 2


def _box_center_y(box):
    return (box[1] + box[3]) / 2


def _box_height(box):
    return max(1.0, box[3] - box[1])


def _box_width(box):
    return max(1.0, box[2] - box[0])


def _row_center(row):
    return (row["top"] + row["bottom"]) / 2


def _column_center(column):
    return (column["left"] + column["right"]) / 2


def _same_row(row, item):
    box = item["box"]
    overlap = max(0.0, min(row["bottom"], box[3]) - max(row["top"], box[1]))
    min_height = min(max(1.0, row["bottom"] - row["top"]), _box_height(box))
    center_gap = abs(_box_center_y(box) - _row_center(row))
    max_center_gap = max(12.0, min_height * 0.8)

    return overlap / min_height >= 0.35 or center_gap <= max_center_gap


def _same_column(column, item):
    box = item["box"]
    overlap = max(0.0, min(column["right"], box[2]) - max(column["left"], box[0]))
    min_width = min(max(1.0, column["right"] - column["left"]), _box_width(box))
    center_gap = abs(_box_center_x(box) - _column_center(column))
    max_center_gap = max(10.0, min_width * 0.8)

    return overlap / min_width >= 0.35 or center_gap <= max_center_gap


def _add_to_row(row, item):
    row["items"].append(item)
    row["top"] = min(row["top"], item["box"][1])
    row["bottom"] = max(row["bottom"], item["box"][3])


def _add_to_column(column, item):
    column["items"].append(item)
    column["left"] = min(column["left"], item["box"][0])
    column["right"] = max(column["right"], item["box"][2])


def _clean_entry(entry, item_id=None):
    line = _clean_line(entry.get("text", ""))
    words = _normalized_text(line).split()
    is_connector = len(words) == 1 and words[0] in CONNECTOR_WORDS

    if not line or (not is_connector and _is_noise(line)):
        return None

    box = _entry_box(entry)
    return {
        "id": item_id,
        "text": line,
        "score": entry.get("score"),
        "box": box,
    }


def _entries_by_source_rotation(entries):
    groups = {}

    for item_id, entry in enumerate(entries):
        rotation = entry.get("source_rotation", 0)
        grouped_entry = dict(entry)
        grouped_entry["_match_id"] = f"{rotation}:{item_id}"
        groups.setdefault(rotation, []).append(grouped_entry)

    def rotation_order(rotation):
        return (rotation != 0, rotation)

    return [
        (rotation, groups[rotation])
        for rotation in sorted(groups, key=rotation_order)
    ]


def _group_entries_by_rows(entries):
    rows = []
    unboxed_lines = []

    for item_id, entry in enumerate(entries):
        item = _clean_entry(entry, entry.get("_match_id", item_id))
        if not item:
            continue
        if not item["box"]:
            unboxed_lines.append(item["text"])
            continue

        rows.append(
            {
                "top": item["box"][1],
                "bottom": item["box"][3],
                "items": [item],
            }
        )

    rows.sort(key=_row_center)
    merged_rows = []

    for row in rows:
        item = row["items"][0]
        matching_row = next(
            (candidate for candidate in merged_rows if _same_row(candidate, item)),
            None,
        )

        if matching_row:
            _add_to_row(matching_row, item)
        else:
            merged_rows.append(row)

    for row in merged_rows:
        row["items"].sort(key=lambda item: _box_center_x(item["box"]))

    return merged_rows, unboxed_lines


def _split_column_by_vertical_gaps(column):
    items = sorted(column["items"], key=lambda item: _box_center_y(item["box"]))
    if len(items) <= 1:
        return [{**column, "items": items}]

    heights = sorted(_box_height(item["box"]) for item in items)
    median_height = heights[len(heights) // 2]
    max_gap = max(80.0, median_height * 3.0)
    split_columns = []
    current_items = [items[0]]

    for previous, item in zip(items, items[1:]):
        gap = item["box"][1] - previous["box"][3]
        if gap > max_gap:
            split_columns.append(current_items)
            current_items = [item]
        else:
            current_items.append(item)

    split_columns.append(current_items)

    return [
        {
            "left": min(item["box"][0] for item in group),
            "right": max(item["box"][2] for item in group),
            "items": group,
        }
        for group in split_columns
    ]


def _group_entries_by_columns(entries):
    columns = []
    unboxed_lines = []

    for item_id, entry in enumerate(entries):
        item = _clean_entry(entry, entry.get("_match_id", item_id))
        if not item:
            continue
        if not item["box"]:
            unboxed_lines.append(item["text"])
            continue

        columns.append(
            {
                "left": item["box"][0],
                "right": item["box"][2],
                "items": [item],
            }
        )

    columns.sort(key=_column_center)
    merged_columns = []

    for column in columns:
        item = column["items"][0]
        matching_column = next(
            (
                candidate
                for candidate in merged_columns
                if _same_column(candidate, item)
            ),
            None,
        )

        if matching_column:
            _add_to_column(matching_column, item)
        else:
            merged_columns.append(column)

    split_columns = []
    for column in merged_columns:
        split_columns.extend(_split_column_by_vertical_gaps(column))

    for column in split_columns:
        column["items"].sort(key=lambda item: _box_center_y(item["box"]))

    return split_columns, unboxed_lines


def _looks_like_author(text):
    words = _normalized_text(text).split()
    if any(word in TITLE_WORD_HINTS or word.endswith("ing") for word in words):
        return False
    if len(words) == 4 and not any(len(word) == 1 for word in words):
        return False
    if len(words) not in {2, 3, 4}:
        return False
    if any(word in CONNECTOR_WORDS for word in words):
        return False
    if any(char.isdigit() for char in text):
        return False

    raw_words = re.findall(r"[A-Za-z][A-Za-z.'-]*", _strip_accents(text))
    if not 2 <= len(raw_words) <= 4:
        return False

    capitalized_words = sum(
        1 for word in raw_words if word[:1].isupper() or word.isupper()
    )
    if len(words) == 4 and any(len(word) == 1 for word in words):
        return capitalized_words >= len(raw_words) - 1

    return capitalized_words == len(raw_words)


def _segment_has_title_cue(text):
    words = _normalized_text(text).split()
    if len(words) >= 3:
        return True
    if any(word in CONNECTOR_WORDS for word in words):
        return True
    if any(char.isdigit() for char in text):
        return True
    if text.isupper() and words and len(words[0]) > 4:
        return True
    return False


def _segment_ids(segment):
    return {item_id for item_id in segment["ids"] if item_id is not None}


def _author_candidate_at(segments, index):
    segment = segments[index]
    text = segment["text"]

    if _looks_like_author(text):
        return text, _segment_ids(segment), index, index

    if index + 1 >= len(segments):
        return None

    next_segment = segments[index + 1]
    combined_text = f"{text} {next_segment['text']}"
    if _looks_like_author(combined_text):
        return (
            combined_text,
            _segment_ids(segment) | _segment_ids(next_segment),
            index,
            index + 1,
        )

    return None


def _nearest_author(segments, start, end):
    best_author = None
    best_author_ids = set()
    best_distance = None
    best_index = None

    for index in range(len(segments)):
        author_candidate = _author_candidate_at(segments, index)
        if not author_candidate:
            continue

        author, author_ids, author_start, author_end = author_candidate
        if author_start <= end and author_end >= start:
            continue

        distance = min(abs(author_end - start), abs(author_start - end))
        if best_distance is None or distance < best_distance:
            best_author = author
            best_author_ids = author_ids
            best_distance = distance
            best_index = author_start

    return best_author, best_index, best_author_ids


def _merge_split_items(items):
    segments = []
    index = 0

    while index < len(items):
        current_text = items[index]["text"]
        current_ids = [items[index]["id"]]
        current_scores = [items[index].get("score")]

        while index + 1 < len(items) and _should_join_with_next(
            current_text, items[index + 1]["text"]
        ):
            current_text = f"{current_text} {items[index + 1]['text']}"
            current_ids.append(items[index + 1]["id"])
            current_scores.append(items[index + 1].get("score"))
            index += 1

        numeric_scores = [score for score in current_scores if score is not None]
        min_score = min(numeric_scores) if numeric_scores else None
        segments.append({"text": current_text, "ids": current_ids, "score": min_score})
        index += 1

    return segments


def _ordered_title_candidates(items):
    segments = _merge_split_items(items)
    candidates = []

    for start in range(len(segments)):
        parts = []
        for end in range(start, min(start + 3, len(segments))):
            parts.append(segments[end])
            title = " ".join(part["text"] for part in parts)
            words = _normalized_text(title).split()
            author, author_index, author_ids = _nearest_author(segments, start, end)
            has_title_shape = _looks_like_title(title)
            part_scores = [
                part["score"] for part in parts if part.get("score") is not None
            ]
            min_part_score = min(part_scores) if part_scores else 1.0
            average_part_score = (
                sum(part_scores) / len(part_scores)
                if part_scores
                else 1.0
            )

            if author and len(words) == 1 and len(words[0]) >= 5 and min_part_score >= 0.9:
                has_title_shape = True

            if not words or not has_title_shape:
                continue
            if len(segments) == 1 and _looks_like_author(title):
                continue
            if len(parts) == 1 and _looks_like_author(title) and not author:
                continue

            authorish_parts = [
                part for part in parts if _looks_like_author(part["text"])
            ]
            non_authorish_parts = [
                part for part in parts if not _looks_like_author(part["text"])
            ]
            if authorish_parts and non_authorish_parts:
                has_non_author_title_cue = any(
                    _segment_has_title_cue(part["text"])
                    for part in non_authorish_parts
                )
                if not has_non_author_title_cue:
                    continue

            score = _candidate_lookup_score(title)
            score += _natural_order_score(title)
            weak_parts = [
                part["text"]
                for part in parts
                if not _segment_has_title_cue(part["text"])
            ]

            if len(parts) > 1:
                score += 1
            if author:
                score += 2
                if author_index is not None and author_index < start:
                    score += 1
            if (
                any(_looks_like_author(part["text"]) for part in parts)
                and len(segments) > 1
            ):
                score -= 4
            if len(parts) > 1:
                score -= len(weak_parts) * 3

            if score <= 0:
                continue

            item_ids = {
                item_id
                for part in parts
                for item_id in part["ids"]
                if item_id is not None
            }

            candidates.append(
                {
                    "title": title,
                    "author": author,
                    "score": score,
                    "ocr_score": min_part_score,
                    "average_ocr_score": average_part_score,
                    "part_texts": [part["text"] for part in parts],
                    "item_ids": item_ids,
                    "support_ids": item_ids | author_ids,
                }
            )

    candidates.sort(key=lambda candidate: -candidate["score"])
    return candidates


def _row_title_candidates(row):
    return _ordered_title_candidates(row["items"])


def _column_title_candidates(column):
    candidates = []

    for direction, items in (
        ("top-to-bottom", column["items"]),
        ("bottom-to-top", list(reversed(column["items"]))),
    ):
        for candidate in _ordered_title_candidates(items):
            candidates.append({**candidate, "direction": direction})

    candidates.sort(key=lambda candidate: -candidate["score"])
    return candidates


def _layout_title_candidates(entries):
    candidates = []

    for rotation, rotation_entries in _entries_by_source_rotation(entries):
        rows, unboxed_lines = _group_entries_by_rows(rotation_entries)
        columns, _column_unboxed_lines = _group_entries_by_columns(rotation_entries)

        for row_index, row in enumerate(rows):
            for candidate in _row_title_candidates(row):
                candidates.append(
                    {
                        **candidate,
                        "orientation": "row",
                        "source_rotation": rotation,
                        "row_index": row_index,
                    }
                )

        for column_index, column in enumerate(columns):
            if len(column["items"]) < 2:
                continue

            for candidate in _column_title_candidates(column):
                candidates.append(
                    {
                        **candidate,
                        "orientation": "column",
                        "source_rotation": rotation,
                        "column_index": column_index,
                    }
                )

        for line in _merge_split_lines(unboxed_lines):
            if _looks_like_title(line):
                candidates.append(
                    {
                        "title": line,
                        "author": None,
                        "score": _candidate_lookup_score(line),
                        "ocr_score": 1.0,
                        "average_ocr_score": 1.0,
                        "part_texts": [line],
                        "item_ids": set(),
                        "orientation": "unboxed",
                        "source_rotation": rotation,
                        "row_index": None,
                    }
                )

    candidates.sort(
        key=lambda candidate: -_candidate_selection_score(candidate)
    )
    return candidates


def _candidate_selection_score(candidate):
    item_count = len(candidate.get("item_ids", set()))
    score = candidate["score"]
    score += candidate.get("average_ocr_score", 1.0) * 3

    if candidate.get("direction") == "top-to-bottom":
        score += 1
    elif candidate.get("direction") == "bottom-to-top":
        score -= 1

    if item_count <= 1:
        score += 5
    else:
        score -= (item_count - 1) * 4

    return score


def _fallback_titles_from_layout(entries):
    titles = []
    used_item_ids = set()
    candidates = _layout_title_candidates(entries)
    author_words = _author_words_from_entries(entries)
    author_words.update(_author_words_from_candidates(candidates))

    for candidate in candidates:
        if not _good_fallback_candidate(candidate, author_words):
            continue
        item_ids = set(candidate.get("support_ids", candidate.get("item_ids", set())))
        if item_ids and item_ids & used_item_ids:
            continue

        if _is_reversed_two_word_duplicate(candidate["title"], titles):
            continue

        titles.append(_title_case_if_needed(candidate["title"]))
        used_item_ids.update(item_ids)

    return _dedupe_titles(titles)


def _is_reversed_two_word_duplicate(title, accepted_titles):
    words = _normalized_text(title).split()
    if len(words) != 2:
        return False

    reversed_title = " ".join(reversed(words))
    return any(
        _normalized_text(accepted_title) == reversed_title
        for accepted_title in accepted_titles
    )


def _author_words_from_entries(entries):
    author_words = set()

    for entry in entries:
        text = _clean_line(entry.get("text", ""))
        if _looks_like_author(text):
            author_words.update(
                word
                for word in _normalized_text(text).split()
                if len(word) > 1
            )

    return author_words


def _author_words_from_candidates(candidates):
    author_words = set()

    for candidate in candidates:
        author = candidate.get("author")
        if author:
            author_words.update(
                word
                for word in _normalized_text(author).split()
                if len(word) > 1
            )

        for part in candidate.get("part_texts", []):
            if _looks_like_author(part):
                author_words.update(
                    word
                    for word in _normalized_text(part).split()
                    if len(word) > 1
                )

    return author_words


def _word_matches_author_word(word, author_words):
    if not word or not author_words:
        return False
    if word in author_words:
        return True
    if len(word) < 4:
        return False

    for author_word in author_words:
        if len(author_word) < 4:
            continue
        if word.startswith(author_word) or author_word.startswith(word):
            return True
        if SequenceMatcher(None, word, author_word).ratio() >= 0.78:
            return True

    return False


def _contains_title_hint(words):
    return any(word in TITLE_WORD_HINTS or word in CONNECTOR_WORDS for word in words)


def _part_is_authorish(part_text, author_words):
    words = _normalized_text(part_text).split()
    if not words:
        return False
    if _looks_like_author(part_text):
        return True

    meaningful_words = [word for word in words if len(word) > 1]
    return bool(meaningful_words) and all(
        _word_matches_author_word(word, author_words)
        for word in meaningful_words
    )


def _has_author_title_mix(words, author_words):
    if not words:
        return False

    has_author_word = any(
        _word_matches_author_word(word, author_words)
        for word in words
    )
    has_title_word = any(word in TITLE_WORD_HINTS for word in words)

    return has_author_word and has_title_word


def _good_fallback_candidate(candidate, author_words=None):
    author_words = author_words or set()
    title = candidate["title"]
    words = _normalized_text(title).split()
    part_texts = candidate.get("part_texts") or [title]

    if not words:
        return False
    if candidate.get("ocr_score", 1.0) < 0.72:
        return False
    if _looks_like_metadata_fragment(title):
        return False
    if _looks_like_author(title) and not _contains_title_hint(words):
        return False
    if _has_author_title_mix(words, author_words):
        return False
    if len(words) == 1:
        return False
    if len(words) >= 8 and not any(word in CONNECTOR_WORDS for word in words):
        return False
    if len(candidate.get("item_ids", set())) > 3:
        return False
    if len(part_texts) > 1 and not _parts_should_form_one_title(part_texts):
        return False
    if len(part_texts) > 1 and any(
        _part_is_authorish(part, author_words)
        for part in part_texts
    ):
        return False
    if _looks_like_garbage_title(title):
        return False

    return candidate["score"] >= 3


def _looks_like_metadata_fragment(text):
    normalized = _normalized_text(text)
    words = normalized.split()
    raw_words = re.findall(r"[A-Za-z][A-Za-z.'-]*", _strip_accents(text))

    if not words:
        return True
    if normalized in METADATA_WORDS:
        return True
    if set(words) <= METADATA_WORDS:
        return True
    if any(phrase in normalized for phrase in METADATA_PHRASES):
        return True
    if len(raw_words) == 1 and any(char in raw_words[0] for char in {"'", ".", "-"}):
        return True
    if len(words) <= 4 and words[:1] in (["wy"], ["ny"]) and "new" in words and "york" in words:
        return True

    return False


def _parts_should_form_one_title(part_texts):
    if len(part_texts) == 2:
        word_counts = [len(_normalized_text(part).split()) for part in part_texts]
        if all(count == 1 for count in word_counts):
            return True

    for current, next_part in zip(part_texts, part_texts[1:]):
        if _should_join_with_next(current, next_part):
            return True

    return False


def _looks_like_garbage_title(text):
    words = _normalized_text(text).split()
    if not words:
        return True

    bad_words = 0
    for word in words:
        has_digit = any(char.isdigit() for char in word)
        has_alpha = any(char.isalpha() for char in word)
        if has_digit and has_alpha:
            bad_words += 1
            continue
        if len(word) >= 5 and not re.search(r"[aeiouy]", word):
            bad_words += 1

    if bad_words >= 2:
        return True
    if bad_words == 1 and len(words) <= 3:
        return True

    return False


def _fallback_titles(lines):
    titles = []

    for line in lines:
        if _looks_like_title(line):
            titles.append(_title_case_if_needed(line))

    return _dedupe_titles(titles)


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

    for candidate in _prioritized_candidates(merged_lines):
        title = None

        remaining_queries = max_online_queries - query_count
        if remaining_queries <= 0:
            break

        title, used_queries = _search_best_title(candidate, remaining_queries)
        query_count += used_queries

        if title:
            if query_count >= max_online_queries:
                continue

            verified = _verify_title(title)
            query_count += 1
            if verified:
                fixed_titles.append(verified)

    fallback_titles = [
        _title_case_if_needed(line) for line in merged_lines if _looks_like_title(line)
    ]

    return _dedupe_titles(fixed_titles + fallback_titles)


def fix_book_titles_from_entries(
    ocr_entries,
    use_online_lookup=False,
    max_online_queries=40,
):
    if not ocr_entries:
        return []

    if not any(_entry_box(entry) for entry in ocr_entries):
        return fix_book_titles(
            [entry.get("text", "") for entry in ocr_entries],
            use_online_lookup=use_online_lookup,
            max_online_queries=max_online_queries,
        )

    fallback_titles = _fallback_titles_from_layout(ocr_entries)

    if not use_online_lookup:
        return _dedupe_titles(fallback_titles)

    fixed_titles = []
    query_count = 0

    for candidate in _layout_title_candidates(ocr_entries):
        remaining_queries = max_online_queries - query_count
        if remaining_queries <= 0:
            break

        title, used_queries = _search_best_title(
            candidate["title"],
            remaining_queries,
            author=candidate["author"],
        )
        query_count += used_queries

        if title:
            fixed_titles.append(title)

    return _dedupe_titles(fixed_titles + fallback_titles)
