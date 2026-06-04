#!/usr/bin/env python3

import os
import re
import sys
import time
import html
import pathlib
import argparse
import requests
import xml.etree.ElementTree as ET

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
    return name[:180] or "unknown"


def plex_get(path: str, **params) -> ET.Element:
    url = f"{PLEX_BASE_URL}{path}"
    all_params = {"X-Plex-Token": PLEX_TOKEN, **params}
    r = requests.get(url, params=all_params, timeout=60, verify=False)
    r.raise_for_status()
    return ET.fromstring(r.content)


def plex_get_paged(path: str, **params) -> list:
    """Fetch all items across Plex pagination; returns a flat list of child elements."""
    start = 0
    page_size = 500
    collected = []
    while True:
        root = plex_get(
            path,
            **{"X-Plex-Container-Start": start, "X-Plex-Container-Size": page_size, **params},
        )
        items = list(root)
        collected.extend(items)
        total = int(root.attrib.get("totalSize", root.attrib.get("size", "0")) or 0)
        start += len(items)
        if not items or start >= total:
            break
    return collected


def extract_paths(items) -> list:
    """Extract file paths from a list of Track elements (or an Element tree root)."""
    if isinstance(items, ET.Element):
        items = list(items)
    paths = []
    for item in items:
        for part in item.findall(".//Part"):
            fp = part.attrib.get("file")
            if fp:
                paths.append(fp)
    return paths


def write_m3u(out_path: pathlib.Path, title: str, source_key: str, tracks: list):
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("#EXTM3U\n")
        f.write(f"# PLAYLIST: {title}\n")
        f.write(f"# SOURCE: Plex {source_key}\n")
        for path in tracks:
            f.write(path + "\n")


def get_music_sections() -> list:
    root = plex_get("/library/sections")
    return [
        (d.attrib["key"], d.attrib.get("title", "Music"))
        for d in root.findall(".//Directory")
        if d.attrib.get("type") == "artist"
    ]


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------

def export_playlists(out_dir: pathlib.Path):
    if not pathlib.Path(PLAYLIST_XML).exists():
        print(f"Skipping playlists: {PLAYLIST_XML} not found")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(PLAYLIST_XML)
    root = tree.getroot()

    playlists = [
        (p.attrib.get("title", "Untitled"), p.attrib["key"], int(p.attrib.get("leafCount", "0")))
        for p in root.findall(".//Playlist")
        if p.attrib.get("playlistType") == "audio" and p.attrib.get("key")
    ]

    print(f"\nFound {len(playlists)} audio playlists")
    for title, key, leaf_count in playlists:
        out_path = out_dir / (safe_filename(title) + ".m3u")
        print(f"  {title} ({leaf_count} tracks)", end="", flush=True)
        try:
            tracks = extract_paths(plex_get_paged(key))
            write_m3u(out_path, title, key, tracks)
            print(f" -> {len(tracks)} written")
            time.sleep(0.2)
        except Exception as e:
            print(f" ERROR: {e}")


def export_artists(out_dir: pathlib.Path):
    sections = get_music_sections()
    if not sections:
        print("No music library sections found")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    for section_id, section_title in sections:
        artists = plex_get_paged(f"/library/sections/{section_id}/all", type=8)
        print(f"\n{section_title}: {len(artists)} artists")

        for artist in artists:
            name = artist.attrib.get("title", "Unknown Artist")
            key = artist.attrib.get("ratingKey", "")
            if not key:
                continue
            out_path = out_dir / (safe_filename(name) + ".m3u")
            print(f"  {name}", end="", flush=True)
            try:
                leaves_path = f"/library/metadata/{key}/allLeaves"
                tracks = extract_paths(plex_get_paged(leaves_path))
                write_m3u(out_path, name, leaves_path, tracks)
                print(f" -> {len(tracks)} tracks")
                time.sleep(0.1)
            except Exception as e:
                print(f" ERROR: {e}")


def export_albums(out_dir: pathlib.Path):
    sections = get_music_sections()
    if not sections:
        print("No music library sections found")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    for section_id, section_title in sections:
        albums = plex_get_paged(f"/library/sections/{section_id}/all", type=9)
        print(f"\n{section_title}: {len(albums)} albums")

        for album in albums:
            album_title = album.attrib.get("title", "Unknown Album")
            artist_name = album.attrib.get("parentTitle", "Unknown Artist")
            key = album.attrib.get("ratingKey", "")
            if not key:
                continue
            filename = safe_filename(f"{artist_name} - {album_title}") + ".m3u"
            out_path = out_dir / filename
            print(f"  {artist_name} - {album_title}", end="", flush=True)
            try:
                children_path = f"/library/metadata/{key}/children"
                tracks = extract_paths(plex_get_paged(children_path))
                write_m3u(out_path, f"{artist_name} - {album_title}", children_path, tracks)
                print(f" -> {len(tracks)} tracks")
                time.sleep(0.05)
            except Exception as e:
                print(f" ERROR: {e}")


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Export Plex music library to M3U files")
    parser.add_argument("--playlists", action="store_true", help="Export playlists only")
    parser.add_argument("--artists", action="store_true", help="Export artist collections only")
    parser.add_argument("--albums", action="store_true", help="Export album collections only")
    args = parser.parse_args()

    run_all = not (args.playlists or args.artists or args.albums)
    base = pathlib.Path(OUTPUT_DIR)

    if run_all or args.playlists:
        export_playlists(base)

    if run_all or args.artists:
        export_artists(base / "artists")

    if run_all or args.albums:
        export_albums(base / "albums")


if __name__ == "__main__":
    main()
