"""
Private Flipbook Studio
------------------------
Upload a PDF or images -> get a realistic page-flip viewer with a unique,
private, shareable link. All files are stored in a Google Drive folder
(via a service account) so flipbooks persist permanently, not just in
this app's local/ephemeral storage.

URL modes:
  https://yourapp.streamlit.app/                -> owner dashboard (password protected)
  https://yourapp.streamlit.app/?id=<folder_id>  -> client-facing flipbook viewer (no login)
"""

import io
import json
import uuid
import base64
import datetime as dt

import streamlit as st
import pymupdf  # PyMuPDF

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2 import service_account

st.set_page_config(page_title="Flipbook Studio", layout="wide")

# --------------------------------------------------------------------------
# Google Drive helpers
# --------------------------------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/drive"]


@st.cache_resource(show_spinner=False)
def get_drive_service():
    info = dict(st.secrets["gcp_service_account"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def root_folder_id() -> str:
    return st.secrets["ROOT_FOLDER_ID"]


def create_flipbook_folder(service, title: str) -> str:
    metadata = {
        "name": f"{title} [{uuid.uuid4().hex[:8]}]",
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [root_folder_id()],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_bytes(service, folder_id: str, filename: str, data: bytes, mimetype: str) -> str:
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype, resumable=False)
    metadata = {"name": filename, "parents": [folder_id]}
    f = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return f["id"]


def list_children(service, folder_id: str):
    items = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    while True:
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType, createdTime)",
            pageToken=page_token,
            pageSize=1000,
        ).execute()
        items.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def download_bytes(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def update_bytes(service, file_id: str, data: bytes, mimetype: str):
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype, resumable=False)
    service.files().update(fileId=file_id, media_body=media).execute()


def find_child(children, name):
    return next((c for c in children if c["name"] == name), None)


def log_view(service, folder_id: str, children):
    """Append a UTC timestamp to views.json in the flipbook folder (create if missing)."""
    views_file = find_child(children, "views.json")
    now = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    try:
        if views_file:
            existing = json.loads(download_bytes(service, views_file["id"]).decode("utf-8"))
            existing.append(now)
            update_bytes(service, views_file["id"], json.dumps(existing).encode("utf-8"), "application/json")
        else:
            upload_bytes(service, folder_id, "views.json", json.dumps([now]).encode("utf-8"), "application/json")
    except Exception:
        # Never let view logging break the viewer itself
        pass


def get_views(service, children):
    views_file = find_child(children, "views.json")
    if not views_file:
        return []
    try:
        return json.loads(download_bytes(service, views_file["id"]).decode("utf-8"))
    except Exception:
        return []


def list_flipbook_folders(service):
    return sorted(
        [f for f in list_children(service, root_folder_id())
         if f["mimeType"] == "application/vnd.google-apps.folder"],
        key=lambda f: f.get("createdTime", ""),
        reverse=True,
    )


# --------------------------------------------------------------------------
# PDF / image processing
# --------------------------------------------------------------------------

def pdf_to_page_images(pdf_bytes: bytes, dpi: int = 150):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        pages.append(pix.tobytes("png"))
    doc.close()
    return pages


# --------------------------------------------------------------------------
# Flipbook viewer (HTML/JS using page-flip.js from CDN)
# --------------------------------------------------------------------------

