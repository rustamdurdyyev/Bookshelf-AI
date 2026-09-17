from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st

from groq_bookshelf import (
    DEFAULT_GROQ_MODEL,
    DEFAULT_MAX_IMAGES_PER_REQUEST,
    MODEL_IMAGE_LIMITS,
    GroqBookshelfError,
    analyze_bookshelf_images,
)


SUPPORTED_IMAGE_TYPES = ("jpg", "jpeg", "png", "webp")
MAX_PHOTOS_IN_UI = 6
RECOMMENDATION_SAFE_LIMIT = 3
RECOMMENDATION_MAX_LIMIT = 6
MODEL_CHOICES = {
    "Qwen 3.8 27B": "qwen/qwen3.8-27b",
    "Qwen 3.6 27B": "qwen/qwen3.6-27b",
}


st.set_page_config(
    page_title="Bookshelf AI",
    page_icon="bookshelf",
    layout="centered",
)


st.markdown(
    """
    <style>
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    #MainMenu {
        display: none;
    }
    html,
    body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {
        color-scheme: light;
    }
    .stApp {
        background:
            radial-gradient(circle at 18% 0%, rgba(59, 130, 246, 0.14), transparent 19rem),
            radial-gradient(circle at 90% 12%, rgba(20, 184, 166, 0.12), transparent 18rem),
            linear-gradient(180deg, #f8fafc 0%, #eef4ff 100%);
    }
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2.25rem;
        max-width: 760px;
    }
    h1, h2, h3 {
        letter-spacing: 0;
    }
    h1 {
        color: #111827;
        font-size: 2.6rem;
        margin-bottom: 0.25rem;
    }
    h2, h3 {
        color: #111827;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.35rem;
    }
    div[data-testid="stFileUploader"] section {
        min-height: 7rem;
        background: #ffffff;
        border-color: #dce5f2;
        color: #111827;
    }
    .app-hero {
        margin-bottom: 1rem;
        padding: 1.35rem 1.2rem;
        border-radius: 22px;
        color: #111827;
        background:
            radial-gradient(circle at 92% 0%, rgba(37, 99, 235, 0.16), transparent 12rem),
            linear-gradient(135deg, #ffffff 0%, #f3f8ff 58%, #eefdfa 100%);
        border: 1px solid #dce5f2;
        box-shadow: 0 16px 34px rgba(15, 23, 42, 0.08);
    }
    .app-hero-kicker {
        color: #2563eb;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.1rem;
        margin-bottom: 0.35rem;
        text-transform: uppercase;
    }
    .app-hero-title {
        font-size: 2.15rem;
        font-weight: 800;
        line-height: 1.05;
        margin-bottom: 0.55rem;
    }
    .app-hero-copy {
        color: #334155;
        font-size: 0.98rem;
        line-height: 1.45;
        max-width: 33rem;
    }
    .section-note {
        color: #64748b;
        font-size: 0.9rem;
        margin-top: -0.35rem;
        margin-bottom: 0.6rem;
    }
    .limit-meter {
        margin: 0.2rem 0 0.9rem;
    }
    .limit-meter-top {
        align-items: center;
        color: #334155;
        display: flex;
        font-size: 0.86rem;
        font-weight: 650;
        justify-content: space-between;
        margin-bottom: 0.35rem;
    }
    .limit-meter-track {
        background: #e5e7eb;
        border-radius: 999px;
        height: 0.58rem;
        overflow: hidden;
        position: relative;
    }
    .limit-meter-safe,
    .limit-meter-over {
        height: 100%;
        left: 0;
        position: absolute;
        top: 0;
    }
    .limit-meter-safe {
        background: linear-gradient(90deg, #2563eb, #38bdf8);
    }
    .limit-meter-over {
        background: linear-gradient(90deg, #ef4444, #b91c1c);
    }
    .limit-meter-labels {
        color: #64748b;
        display: flex;
        font-size: 0.75rem;
        justify-content: space-between;
        margin-top: 0.25rem;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: #dce5f2;
        border-radius: 18px;
        background: #ffffff;
        box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
    }
    div[data-testid="stExpander"] {
        border: 1px solid #dce5f2;
        border-radius: 18px;
        background: #ffffff;
        box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
        overflow: hidden;
    }
    div[data-testid="stExpander"] details summary {
        font-weight: 750;
        color: #111827;
    }
    div.stButton > button {
        width: 100%;
        border-radius: 12px;
        min-height: 3rem;
        font-weight: 700;
    }
    div.stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #2563eb, #14b8a6);
        border-color: transparent;
        color: white;
    }
    div[data-testid="stTabs"] button {
        color: #111827;
    }
    div[data-baseweb="tab-list"] {
        gap: 0.35rem;
    }
    div[data-baseweb="tab"] {
        border-radius: 999px;
        padding-left: 0.9rem;
        padding-right: 0.9rem;
    }
    div[data-testid="stSlider"] div[data-baseweb="slider"] > div:first-child {
        background: linear-gradient(90deg, #2563eb 0%, #38bdf8 50%, #ef4444 50%, #b91c1c 100%) !important;
    }
    div[data-baseweb="select"] > div,
    input,
    textarea {
        background-color: #ffffff;
        color: #111827;
    }
    .result-title {
        color: #111827;
        font-size: 1.04rem;
        font-weight: 650;
        margin-bottom: 0.15rem;
    }
    .result-meta {
        color: #6b7280;
        font-size: 0.88rem;
        margin-bottom: 0.45rem;
    }
    @media (max-width: 640px) {
        .block-container {
            padding-left: 0.75rem;
            padding-right: 0.75rem;
            padding-top: 0.65rem;
        }
        .app-hero {
            border-radius: 18px;
            padding: 1.15rem 1rem;
            margin-bottom: 0.8rem;
        }
        .app-hero-title {
            font-size: 1.85rem;
        }
        .app-hero-copy {
            font-size: 0.92rem;
        }
        h2, h3 {
            font-size: 1.25rem;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 16px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _init_state():
    st.session_state.setdefault("camera_photos", [])
    st.session_state.setdefault("camera_key", 0)
    st.session_state.setdefault("last_result", None)


def _streamlit_secret_api_key():
    try:
        return st.secrets.get("GROQ_API_KEY")
    except (FileNotFoundError, KeyError):
        return None


def _uploaded_image_items(uploaded_files):
    items = []
    for index, uploaded_file in enumerate(uploaded_files or [], start=1):
        items.append(
            {
                "name": uploaded_file.name or f"uploaded_{index}.jpg",
                "bytes": uploaded_file.getvalue(),
                "source": "Upload",
            }
        )
    return items


def _camera_image_items():
    items = []
    for index, photo in enumerate(st.session_state.camera_photos, start=1):
        items.append(
            {
                "name": f"camera_{index}.jpg",
                "bytes": photo,
                "source": "Camera",
            }
        )
    return items


def _write_temp_images(image_items, temp_dir):
    image_paths = []
    temp_dir = Path(temp_dir)

    for index, image_item in enumerate(image_items, start=1):
        image_path = temp_dir / f"bookshelf_{index}.jpg"
        image_path.write_bytes(image_item["bytes"])
        image_paths.append(image_path)

    return image_paths


def _display_preview(image_items):
    if not image_items:
        st.info("Add at least one bookshelf photo to start.")
        return

    for index, image_item in enumerate(image_items):
        st.image(
            image_item["bytes"],
            caption=f"{index + 1}. {image_item['source']} - {image_item['name']}",
            width="stretch",
        )


def _limit_meter_html(count, safe_limit, hard_limit, item_label):
    visible_count = min(count, hard_limit)
    safe_count = min(visible_count, safe_limit)
    over_count = max(0, visible_count - safe_limit)
    safe_width = (safe_count / hard_limit) * 100
    over_left = (safe_limit / hard_limit) * 100
    over_width = (over_count / hard_limit) * 100

    return f"""
    <div class="limit-meter">
        <div class="limit-meter-top">
            <span>{visible_count}/{hard_limit} {item_label}</span>
            <span>{safe_limit} ideal / {hard_limit} max</span>
        </div>
        <div class="limit-meter-track">
            <div class="limit-meter-safe" style="width: {safe_width:.1f}%;"></div>
            <div class="limit-meter-over" style="left: {over_left:.1f}%; width: {over_width:.1f}%;"></div>
        </div>
        <div class="limit-meter-labels">
            <span>0</span>
            <span>{safe_limit}</span>
            <span>{hard_limit}</span>
        </div>
    </div>
    """


def _result_rows(items):
    if not items:
        return []
    return items


def _display_results(result):
    detected_books = _result_rows(result.get("detected_books"))
    recommendations = _result_rows(result.get("recommendations"))

    metric_columns = st.columns(2)
    metric_columns[0].metric("Detected books", len(detected_books))
    metric_columns[1].metric("Recommendations", len(recommendations))

    st.subheader("Detected Books")
    if detected_books:
        st.dataframe(detected_books, width="stretch", hide_index=True)
    else:
        st.warning("No clear book titles were detected.")

    st.subheader("Recommendations")
    if recommendations:
        for recommendation in recommendations:
            title = recommendation.get("title", "Untitled")
            author = recommendation.get("author")
            genre = recommendation.get("genre")
            with st.container(border=True):
                st.markdown(f'<div class="result-title">{title}</div>', unsafe_allow_html=True)
                meta_parts = [part for part in (author, genre) if part]
                if meta_parts:
                    st.markdown(
                        f'<div class="result-meta">{" - ".join(meta_parts)}</div>',
                        unsafe_allow_html=True,
                    )
                st.write(recommendation.get("why", ""))
    else:
        st.warning("No recommendations were returned.")


def main():
    _init_state()

    st.markdown(
        """
        <div class="app-hero">
            <div class="app-hero-kicker">Personal shelf discovery</div>
            <div class="app-hero-title">Bookshelf AI</div>
            <div class="app-hero-copy">
                Add a few bookshelf photos and get recommendations inspired by
                the books already on your shelf.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Reading Setup", expanded=False):
        st.markdown(
            '<div class="section-note">Choose how the shelf should be read before adding photos.</div>',
            unsafe_allow_html=True,
        )
        model_names = list(MODEL_CHOICES)
        default_model_name = next(
            (
                name
                for name, model_id in MODEL_CHOICES.items()
                if model_id == DEFAULT_GROQ_MODEL
            ),
            model_names[0],
        )
        model_name = st.selectbox(
            "Model",
            model_names,
            index=model_names.index(default_model_name),
        )
        model = MODEL_CHOICES[model_name]
        max_images = MODEL_IMAGE_LIMITS.get(model, DEFAULT_MAX_IMAGES_PER_REQUEST)
        language_choice = st.selectbox(
            "Language",
            ["auto", "English", "Romanian", "Turkish", "Russian", "German", "French", "Spanish"],
            index=0,
        )
        recommendation_limit = st.slider(
            "Recommendations",
            1,
            RECOMMENDATION_MAX_LIMIT,
            RECOMMENDATION_SAFE_LIMIT,
        )

    with st.container(border=True):
        st.subheader("Add Photos From Your Shelf")
        st.markdown(
            '<div class="section-note">Upload shelf photos or take new ones, then analyze your bookshelf.</div>',
            unsafe_allow_html=True,
        )
        upload_tab, camera_tab = st.tabs(["Upload", "Camera"])

        with upload_tab:
            uploaded_files = st.file_uploader(
                "Bookshelf photos, max 5 MB each",
                type=SUPPORTED_IMAGE_TYPES,
                accept_multiple_files=True,
                help="Upload JPG, PNG, or WEBP images up to 5 MB each.",
            )

        with camera_tab:
            camera_photo = st.camera_input(
                "Take a bookshelf photo",
                key=f"camera_{st.session_state.camera_key}",
            )

            button_columns = st.columns(2)
            with button_columns[0]:
                if st.button("Add photo", disabled=camera_photo is None):
                    st.session_state.camera_photos.append(camera_photo.getvalue())
                    st.session_state.camera_key += 1
                    st.rerun()
            with button_columns[1]:
                if st.button("Clear photos", disabled=not st.session_state.camera_photos):
                    st.session_state.camera_photos = []
                    st.session_state.camera_key += 1
                    st.rerun()

        image_items = _uploaded_image_items(uploaded_files) + _camera_image_items()
        visible_items = image_items[:MAX_PHOTOS_IN_UI]
        selected_items = image_items[:max_images]

        st.markdown(
            _limit_meter_html(
                len(image_items),
                safe_limit=max_images,
                hard_limit=MAX_PHOTOS_IN_UI,
                item_label="photos",
            ),
            unsafe_allow_html=True,
        )
        if len(image_items) > MAX_PHOTOS_IN_UI:
            st.warning(
                f"{len(image_items)} photos were added. The first {MAX_PHOTOS_IN_UI} photos are shown."
            )
        _display_preview(visible_items)

        analyze_disabled = not selected_items
        if st.button("Analyze Bookshelf", type="primary", disabled=analyze_disabled):
            with st.spinner("Reading book spines and preparing suggestions..."):
                try:
                    with TemporaryDirectory(prefix="bookshelf_ai_streamlit_") as temp_dir:
                        image_paths = _write_temp_images(selected_items, temp_dir)
                        result = analyze_bookshelf_images(
                            image_paths,
                            api_key=_streamlit_secret_api_key(),
                            model=model,
                            language=language_choice,
                            recommendation_limit=recommendation_limit,
                        )
                except GroqBookshelfError:
                    st.error("Analysis failed. Please check the API key and selected model, then try again.")
                else:
                    st.session_state.last_result = result

    if st.session_state.last_result:
        with st.container(border=True):
            _display_results(st.session_state.last_result)


if __name__ == "__main__":
    main()
