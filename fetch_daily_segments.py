#!/usr/bin/env python3
"""
fetch_daily_segments.py — List and download every "dirty" episode segment
for a given date from the TITV "Records" Drive folder.

Skips macOS AppleDouble junk files (e.g. "._PGM_Dirty...mp4"), sorts
segments by their trailing segment number, and downloads them in order.
Uses only the Python standard library — no extra dependencies needed on
a GitHub Actions runner.

Usage:
    python3 fetch_daily_segments.py \
        --date 2026-07-02 \
        --records-folder-id 1eQ7K0c4sEqcZBCHBvKmcIpdCcXi28n9l \
        --api-key "$GOOGLE_DRIVE_API_KEY" \
        --out-dir segments

Writes downloaded files to <out-dir>/segment_00.mp4, segment_01.mp4, ...
and a manifest at <out-dir>/segments.txt listing their paths in order,
one per line, for the next pipeline step to consume.
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.googleapis.com/drive/v3/files"


def api_get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"Drive API request failed ({e.code}): {body}")


def find_date_folder(records_id, date, api_key):
    q = (
        f"'{records_id}' in parents and "
        f"mimeType='application/vnd.google-apps.folder' and name='{date}'"
    )
    data = api_get({"q": q, "key": api_key})
    files = data.get("files", [])
    if not files:
        raise SystemExit(
            f"No folder named '{date}' found inside the Records folder. "
            f"Check the date and that it's spelled like the Drive folder name."
        )
    return files[0]["id"]


def list_dirty_files(date_folder_id, api_key):
    q = (
        f"'{date_folder_id}' in parents and "
        f"mimeType='video/mp4' and name contains 'PGM_Dirty'"
    )
    data = api_get({"q": q, "key": api_key, "pageSize": 100})
    files = data.get("files", [])

    # Drop macOS AppleDouble resource-fork junk files, which show up
    # alongside real footage as tiny 4KB files named "._PGM_Dirty...".
    before = len(files)
    files = [f for f in files if not f["name"].startswith("._")]
    dropped = before - len(files)
    if dropped:
        print(f"Ignored {dropped} macOS junk file(s) (._PGM_Dirty...).")

    if not files:
        raise SystemExit("No real PGM_Dirty files found in that date folder.")

    def segment_num(f):
        m = re.search(r"(\d+)\.mp4$", f["name"])
        return int(m.group(1)) if m else 0

    files.sort(key=segment_num)
    return files


def download_file(file_id, api_key, out_path):
    url = API + f"/{file_id}?" + urllib.parse.urlencode({"alt": "media", "key": api_key})
    urllib.request.urlretrieve(url, out_path)


def main():
    ap = argparse.ArgumentParser(description="Fetch a day's dirty segments from Drive.")
    ap.add_argument("--date", required=True, help="Date folder name, e.g. 2026-07-02")
    ap.add_argument("--records-folder-id", required=True, help="Drive ID of the Records folder")
    ap.add_argument("--api-key", required=True, help="Google Drive API key")
    ap.add_argument("--out-dir", default="segments", help="Where to save downloaded segments")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Looking up date folder '{args.date}'...")
    date_folder_id = find_date_folder(args.records_folder_id, args.date, args.api_key)

    print("Listing dirty segments...")
    files = list_dirty_files(date_folder_id, args.api_key)

    print(f"Found {len(files)} dirty segment(s) for {args.date}:")
    paths = []
    for i, f in enumerate(files):
        out_path = out_dir / f"segment_{i:02d}.mp4"
        print(f"  [{i}] {f['name']} -> {out_path}")
        download_file(f["id"], args.api_key, out_path)
        paths.append(str(out_path))

    manifest = out_dir / "segments.txt"
    manifest.write_text("\n".join(paths) + "\n")
    print(f"\nWrote manifest: {manifest}")


if __name__ == "__main__":
    main()
