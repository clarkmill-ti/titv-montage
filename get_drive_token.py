#!/usr/bin/env python3
"""
get_drive_token.py — ONE-TIME local helper. Run this on your own laptop,
NOT in GitHub Actions. It opens a browser for you to approve Drive
access as yourself, then prints values to paste into GitHub secrets.

Why this exists: Drive service accounts have zero storage quota of
their own, so they can't create new files even in folders they've been
given Editor access to. Authorizing as your own account instead means
uploads count against your normal Drive storage, which already works
fine for everything else you do by hand.

Requires: pip install google-auth-oauthlib

Usage:
    python3 get_drive_token.py --client-id YOUR_ID --client-secret YOUR_SECRET
    (or set GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET env vars)

This will open your browser once. Approve access, then come back here —
the three values printed at the end go into GitHub repo secrets.
"""

import argparse
import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"))
    ap.add_argument("--client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"))
    args = ap.parse_args()

    if not args.client_id or not args.client_secret:
        raise SystemExit(
            "Provide --client-id and --client-secret from your Desktop app "
            "OAuth client (Google Cloud Console → Credentials)."
        )

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\nSuccess! Add these three as GitHub repo secrets:\n")
    print(f"GOOGLE_OAUTH_CLIENT_ID={args.client_id}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={args.client_secret}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
    print("\n(The refresh token doesn't expire under normal use — you "
          "shouldn't need to run this again unless you revoke access.)")


if __name__ == "__main__":
    main()
