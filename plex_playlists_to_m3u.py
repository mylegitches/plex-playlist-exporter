#!/usr/bin/env python3

import os
import re
import sys
import time
import html
import pathlib
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

PLEX_BASE_URL = os.environ.get("PLEX_BASE_URL", "").rstrip("/")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "")
PLAYLIST_XML = os.environ.get("PLAYLIST_XML", "playlists.xml")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "plex_m3u_exports")

if not PLEX_BASE_URL:
    print("ERROR: Set PLEX_BASE_URL first")
    sys.exit(1)

if not PLEX_TOKEN:
    print("ERROR: Set PLEX_TOKEN first")
    sys.exit(1)

def safe_filename(name: str) -> str:
    name = html.unescape(name)
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] or "playlist"

def plex_get(path: str) -> ET.Element:
    url = f"{PLEX_BASE_URL}{path}"
    params = {"X-Plex-Token": PLEX_TOKEN}
    r = requests.get(url, params=params, timeout=60, verify=False)
    r.raise_for_status()
    return ET.fromstring(r.content)

def extract_track_paths(root: ET.Element):
    paths = []

    # Plex track items usually contain Media -> Part file="..."
    for part in root.findall(".//Part"):
        file_path = part.attrib.get("file")
        if file_path:
            paths.append(file_path)

    return paths

def main():
    pathlib.Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    tree = ET.parse(PLAYLIST_XML)
    root = tree.getroot()

    playlists = []
    for p in root.findall(".//Playlist"):
        playlist_type = p.attrib.get("playlistType", "")
        title = p.attrib.get("title", "Untitled")
        key = p.attrib.get("key", "")
        leaf_count = int(p.attrib.get("leafCount", "0"))

        # Change this if you also want video playlists.
        if playlist_type != "audio":
            continue

        if not key:
            continue

        playlists.append((title, key, leaf_count))

    print(f"Found {len(playlists)} audio playlists")

    for title, key, leaf_count in playlists:
        filename = safe_filename(title) + ".m3u"
        out_path = pathlib.Path(OUTPUT_DIR) / filename

        print(f"Exporting: {title} ({leaf_count} items)")

        try:
            items_root = plex_get(key)
            track_paths = extract_track_paths(items_root)

            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                f.write("#EXTM3U\n")
                f.write(f"# PLAYLIST: {title}\n")
                f.write(f"# SOURCE: Plex {key}\n")

                for path in track_paths:
                    f.write(path + "\n")

            print(f"  wrote {len(track_paths)} tracks -> {out_path}")

            # Be polite to Plex.
            time.sleep(0.2)

        except Exception as e:
            print(f"  ERROR exporting {title}: {e}")

if __name__ == "__main__":
    main()