FLIPBOOK_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  html,body {{ margin:0; padding:0; background:#2b2b2b; overflow:hidden; height:100%; }}
  #book-wrap {{ display:flex; justify-content:center; align-items:center; height:100vh; }}
  #book {{ box-shadow: 0 10px 40px rgba(0,0,0,0.5); }}
  .page {{ background:#fff; }}
  .page img {{ width:100%; height:100%; object-fit:contain; display:block; }}
  #controls {{ position:fixed; bottom:16px; left:0; right:0; text-align:center; }}
  #controls button {{
    background:#444; color:#fff; border:none; padding:10px 18px; margin:0 6px;
    border-radius:6px; cursor:pointer; font-size:14px;
  }}
  #controls button:hover {{ background:#666; }}
  #pagenum {{ color:#ccc; font-family:sans-serif; margin:0 10px; }}
</style>
</head>
<body>
<div id="book-wrap"><div id="book"></div></div>
<div id="controls">
  <button onclick="pageFlip.flipPrev()">&#8592; Prev</button>
  <span id="pagenum"></span>
  <button onclick="pageFlip.flipNext()">Next &#8594;</button>
</div>

<script src="https://cdn.jsdelivr.net/npm/page-flip@2.0.7/dist/js/page-flip.browser.js"></script>
<script>
const pages = {pages_json};

const bookEl = document.getElementById('book');
const pageFlip = new St.PageFlip(bookEl, {{
  width: {page_w},
  height: {page_h},
  size: "stretch",
  minWidth: 300,
  maxWidth: 1400,
  minHeight: 400,
  maxHeight: 1800,
  showCover: true,
  maxShadowOpacity: 0.5,
  mobileScrollSupport: true
}});

const pageDivs = pages.map(src => {{
  const d = document.createElement('div');
  d.className = 'page';
  const img = document.createElement('img');
  img.src = src;
  d.appendChild(img);
  return d;
}});

pageFlip.loadFromHTML ? null : null;
pageFlip.updateFromImages ? null : null;
pageFlip.loadFromImages(pages);

function updateNum() {{
  document.getElementById('pagenum').innerText =
    (pageFlip.getCurrentPageIndex()+1) + ' / ' + pages.length;
}}
pageFlip.on('flip', updateNum);
updateNum();
</script>
</body>
</html>
"""


def render_flipbook(page_data_urls, page_w=700, page_h=980):
    html = FLIPBOOK_HTML.format(
        pages_json=json.dumps(page_data_urls),
        page_w=page_w,
        page_h=page_h,
    )
    st.components.v1.html(html, height=800, scrolling=False)


# --------------------------------------------------------------------------
# App logic
# --------------------------------------------------------------------------

def owner_login():
    st.subheader("Owner Login")
    pw = st.text_input("Password", type="password")
    if st.button("Log in"):
        if pw == st.secrets.get("OWNER_PASSWORD", ""):
            st.session_state["is_owner"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")


def viewer_page(flipbook_id: str):
    service = get_drive_service()
    try:
        children = list_children(service, flipbook_id)
    except Exception:
        st.error("This flipbook link is invalid or no longer available.")
        return

    meta_file = find_child(children, "metadata.json")
    image_files = sorted(
        [c for c in children if c["name"].startswith("page_")],
        key=lambda c: c["name"],
    )

    if not image_files:
        st.error("This flipbook has no pages, or the link is invalid.")
        return

    title = flipbook_id
    if meta_file:
        try:
            meta = json.loads(download_bytes(service, meta_file["id"]).decode("utf-8"))
            title = meta.get("title", title)
        except Exception:
            pass

    # Log this open (once per browser session, so refreshing/flipping pages
    # doesn't inflate the count)
    if not st.session_state.get(f"logged_{flipbook_id}"):
        log_view(service, flipbook_id, children)
        st.session_state[f"logged_{flipbook_id}"] = True

    st.markdown(f"<h3 style='text-align:center'>{title}</h3>", unsafe_allow_html=True)

    data_urls = []
    progress = st.progress(0.0, text="Loading pages...")
    for i, f in enumerate(image_files):
        raw = download_bytes(service, f["id"])
        b64 = base64.b64encode(raw).decode("ascii")
        data_urls.append(f"data:image/png;base64,{b64}")
        progress.progress((i + 1) / len(image_files), text=f"Loading page {i+1}/{len(image_files)}")
    progress.empty()

    render_flipbook(data_urls)


def owner_dashboard():
    service = get_drive_service()

    st.title("📖 Flipbook Studio — Dashboard")
    st.caption("Upload a PDF or images, get a private shareable flipbook link.")

    with st.form("upload_form", clear_on_submit=True):
        title = st.text_input("Flipbook title", placeholder="e.g. Summer 2026 Catalog")
        upload_type = st.radio("Upload type", ["PDF", "Images"], horizontal=True)
        files = None
        if upload_type == "PDF":
            files = st.file_uploader("Upload PDF", type=["pdf"])
        else:
            files = st.file_uploader(
                "Upload images (in order)", type=["png", "jpg", "jpeg"],
                accept_multiple_files=True,
            )
        submitted = st.form_submit_button("Create Flipbook")

    if submitted:
        if not title.strip():
            st.error("Please enter a title.")
        elif not files:
            st.error("Please upload a file.")
        else:
            with st.spinner("Creating flipbook and uploading to Google Drive..."):
                folder_id = create_flipbook_folder(service, title.strip())

                if upload_type == "PDF":
                    page_images = pdf_to_page_images(files.read())
                else:
                    page_images = [f.read() for f in files]

                for i, img_bytes in enumerate(page_images):
                    fname = f"page_{i:04d}.png"
                    upload_bytes(service, folder_id, fname, img_bytes, "image/png")

                meta = {
                    "title": title.strip(),
                    "created": dt.datetime.utcnow().isoformat(),
                    "pages": len(page_images),
                }
                upload_bytes(
                    service, folder_id, "metadata.json",
                    json.dumps(meta).encode("utf-8"), "application/json",
                )

            st.success(f"Flipbook created with {len(page_images)} pages!")
            base_url = st.secrets.get("APP_BASE_URL", "").rstrip("/")
            link = f"{base_url}/?id={folder_id}" if base_url else f"?id={folder_id}"
            st.code(link, language=None)

    st.divider()
    st.subheader("Your Flipbooks")

    folders = list_flipbook_folders(service)
    base_url = st.secrets.get("APP_BASE_URL", "").rstrip("/")

    if not folders:
        st.info("No flipbooks yet — create one above.")
    for f in folders:
        link = f"{base_url}/?id={f['id']}" if base_url else f"?id={f['id']}"
        children = list_children(service, f["id"])
        views = get_views(service, children)

        cols = st.columns([4, 3, 1, 1])
        cols[0].markdown(f"**{f['name']}**")
        cols[1].code(link, language=None)
        cols[2].metric("Opens", len(views))
        if cols[3].button("Open", key=f"open_{f['id']}"):
            st.query_params["id"] = f["id"]
            st.rerun()

        if views:
            with st.expander(f"View history ({len(views)} opens)"):
                for ts in reversed(views):
                    try:
                        local = dt.datetime.fromisoformat(ts.replace("Z", "")).strftime("%d %b %Y, %I:%M %p UTC")
                    except Exception:
                        local = ts
                    st.text(local)
        st.divider()


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------

def main():
    params = st.query_params
    if "id" in params:
        viewer_page(params["id"])
        return

    if not st.session_state.get("is_owner"):
        owner_login()
        return

    owner_dashboard()


if __name__ == "__main__":
    main()
