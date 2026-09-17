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
MODEL_CHOICES = {
    "Balanced reader": DEFAULT_GROQ_MODEL,
}


st.set_page_config(
    page_title="Bookshelf AI",
    page_icon="bookshelf",
    layout="wide",
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
    .stApp {
        background: #ffffff;
    }
    .block-container {
        padding-top: 1.1rem;
        padding-bottom: 2rem;
        max-width: 1180px;
    }
    h1, h2, h3 {
        letter-spacing: 0;
    }
    h1 {
        color: #111827;
        font-family: Georgia, "Times New Roman", serif;
        font-size: 3rem;
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
    }
    .bookshelf-muted {
        color: #4b5563;
        font-size: 1rem;
        max-width: 680px;
    }
    .book-topline {
        color: #6b7280;
        font-size: 0.78rem;
        letter-spacing: 0.08rem;
        margin-bottom: 0.1rem;
        text-transform: uppercase;
    }
    .book-spread {
        margin-top: 1.2rem;
        padding: 0;
        border-radius: 0;
        background: #ffffff;
        box-shadow: none;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: #e5e7eb;
        border-radius: 8px;
        background: #ffffff;
        box-shadow: none;
    }
    div.stButton > button {
        width: 100%;
        border-radius: 6px;
        min-height: 2.8rem;
    }
    div.stButton > button[kind="primary"] {
        background: #111827;
        border-color: #111827;
        color: white;
    }
    div[data-testid="stTabs"] button {
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
            padding-left: 0.85rem;
            padding-right: 0.85rem;
            padding-top: 0.75rem;
        }
        h1 {
            font-size: 2.25rem;
        }
        .bookshelf-muted {
            font-size: 0.95rem;
        }
        .book-spread {
            margin-left: -0.25rem;
            margin-right: -0.25rem;
            padding: 0.55rem;
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

    st.markdown('<div class="book-topline">Personal shelf discovery</div>', unsafe_allow_html=True)
    st.title("Bookshelf AI")
    st.markdown(
        '<p class="bookshelf-muted">Add bookshelf photos and get recommendations inspired by the books already on your shelf.</p>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="book-spread">', unsafe_allow_html=True)
    left_page, right_page = st.columns([0.92, 1.28], gap="large")

    with left_page:
        with st.container(border=True):
            st.subheader("Reading Setup")
            model_label = st.selectbox("Model", list(MODEL_CHOICES), index=0)
            model = MODEL_CHOICES[model_label]
            max_images = MODEL_IMAGE_LIMITS.get(model, DEFAULT_MAX_IMAGES_PER_REQUEST)
            language_choice = st.selectbox(
                "Language",
                ["auto", "English", "Romanian", "Turkish", "Russian", "German", "French", "Spanish"],
                index=0,
            )
            recommendation_limit = st.slider("Recommendations", 1, 10, 5)
            st.caption(f"Up to {max_images} photos in one reading.")

        with st.container(border=True):
            st.subheader("Add Photos")
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
    selected_items = image_items[:max_images]

    with right_page:
        with st.container(border=True):
            st.subheader("Shelf Photos")
            if len(image_items) > max_images:
                st.warning(
                    f"{len(image_items)} photos were added, but this model can analyze only "
                    f"{max_images}. The first {max_images} photos will be used."
                )
            _display_preview(selected_items)

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

    st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
