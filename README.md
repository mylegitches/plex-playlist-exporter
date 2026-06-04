# Plex Playlist to M3U Exporter

This small utility exports Plex playlists to `.m3u` files.

It uses the Plex playlist API:

```text
/playlists
/playlists/<ratingKey>/items
```

The playlist index XML contains playlist names, `ratingKey` values, playlist type, and item counts. The script then queries each playlist's item endpoint and extracts local media file paths from `<Part file="...">` entries.

## Files

```text
plex_playlists_to_m3u.py   Python exporter script
playlists.xml              Saved Plex playlist index XML
plex_m3u_exports/          Generated .m3u playlist files
README.md                  Human usage instructions
AGENTS.md                  AI coding-agent instructions
```

## Requirements

- Windows, Linux, or macOS
- Python 3
- Plex Media Server reachable over HTTP or HTTPS
- A valid Plex token
- `requests` Python package

Install `requests` if needed:

```cmd
python -m pip install requests
```

## Windows Command Prompt Usage

Open Command Prompt in the folder containing:

```text
plex_playlists_to_m3u.py
playlists.xml
```

Example:

```cmd
cd C:\Users\adamr\Desktop
dir
```

You should see both files.

Then set the environment variables:

```cmd
set PLEX_BASE_URL=https://YOUR-PLEX-SERVER:32400
set PLEX_TOKEN=YOUR_REAL_PLEX_TOKEN
set PLAYLIST_XML=playlists.xml
set OUTPUT_DIR=plex_m3u_exports

python plex_playlists_to_m3u.py
```

For your Plex Direct style URL, the base URL looks like this:

```cmd
set PLEX_BASE_URL=https://192-168-1-124.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.plex.direct:32400
```

Do not include `/playlists` at the end of `PLEX_BASE_URL`.

## PowerShell Usage

```powershell
$env:PLEX_BASE_URL="https://YOUR-PLEX-SERVER:32400"
$env:PLEX_TOKEN="YOUR_REAL_PLEX_TOKEN"
$env:PLAYLIST_XML="playlists.xml"
$env:OUTPUT_DIR="plex_m3u_exports"

python .\plex_playlists_to_m3u.py
```

## Linux/macOS Usage

```bash
export PLEX_BASE_URL='https://YOUR-PLEX-SERVER:32400'
export PLEX_TOKEN='YOUR_REAL_PLEX_TOKEN'
export PLAYLIST_XML='playlists.xml'
export OUTPUT_DIR='plex_m3u_exports'

python3 plex_playlists_to_m3u.py
```

## Output

The script creates one `.m3u` file per audio playlist:

```text
plex_m3u_exports/
├── Adam's Classics.m3u
├── Anthems.m3u
├── Piano.m3u
├── Rap.m3u
└── Sleepy - Ultimate.m3u
```

Each file uses this structure:

```m3u
#EXTM3U
# PLAYLIST: Adam's Classics
# SOURCE: Plex /playlists/499482/items
/path/to/music/file1.flac
/path/to/music/file2.mp3
```

## Troubleshooting Decision Tree

### Script says `ERROR: Set PLEX_BASE_URL first`

You did not set the environment variables in the current terminal.

Windows CMD:

```cmd
set PLEX_BASE_URL=https://YOUR-PLEX-SERVER:32400
```

PowerShell:

```powershell
$env:PLEX_BASE_URL="https://YOUR-PLEX-SERVER:32400"
```

Linux/macOS:

```bash
export PLEX_BASE_URL='https://YOUR-PLEX-SERVER:32400'
```

### `python3` is not found on Windows

Use:

```cmd
python plex_playlists_to_m3u.py
```

not:

```cmd
python3 plex_playlists_to_m3u.py
```

### `export` is not recognized on Windows

You are in Windows Command Prompt. Use `set`:

```cmd
set PLEX_TOKEN=YOUR_REAL_PLEX_TOKEN
```

### XML file not found

Check the actual file name:

```cmd
dir
```

If the file is named `Pasted text(26).txt`, use:

```cmd
set PLAYLIST_XML=Pasted text(26).txt
python plex_playlists_to_m3u.py
```

### Generated M3U files are empty

Open one playlist item URL in Chrome:

```text
https://YOUR-PLEX-SERVER:32400/playlists/PLAYLIST_ID/items?X-Plex-Token=YOUR_TOKEN
```

Search the page for:

```text
file=
```

Decision tree:

```text
file= appears
├─ Yes → the script should be able to export paths
└─ No
   ├─ the playlist may currently be empty
   ├─ Plex may not be returning local paths through that endpoint
   └─ recover from the Plex SQLite database or an older DB backup
```

## Security Note

A Plex token is equivalent to an authentication secret. Do not commit it to Git, paste it into docs, or hard-code it in the script.

Recommended after recovery:

1. Sign out old Plex sessions.
2. Re-login.
3. Use a fresh token.
