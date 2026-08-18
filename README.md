# Flipbook Studio

Upload a PDF or images, get a private, permanent, shareable flipbook link (like Heyzine),
backed by your own Google Drive so nothing gets lost.

- `yourapp.streamlit.app/` → your private dashboard (password protected) — upload files, see all your flipbooks and their links
- `yourapp.streamlit.app/?id=<id>` → the client-facing viewer — no login needed, only works if someone has the exact link

---

## 1. Create a Google Service Account (one-time setup)

A service account lets the app talk to Google Drive on your behalf, without you logging in every time.

1. Go to https://console.cloud.google.com/ and create a new project (or use an existing one).
2. In the search bar, go to **APIs & Services → Library**, search for **Google Drive API**, and click **Enable**.
3. Go to **APIs & Services → Credentials → Create Credentials → Service Account**.
   - Give it any name, e.g. `flipbook-bot`.
   - Skip granting it project roles (not needed).
   - Click **Done**.
4. Click on the service account you just created → **Keys** tab → **Add Key → Create new key → JSON**.
   - This downloads a `.json` file. **Keep it safe — treat it like a password.**

## 2. Create and share a Google Drive folder

1. In your own Google Drive, create a new folder, e.g. **"Flipbooks"**.
2. Open the folder, copy its ID from the URL:
   `https://drive.google.com/drive/folders/`**`THIS_PART_IS_THE_FOLDER_ID`**
3. Click **Share** on that folder, and share it with the service account's email address
   (it looks like `flipbook-bot@your-project.iam.gserviceaccount.com` — find it inside the JSON
   file under `"client_email"`). Give it **Editor** access.

## 3. Deploy to Streamlit Community Cloud (free)

1. Push this folder (`app.py`, `requirements.txt`) to a **private** GitHub repo.
2. Go to https://share.streamlit.io/ → **New app** → connect your repo → set main file to `app.py`.
3. Before/after deploying, open **App settings → Secrets** and paste in:

   ```toml
   OWNER_PASSWORD = "choose-a-password-only-you-know"
   ROOT_FOLDER_ID = "the-drive-folder-id-from-step-2"
   APP_BASE_URL = "https://your-app-name.streamlit.app"   # fill in after first deploy

   [gcp_service_account]
   type = "service_account"
   project_id = "..."
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   client_email = "flipbook-bot@your-project.iam.gserviceaccount.com"
   client_id = "..."
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "..."
   ```

   Copy every field straight out of the JSON file you downloaded in step 1 — just re-wrap it
   in this `[gcp_service_account]` TOML table. Keep the `\n` characters inside `private_key` as-is.

4. Save. The app will restart. Visit your app URL — you'll land on the **Owner Login** screen.

## 4. Using it

- Log in with your `OWNER_PASSWORD` → you'll see the dashboard.
- Upload a PDF (or a set of images in order) with a title → click **Create Flipbook**.
- Copy the generated link and send it to your client. That's it — they open it and can flip
  through pages, no login required.
- Every flipbook you've made is listed on your dashboard with its link, so you can always find
  it again.

## View tracking

Every time someone opens a flipbook link, the app logs the date and time (UTC) to
`views.json` inside that flipbook's Drive folder. On your dashboard, each flipbook shows
its total **Opens** count, and you can expand **View history** to see the full list of
open timestamps. A single browser session only counts as one open (flipping pages or
refreshing doesn't inflate the count).

## Notes

- Files live permanently in your own Google Drive folder — delete a flipbook by deleting its
  subfolder in Drive.
- Links are private by obscurity: Drive folder IDs are long random strings, not guessable, and
  are never listed publicly — only your password-protected dashboard shows them.
- If you want, this can later be extended with per-flipbook expiry dates, view counts, or a
  branded cover page.
