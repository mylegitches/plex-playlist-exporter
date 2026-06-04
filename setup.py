#!/usr/bin/env python3
"""
Interactive setup: finds your Plex token and server URL, then optionally
exports the playlists.xml so the exporter can scrape playlists + collections.
"""

import os
import sys
import json
import pathlib
import getpass
import subprocess
import xml.etree.ElementTree as ET

try:
    import requests
except ImportError:
    print("requests is not installed. Run:  pip install requests")
    sys.exit(1)

ENV_FILE = pathlib.Path(".env")
PLEX_SIGNIN_URL = "https://plex.tv/api/v2/users/signin"
PLEX_RESOURCES_URL = "https://plex.tv/api/v2/resources"
PLEX_HEADERS = {
    "X-Plex-Client-Identifier": "plex-playlist-exporter-setup",
    "X-Plex-Product": "plex-playlist-exporter",
    "Accept": "application/json",
}


def step(n: int, msg: str):
    print(f"\n[{n}] {msg}")
    print("-" * 60)


def get_token_via_login() -> str:
    print("\nSign in with your Plex account to get your token.")
    print("(credentials are sent directly to plex.tv and never stored)")
    username = input("Plex username or email: ").strip()
    password = getpass.getpass("Plex password: ")

    r = requests.post(
        PLEX_SIGNIN_URL,
        headers=PLEX_HEADERS,
        json={"login": username, "password": password},
        timeout=30,
    )
    if r.status_code == 201:
        return r.json()["authToken"]
    if r.status_code == 401:
        print("ERROR: Bad credentials.")
    else:
        print(f"ERROR: {r.status_code} {r.text[:200]}")
    return ""


def find_servers(token: str) -> list:
    r = requests.get(
        PLEX_RESOURCES_URL,
        headers={**PLEX_HEADERS, "X-Plex-Token": token},
        timeout=30,
    )
    r.raise_for_status()
    servers = []
    for resource in r.json():
        if resource.get("provides", "").startswith("server"):
            for conn in resource.get("connections", []):
                servers.append({
                    "name": resource["name"],
                    "address": conn["address"],
                    "uri": conn["uri"],
                    "local": conn.get("local", False),
                })
    return servers


def pick_server(servers: list) -> dict:
    local = [s for s in servers if s["local"]]
    remote = [s for s in servers if not s["local"]]
    ranked = local + remote

    print(f"\nFound {len(ranked)} server connection(s):")
    for i, s in enumerate(ranked):
        tag = "local" if s["local"] else "remote"
        print(f"  [{i}] {s['name']}  {s['uri']}  ({tag})")

    if len(ranked) == 1:
        print(f"Using: {ranked[0]['uri']}")
        return ranked[0]

    while True:
        choice = input(f"\nPick a server [0-{len(ranked)-1}]: ").strip()
        if choice.isdigit() and 0 <= int(choice) < len(ranked):
            return ranked[int(choice)]


def test_connection(base_url: str, token: str) -> bool:
    try:
        r = requests.get(
            f"{base_url}/library/sections",
            params={"X-Plex-Token": token},
            timeout=10,
            verify=False,
        )
        return r.ok
    except Exception:
        return False


def export_playlists_xml(base_url: str, token: str, out_path: pathlib.Path):
    r = requests.get(
        f"{base_url}/playlists",
        params={"X-Plex-Token": token},
        timeout=60,
        verify=False,
    )
    r.raise_for_status()
    out_path.write_bytes(r.content)
    root = ET.fromstring(r.content)
    count = len(root.findall(".//Playlist"))
    print(f"  Saved {count} playlist entries to {out_path}")


def write_env(base_url: str, token: str, xml_path: str):
    lines = [
        f'PLEX_BASE_URL="{base_url}"',
        f'PLEX_TOKEN="{token}"',
        f'PLEX_PLAYLIST_XML="{xml_path}"',
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    print(f"\n  Saved to {ENV_FILE}")
    print("  To load:  PowerShell: Get-Content .env | ForEach-Object { Invoke-Expression $_ }")
    print("            Bash:       export $(cat .env | xargs)")


def main():
    print("=" * 60)
    print(" Plex Playlist Exporter — Setup")
    print("=" * 60)

    # --- Step 1: Token ---
    step(1, "Get your Plex token")
    print("Option A: Sign in here (recommended)")
    print("Option B: Paste an existing token")
    choice = input("\nChoice [A/B]: ").strip().upper() or "A"

    token = ""
    if choice == "B":
        token = input("Paste your Plex token: ").strip()
    else:
        token = get_token_via_login()

    if not token:
        print("Could not obtain token. Exiting.")
        sys.exit(1)

    print(f"\n  Token: {token[:8]}{'*' * (len(token) - 8)}")

    # --- Step 2: Server URL ---
    step(2, "Find your Plex server")
    base_url = ""

    try:
        servers = find_servers(token)
        if servers:
            server = pick_server(servers)
            base_url = server["uri"].rstrip("/")
        else:
            print("No servers found via plex.tv. Enter URL manually.")
    except Exception as e:
        print(f"Could not reach plex.tv: {e}")

    if not base_url:
        base_url = input("Enter your Plex server URL (e.g. http://192.168.1.x:32400): ").strip().rstrip("/")

    print(f"\n  Testing connection to {base_url} ...", end="", flush=True)
    if test_connection(base_url, token):
        print(" OK")
    else:
        print(" FAILED (continuing anyway — check URL/token if exports fail)")

    # --- Step 3: Export playlists.xml ---
    step(3, "Export playlists.xml")
    print("The exporter reads playlist names from a local XML file.")
    xml_path = pathlib.Path(os.environ.get("PLAYLIST_XML", "playlists.xml"))
    do_export = input(f"Export now to {xml_path}? [Y/n]: ").strip().lower() or "y"
    if do_export == "y":
        try:
            export_playlists_xml(base_url, token, xml_path)
        except Exception as e:
            print(f"  ERROR: {e}")

    # --- Step 4: Save .env ---
    step(4, "Save environment variables")
    do_save = input(f"Save PLEX_BASE_URL, PLEX_TOKEN, PLEX_PLAYLIST_XML to {ENV_FILE}? [Y/n]: ").strip().lower() or "y"
    if do_save == "y":
        write_env(base_url, token, str(xml_path))

    # --- Done ---
    print("\n" + "=" * 60)
    print(" Setup complete! To run the exporter:")
    print()
    print("   PowerShell:")
    print("     Get-Content .env | ForEach-Object { Invoke-Expression $_ }")
    print("     python plex_playlists_to_m3u.py")
    print()
    print("   Bash:")
    print("     export $(cat .env | xargs)")
    print("     python plex_playlists_to_m3u.py")
    print()
    print("   Flags:  --playlists   export playlists only")
    print("           --artists     export artist collections only")
    print("           --albums      export album collections only")
    print("           (no flags)    export everything")
    print("=" * 60)


if __name__ == "__main__":
    main()
