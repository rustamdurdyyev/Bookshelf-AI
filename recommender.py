import json
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
from urllib.parse import quote, urlencode
from urllib.request import urlopen


OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
OPEN_LIBRARY_LANGUAGE_URL = "https://openlibrary.org/languages"
OPEN_LIBRARY_SUBJECT_URL = "https://openlibrary.org/subjects"
API_TIMEOUT = 8
MATCHED_TITLE_LIMIT = 5
SHELF_TERM_LIMIT = 4
SUBJECT_LOOKUP_LIMIT = 4
TITLE_CONNECTOR_WORDS = {
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
TITLE_VARIANT_STOP_WORDS = TITLE_CONNECTOR_WORDS | {
    "at",
    "by",
    "for",
    "from",
    "in",
    "on",
    "to",
    "with",
}
GENERIC_SUBJECTS = {
    "adult",
    "fiction",
    "general",
    "history",
    "literature",
}
LOW_VALUE_SUBJECT_PHRASES = {
    "bestseller",
    "new york times",
    "nyt",
    "reading level",
}
SUBJECT_KEYWORD_WEIGHTS = {
    "scala": 14,
    "programming": 12,
    "fantasy": 12,
    "mystery": 10,
    "detective": 10,
    "computer": 8,
    "software": 8,
    "epic": 6,
    "historical": 6,
    "magic": 5,
    "adventure": 4,
}
SUBJECT_CATEGORY_KEYWORDS = {
    "fantasy": {"epic", "fantasy", "magic"},
    "mystery": {"detective", "mystery"},
    "programming": {"computer", "programming", "scala", "software"},
}
KNOWN_LANGUAGE_NAMES = {
    "eng": "English",
    "en": "English",
    "fre": "French",
    "fr": "French",
    "ger": "German",
    "de": "German",
    "rum": "Romanian",
    "ro": "Romanian",
    "rus": "Russian",
    "ru": "Russian",
    "tur": "Turkish",
    "tr": "Turkish",
}

_language_name_cache = {}


def _normalize(text):
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _display_title(text):
    return unicodedata.normalize("NFC", str(text)).strip()


def _title_content_words(text):
    return [
        word
        for word in _normalize(text).split()
        if word not in TITLE_VARIANT_STOP_WORDS
    ]


def _same_title_variant(left, right):
    left_key = _normalize(left)
    right_key = _normalize(right)

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


def _matches_any_title(title, titles):
    return any(_same_title_variant(title, existing_title) for existing_title in titles)


def _title_quality(title):
    words = _normalize(title).split()
    content_words = _title_content_words(title)
    score = len(words) + (len(content_words) * 2)

    if any(word in TITLE_CONNECTOR_WORDS for word in words):
        score += 1
    if len(content_words) <= 1:
        score -= 3

    return score


def _dedupe_titles(titles):
    unique_titles = []

    for title in titles:
        clean_title = _display_title(title)
        if not clean_title:
            continue

        matching_index = next(
            (
                index
                for index, existing_title in enumerate(unique_titles)
                if _same_title_variant(clean_title, existing_title)
            ),
            None,
        )

        if matching_index is None:
            unique_titles.append(clean_title)
            continue

        if _title_quality(clean_title) > _title_quality(unique_titles[matching_index]):
            unique_titles[matching_index] = clean_title

    return unique_titles


@lru_cache(maxsize=512)
def _read_json(url, timeout=API_TIMEOUT):
    try:
        with urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except OSError:
        return None


def _search_open_library(params, timeout=API_TIMEOUT):
    payload = _read_json(f"{OPEN_LIBRARY_SEARCH_URL}?{urlencode(params)}", timeout)
    if not payload:
        return []

    return payload.get("docs", [])


def _search_works_for_title(title, limit=5):
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
    if language_code in KNOWN_LANGUAGE_NAMES:
        return KNOWN_LANGUAGE_NAMES[language_code]
    if language_code in _language_name_cache:
        return _language_name_cache[language_code]

    payload = _read_json(f"{OPEN_LIBRARY_LANGUAGE_URL}/{language_code}.json")
    if payload and payload.get("name"):
        _language_name_cache[language_code] = payload["name"]
        return payload["name"]

    return language_code


def _shelf_search_terms(book_titles, limit=SHELF_TERM_LIMIT):
    words = Counter()

    for title in book_titles:
        for word in _normalize(title).split():
            if len(word) >= 4:
                words[word] += 1

    return [word for word, _count in words.most_common(limit)]


def _title_seed_score(title):
    words = _normalize(title).split()
    if not words:
        return 0

    content_words = _title_content_words(title)
    if len(content_words) < 2:
        return 0

    score = min(len(words), 5)

    if any(word in TITLE_CONNECTOR_WORDS for word in words):
        score += 3
    if any(char.isdigit() for char in str(title)):
        score += 2
    if len(words) == 1:
        score -= 3
    if len(words) == 2 and words[0] in TITLE_CONNECTOR_WORDS:
        score -= 4

    parts = str(title).split()
    if len(words) == 2 and all(part[:1].isupper() for part in parts):
        score -= 1

    return score


def _seed_titles(book_titles, limit=3):
    seen = set()
    scored_titles = []

    for index, title in enumerate(_dedupe_titles(book_titles)):
        key = _normalize(title)
        if not key or key in seen:
            continue

        seen.add(key)
        score = _title_seed_score(title)
        if score > 0:
            scored_titles.append((score, index, title))

    scored_titles.sort(key=lambda item: (-item[0], item[1]))
    return [title for _score, _index, title in scored_titles[:limit]]


def _matched_works(book_titles):
    works = []

    for title in book_titles[:MATCHED_TITLE_LIMIT]:
        works.extend(_search_works_for_title(title))

    return works


def _detect_language(book_titles, works):
    language_scores = Counter()

    for work in works:
        for language in work.get("language", []):
            language_scores[language] += 1

    if not language_scores:
        shelf_terms = _shelf_search_terms(book_titles)
        if not shelf_terms:
            return None

        for work in _search_open_library(
            {
                "q": " ".join(shelf_terms),
                "limit": 20,
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
    if not normalized_subject:
        return False
    if normalized_subject in GENERIC_SUBJECTS:
        return False
    if any(phrase in normalized_subject for phrase in LOW_VALUE_SUBJECT_PHRASES):
        return False

    return True


def _subject_relevance_score(subject, shelf_words=None):
    normalized_subject = _normalize(subject)
    if not _is_useful_subject(subject):
        return 0

    subject_words = set(normalized_subject.split())
    shelf_words = shelf_words or set()
    score = 1

    for keyword, weight in SUBJECT_KEYWORD_WEIGHTS.items():
        if keyword in subject_words:
            score += weight

    overlap = subject_words & shelf_words
    if overlap:
        score += min(len(overlap) * 2, 6)

    if "fiction" in subject_words and len(subject_words) > 1:
        score += 1

    return score


def _subject_category(subject):
    subject_words = set(_normalize(subject).split())

    for category, keywords in SUBJECT_CATEGORY_KEYWORDS.items():
        if subject_words & keywords:
            return category

    return None


def _category_scores_from_query_results(query_results, language):
    category_scores = Counter()

    for _query, docs in query_results:
        query_categories = set()

        for doc in docs[:5]:
            languages = doc.get("language", [])
            if language and languages and language not in languages:
                continue

            for subject in doc.get("subject", [])[:30]:
                category = _subject_category(subject)
                if category:
                    query_categories.add(category)

        for category in query_categories:
            category_scores[category] += 1

    return category_scores


def _rerank_subjects(subjects, category_scores, shelf_words):
    indexed_subjects = list(enumerate(subjects))

    indexed_subjects.sort(
        key=lambda item: -(
            category_scores.get(_subject_category(item[1]), 0) * 100
            + _subject_relevance_score(item[1], shelf_words)
            - (item[0] * 0.01)
        )
    )

    return [subject for _index, subject in indexed_subjects]


def _learn_subjects_from_works(works, language, shelf_words=None):
    subject_scores = Counter()
    shelf_words = shelf_words or set()

    for work in works:
        if language and language not in work.get("language", []):
            continue

        for subject in work.get("subject", [])[:30]:
            score = _subject_relevance_score(subject, shelf_words)
            if score:
                subject_scores[subject] += score

    return [subject for subject, _count in subject_scores.most_common()]


def _learn_subjects_from_search(book_titles, language):
    subject_scores = Counter()
    shelf_words = set()

    for title in book_titles:
        shelf_words.update(_normalize(title).split())

    for term in _shelf_search_terms(book_titles):
        params = {
            "q": term,
            "limit": 10,
            "fields": "title,language,subject",
        }
        if language:
            params["language"] = language

        for work in _search_open_library(params):
            if language and language not in work.get("language", []):
                continue

            for subject in work.get("subject", [])[:30]:
                score = _subject_relevance_score(subject, shelf_words)
                if score:
                    normalized_subject = _normalize(subject)
                    subject_words = set(normalized_subject.split())
                    if subject_words and subject_words <= shelf_words:
                        score += 20
                    if term in normalized_subject.split():
                        score += 3
                    subject_scores[subject] += score

    return [subject for subject, _count in subject_scores.most_common()]


def _broaden_subject(subject):
    words = subject.split()
    if len(words) >= 3:
        return " ".join(words[-2:])
    if len(words) == 2:
        return words[-1]
    return None


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


def _recommendation_subject(subject):
    normalized_subject = _normalize(subject)
    subject_words = set(normalized_subject.split())

    if "fantasy" in subject_words and "epic" in subject_words:
        return "epic fantasy"
    if "epic" in subject_words:
        return "epic fantasy"
    if "fantasy" in subject_words:
        return "fantasy"
    if "mystery" in subject_words or "detective" in subject_words:
        return "mystery"
    if (
        "programming" in subject_words
        or "scala" in subject_words
        or "computer" in subject_words
        or "software" in subject_words
    ):
        return "programming"
    if "historical" in subject_words:
        return "historical fiction"
    if "adventure" in subject_words:
        return "adventure"

    return subject


def _subject_search_query(subject):
    lookup_subject = _recommendation_subject(subject)
    normalized_subject = _normalize(subject)

    if lookup_subject == "epic fantasy":
        return "fantasy epic"
    if lookup_subject == "mystery":
        return "fiction mystery detective"
    if lookup_subject == "programming" and "scala" in normalized_subject.split():
        return "programming scala"

    return lookup_subject


def _subject_slug(subject):
    return quote(_normalize(subject).replace(" ", "_"))


def _recommend_from_subject(subject, language, owned_titles, owned_title_variants, limit):
    lookup_subject = _recommendation_subject(subject)
    subject_limit = max(limit * 12, 30)
    shelf_label = f"{_language_name(language)} shelf" if language else "detected shelf"
    reason_subject = lookup_subject if lookup_subject != subject else subject
    recommendations = []

    def add_recommendation(title, subject_label):
        if (
            not title
            or _normalize(title) in owned_titles
            or _matches_any_title(title, owned_title_variants)
            or _matches_any_title(
                title,
                [recommendation["title"] for recommendation in recommendations],
            )
        ):
            return False

        recommendations.append(
            {
                "title": title,
                "reason": (
                    f"Recommended because it shares the book type '{subject_label}' "
                    f"with your {shelf_label}."
                ),
                "language": language,
                "subject": subject_label,
            }
        )

        return len(recommendations) >= limit

    payload = _read_json(
        f"{OPEN_LIBRARY_SUBJECT_URL}/{_subject_slug(lookup_subject)}.json?limit={subject_limit}"
    )

    for work in payload.get("works", []) if payload else []:
        title = _display_title(work.get("title", ""))
        if add_recommendation(title, reason_subject):
            return recommendations

    if len(recommendations) >= limit:
        return recommendations

    search_query = _subject_search_query(subject)
    docs = _search_open_library(
        {
            "q": search_query,
            "limit": subject_limit,
            "fields": "title,language,subject",
        }
    )

    for doc in docs:
        languages = doc.get("language", [])
        if language and languages and language not in languages:
            continue

        title = _display_title(doc.get("title", ""))
        doc_subjects = [
            doc_subject
            for doc_subject in doc.get("subject", [])
            if _is_useful_subject(doc_subject)
        ]
        subject_label = _recommendation_subject(doc_subjects[0]) if doc_subjects else reason_subject
        if add_recommendation(title, subject_label):
            break

    return recommendations


def _recommend_from_shelf_terms(
    book_titles,
    language,
    owned_titles,
    owned_title_variants,
    limit,
):
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
            "limit": 10,
            "fields": "title,language",
        }
        if language:
            params["language"] = language

        for doc in _search_open_library(params):
            title = _display_title(doc.get("title", ""))
            languages = doc.get("language", [])

            if (
                not title
                or _normalize(title) in owned_titles
                or _matches_any_title(title, owned_title_variants)
            ):
                continue
            if language and language not in languages:
                continue

            if language:
                reason = (
                    f"Recommended in {language_name} because your detected "
                    f"shelf language is {language_name}, and it matches "
                    f"'{query}' from your shelf."
                )
            else:
                reason = f"Recommended because it matches '{query}' from your shelf."

            recommendations.append(
                {
                    "title": title,
                    "reason": reason,
                    "language": language,
                    "subject": None,
                }
            )

            if len(recommendations) >= limit:
                return recommendations

    return recommendations


def _detect_language_from_docs(docs):
    language_scores = Counter()

    for doc in docs:
        for language in doc.get("language", []):
            language_scores[language] += 1

    if language_scores:
        return language_scores.most_common(1)[0][0]

    return None


def _recommend_from_docs(docs, query, owned_titles, owned_title_variants, limit):
    recommendations = []

    for doc in docs:
        title = _display_title(doc.get("title", ""))
        key = _normalize(title)

        if not title or key in owned_titles or _matches_any_title(title, owned_title_variants):
            continue

        subjects = [
            subject for subject in doc.get("subject", []) if _is_useful_subject(subject)
        ]
        if subjects:
            reason = (
                f"Recommended because it matched '{query}' and Open Library "
                f"tags it as '{subjects[0]}'."
            )
        else:
            reason = f"Recommended because it matched '{query}' from your shelf."

        recommendations.append(
            {
                "title": title,
                "reason": reason,
                "language": None,
                "subject": subjects[0] if subjects else None,
            }
        )

        if len(recommendations) >= limit:
            break

    return recommendations


def recommend_books(book_titles, limit=3):
    book_titles = _dedupe_titles(book_titles)
    owned_title_variants = list(book_titles)
    owned_titles = {_normalize(title) for title in book_titles}
    recommendations = []
    recommendation_keys = set()

    def _collect(recs):
        for rec in recs:
            key = _normalize(rec["title"])
            if not key:
                continue
            if key in owned_titles or _matches_any_title(rec["title"], owned_title_variants):
                continue
            if _matches_any_title(
                rec["title"],
                [recommendation["title"] for recommendation in recommendations],
            ):
                continue
            if key not in recommendation_keys:
                recommendations.append(rec)
                recommendation_keys.add(key)
            if len(recommendations) >= limit:
                return True
        return False

    seed_titles = _seed_titles(book_titles, limit=6)
    query_results = []
    works = []

    for query in seed_titles:
        docs = _search_open_library(
            {
                "q": query,
                "limit": 10,
                "fields": "title,language,subject",
            }
        )
        if docs:
            query_results.append((query, docs))
            works.extend(docs)

    language = _detect_language_from_docs(works)
    shelf_words = {
        word
        for title in seed_titles or book_titles
        for word in _normalize(title).split()
    }
    subjects = _learn_subjects_from_works(works, language, shelf_words)
    subjects = _rerank_subjects(
        subjects,
        _category_scores_from_query_results(query_results, language),
        shelf_words,
    )

    # Level 1: subject recommendations learned from the strongest shelf seeds
    for subject in subjects[:SUBJECT_LOOKUP_LIMIT]:
        if _collect(
            _recommend_from_subject(
                subject,
                language,
                owned_titles,
                owned_title_variants,
                limit,
            )
        ):
            return recommendations

    # Level 2: broader subjects
    seen_broad = set()
    for subject in subjects[:SUBJECT_LOOKUP_LIMIT]:
        broad = _broaden_subject(subject)
        if broad and broad not in seen_broad:
            seen_broad.add(broad)
            if _collect(
                _recommend_from_subject(
                    broad,
                    language,
                    owned_titles,
                    owned_title_variants,
                    limit,
                )
            ):
                return recommendations

    # Level 3: direct Open Library search results from the strongest shelf seeds
    for query, docs in query_results:
        if _collect(
            _recommend_from_docs(
                docs,
                query,
                owned_titles,
                owned_title_variants,
                limit,
            )
        ):
            return recommendations

    # Level 4: broad keyword search, no filters
    shelf_terms = _shelf_search_terms(seed_titles or book_titles)
    query = " ".join(shelf_terms)
    if query:
        docs = _search_open_library(
            {
                "q": query,
                "limit": 10,
                "fields": "title,language,subject",
            }
        )
        _collect(
            _recommend_from_docs(
                docs,
                query,
                owned_titles,
                owned_title_variants,
                limit,
            )
        )

    return recommendations
