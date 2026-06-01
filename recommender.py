import json
import re
import unicodedata
from collections import Counter
from urllib.parse import quote, urlencode
from urllib.request import urlopen


OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
OPEN_LIBRARY_LANGUAGE_URL = "https://openlibrary.org/languages"
OPEN_LIBRARY_SUBJECT_URL = "https://openlibrary.org/subjects"

_language_name_cache = {}


def _normalize(text):
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _display_title(text):
    return unicodedata.normalize("NFC", str(text)).strip()


def _read_json(url, timeout=6):
    try:
        with urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except OSError:
        return None


def _search_open_library(params, timeout=6):
    payload = _read_json(f"{OPEN_LIBRARY_SEARCH_URL}?{urlencode(params)}", timeout)
    if not payload:
        return []

    return payload.get("docs", [])


def _search_works_for_title(title, limit=8):
    return _search_open_library(
        {
            "title": title,
            "limit": limit,
            "fields": "title,language,subject",
        }
    )


def _language_name(language_code):
    if not language_code:
        return "the detected language"
    if language_code in _language_name_cache:
        return _language_name_cache[language_code]

    payload = _read_json(f"{OPEN_LIBRARY_LANGUAGE_URL}/{language_code}.json")
    if payload and payload.get("name"):
        _language_name_cache[language_code] = payload["name"]
        return payload["name"]

    return language_code


def _shelf_search_terms(book_titles, limit=12):
    words = Counter()

    for title in book_titles:
        for word in _normalize(title).split():
            if len(word) >= 4:
                words[word] += 1

    return [word for word, _count in words.most_common(limit)]


def _matched_works(book_titles):
    works = []

    for title in book_titles:
        works.extend(_search_works_for_title(title))

    return works


def _detect_language(book_titles, works):
    language_scores = Counter()

    for work in works:
        for language in work.get("language", []):
            language_scores[language] += 1

    shelf_terms = _shelf_search_terms(book_titles)
    if shelf_terms:
        for term in shelf_terms:
            for work in _search_open_library(
                {
                    "q": term,
                    "limit": 20,
                    "fields": "title,language",
                }
            ):
                for language in work.get("language", []):
                    language_scores[language] += 2

        for work in _search_open_library(
            {
                "q": " ".join(shelf_terms),
                "limit": 40,
                "fields": "title,language",
            }
        ):
            for language in work.get("language", []):
                language_scores[language] += 2

    if language_scores:
        return language_scores.most_common(1)[0][0]

    return None


def _is_useful_subject(subject):
    normalized_subject = _normalize(subject)
    return bool(normalized_subject)


def _learn_subjects_from_works(works, language):
    subject_scores = Counter()

    for work in works:
        if language and language not in work.get("language", []):
            continue

        for subject in work.get("subject", [])[:12]:
            if _is_useful_subject(subject):
                subject_scores[subject] += 1

    return [subject for subject, _count in subject_scores.most_common()]


def _learn_subjects_from_search(book_titles, language):
    subject_scores = Counter()
    shelf_words = set()

    for title in book_titles:
        shelf_words.update(_normalize(title).split())

    for term in _shelf_search_terms(book_titles):
        params = {
            "q": term,
            "limit": 20,
            "fields": "title,language,subject",
        }
        if language:
            params["language"] = language

        for work in _search_open_library(params):
            if language and language not in work.get("language", []):
                continue

            for subject in work.get("subject", [])[:12]:
                if _is_useful_subject(subject):
                    score = 2
                    normalized_subject = _normalize(subject)
                    subject_words = set(normalized_subject.split())
                    if subject_words and subject_words <= shelf_words:
                        score += 20
                    if term in normalized_subject.split():
                        score += 3
                    subject_scores[subject] += score

    return [subject for subject, _count in subject_scores.most_common()]


def _merge_subjects(*subject_lists):
    merged = []
    seen = set()

    for subjects in subject_lists:
        for subject in subjects:
            key = _normalize(subject)
            if key and key not in seen:
                merged.append(subject)
                seen.add(key)

    return merged


def _subject_slug(subject):
    return quote(_normalize(subject).replace(" ", "_"))


def _recommend_from_subject(subject, language, owned_titles, limit):
    payload = _read_json(
        f"{OPEN_LIBRARY_SUBJECT_URL}/{_subject_slug(subject)}.json?limit=50"
    )
    if not payload:
        return []

    language_name = _language_name(language)
    recommendations = []

    for work in payload.get("works", []):
        title = _display_title(work.get("title", ""))

        if not title or _normalize(title) in owned_titles:
            continue

        docs = _search_open_library(
            {
                "title": title,
                "limit": 5,
                "fields": "title,language",
            }
        )
        if language and not any(language in doc.get("language", []) for doc in docs):
            continue

        recommendations.append(
            {
                "title": title,
                "reason": (
                    f"Recommended in {language_name} because your detected shelf "
                    f"language is {language_name}, and it shares the book type "
                    f"'{subject}'."
                ),
                "language": language,
                "subject": subject,
            }
        )

        if len(recommendations) >= limit:
            break

    return recommendations


def _recommend_from_shelf_terms(book_titles, language, owned_titles, limit):
    shelf_terms = _shelf_search_terms(book_titles)
    if not shelf_terms:
        return []

    language_name = _language_name(language)
    recommendations = []

    queries = list(shelf_terms)
    queries.append(" ".join(shelf_terms[:5]))

    for query in queries:
        params = {
            "q": query,
            "limit": 50,
            "fields": "title,language",
        }
        if language:
            params["language"] = language

        for doc in _search_open_library(params):
            title = _display_title(doc.get("title", ""))
            languages = doc.get("language", [])

            if not title or _normalize(title) in owned_titles:
                continue
            if language and language not in languages:
                continue

            recommendations.append(
                {
                    "title": title,
                    "reason": (
                        f"Recommended in {language_name} because your detected "
                        f"shelf language is {language_name}, and it matches "
                        f"'{query}' from your shelf."
                    ),
                    "language": language,
                    "subject": None,
                }
            )

            if len(recommendations) >= limit:
                return recommendations

    return recommendations


def recommend_books(book_titles, limit=3):
    owned_titles = {_normalize(title) for title in book_titles}
    works = _matched_works(book_titles)
    language = _detect_language(book_titles, works)
    subjects = _merge_subjects(
        _learn_subjects_from_search(book_titles, language),
        _learn_subjects_from_works(works, language),
    )

    recommendations = []
    recommendation_keys = set()

    for subject in subjects:
        for recommendation in _recommend_from_subject(
            subject, language, owned_titles, limit
        ):
            key = _normalize(recommendation["title"])
            if key in recommendation_keys:
                continue

            recommendations.append(recommendation)
            recommendation_keys.add(key)

            if len(recommendations) >= limit:
                return recommendations

    for recommendation in _recommend_from_shelf_terms(
        book_titles, language, owned_titles, limit
    ):
        key = _normalize(recommendation["title"])
        if key in recommendation_keys:
            continue

        recommendations.append(recommendation)
        recommendation_keys.add(key)

        if len(recommendations) >= limit:
            return recommendations

    return recommendations
