# AGENTS.md

## Project

This repository contains a small Plex playlist recovery/export utility.

Goal: convert Plex playlist API data into `.m3u` playlist files by querying Plex playlist item endpoints and extracting local media paths from `<Part file="...">` XML attributes.

## Expected Files

```text
plex_playlists_to_m3u.py
playlists.xml
README.md
AGENTS.md
```

Generated output:

```text
plex_m3u_exports/
```

Do not commit generated `.m3u` files unless explicitly requested.

## Runtime

Primary user environment is Windows Command Prompt.

Use Windows CMD examples by default:

```cmd
set PLEX_BASE_URL=https://YOUR-PLEX-SERVER:32400
set PLEX_TOKEN=YOUR_REAL_PLEX_TOKEN
set PLAYLIST_XML=playlists.xml
set OUTPUT_DIR=plex_m3u_exports

python plex_playlists_to_m3u.py
```

Do not assume Linux syntax unless the user says they are in Linux, WSL, macOS, Git Bash, or PowerShell.

## Commands

Install dependency:

```cmd
python -m pip install requests
```

Run exporter:

```cmd
python plex_playlists_to_m3u.py
```

List output:

```cmd
dir plex_m3u_exports
```

Open an exported playlist:

```cmd
notepad "plex_m3u_exports\Adam's Classics.m3u"
```

## Code Style

- Keep the script plain Python.
- Avoid large frameworks.
- Prefer readable procedural code.
- Add small helper functions when useful.
- Keep path handling cross-platform with `pathlib`.
- Preserve Unicode playlist names where possible.
- Sanitize filenames for Windows-invalid characters.

## Safety Rules

- Never hard-code Plex tokens.
- Never print full Plex tokens unless the user explicitly asks.
- Never commit tokens, secrets, or server-specific private URLs.
- Avoid destructive file operations.
- If overwriting output files, keep behavior explicit and predictable.
- Do not delete playlist files unless the user explicitly requests it.

## Troubleshooting Style

Use decision trees.

Start with read-only verification commands:

```cmd
dir
python --version
python -m pip show requests
```

Then provide the safest fix.

Common Windows CMD corrections:

```text
export -> set
python3 -> python
single quotes are not needed
```

## Plex API Notes

Playlist index endpoint:

```text
/playlists
```

Playlist items endpoint:

```text
/playlists/<ratingKey>/items
```

The playlist index XML contains playlist metadata but not necessarily track file paths.

Actual paths usually come from item XML:

```xml
<Part file="..." />
```

If `/playlists/<ratingKey>/items` does not contain `file=`, then the script cannot produce path-based M3U entries from the API response alone. Next recovery path is the Plex SQLite database or an older database backup.

## Documentation Rules

Keep `README.md` human-facing.

Keep `AGENTS.md` short and operational for coding agents.

Do not duplicate large explanations between files unless it directly improves usability.
