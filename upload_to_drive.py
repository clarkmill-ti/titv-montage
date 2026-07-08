#!/usr/bin/env python3
"""
upload_to_drive.py — Upload the finished montage into a per-date subfolder
of an existing Drive folder (e.g. "TITV/Shows"), creating that day's
subfolder if it doesn't already exist — mirroring the same "07-06-26"
style folder-per-episode structure already used for thumbnails.

Authenticates as YOUR Google account via OAuth (not a service account —
service accounts have no Drive storage quota of their own and can't
create new files even with Editor access to a folder). Run
get_drive_token.py once locally to generate the refresh token this
script needs.

Requires: pip install google-api-python-client google-auth

Usage:
    python3 upload_to_drive.py \
        --file montage.mp4 \
        --parent-folder-id <Shows_folder_id> \
        --date-folder-name "07-06-26" \
        --name "thumbnail-montage.mp4"

Reads GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, and
GOOGLE_OAUTH_REFRESH_TOKEN from the environment (set from GitHub Actions
secrets — never pass credentials on the command line).
"""

import argparse
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_service():
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN")
    missing = [
        name for name, val in [
            ("GOOGLE_OAUTH_CLIENT_ID", client_id),
            ("GOOGLE_OAUTH_CLIENT_SECRET", client_secret),
            ("GOOGLE_OAUTH_REFRESH_TOKEN", refresh_token),
        ] if not val
    ]
    if missing:
        raise SystemExit(f"Missing env var(s): {', '.join(missing)}")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds)


def find_or_create_folder(service, parent_id, name):
    """Find a subfolder by name under parent_id, creating it if it
    doesn't exist yet — mirrors how the Shows folder is organized by
    hand today (one dated subfolder per episode)."""
    q = (
        f"'{parent_id}' in parents and name = '{name}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    res = service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    print(f"Created new folder '{name}' (id={folder['id']}).")
    return folder["id"]


def find_existing(service, folder_id, name):
    q = f"'{folder_id}' in parents and name = '{name}' and trashed = false"
    res = service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--parent-folder-id", required=True, help="Drive ID of the Shows folder")
    ap.add_argument("--date-folder-name", required=True, help="e.g. 07-06-26, matching existing convention")
    ap.add_argument("--name", default="thumbnail-montage.mp4", help="Filename to give the upload")
    args = ap.parse_args()

    service = get_service()
    date_folder_id = find_or_create_folder(service, args.parent_folder_id, args.date_folder_name)

    media = MediaFileUpload(args.file, mimetype="video/mp4", resumable=True)
    existing_id = find_existing(service, date_folder_id, args.name)

    if existing_id:
        print(f"Found existing '{args.name}' in {args.date_folder_name}; updating it in place.")
        file = service.files().update(fileId=existing_id, media_body=media).execute()
    else:
        print(f"Uploading '{args.name}' into {args.date_folder_name}.")
        metadata = {"name": args.name, "parents": [date_folder_id]}
        file = service.files().create(body=metadata, media_body=media, fields="id").execute()

    file_id = file.get("id")
    print(f"Uploaded '{args.name}'. File ID: {file_id}")
    print(f"View at: https://drive.google.com/file/d/{file_id}/view")


if __name__ == "__main__":
    main()
