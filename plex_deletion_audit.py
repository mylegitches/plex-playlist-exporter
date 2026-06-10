#!/usr/bin/env python3
"""
plex_deletion_audit.py
Scans Plex Media Server logs for every deletion, removal, trash, and
housekeeping event in the past month and writes a categorized text report.

Usage:
  # Remote Plex server via SSH (key-based auth required):
  python plex_deletion_audit.py --ssh user@192.168.1.124

  # SSH with explicit log directory on the remote host:
  python plex_deletion_audit.py --ssh user@192.168.1.124 --log-dir "/custom/path/Logs"

  # Local log directory (if logs are mounted or copied locally):
  python plex_deletion_audit.py --log-dir "D:/Plex Media Server/Logs"

  # Change lookback window (default 31 days):
  python plex_deletion_audit.py --ssh user@host --days 60

  # Change output file:
  python plex_deletion_audit.py --ssh user@host --output my_report.txt
"""

import re
import sys
import gzip
import argparse
import subprocess
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

LOOKBACK_DAYS = 31
OUTPUT_FILE = "plex_deletion_report.txt"

# Common Plex log directory paths (tried in order when --log-dir is not given)
DEFAULT_LOG_PATHS = [
    "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Logs",
    "/usr/lib/plexmediaserver/Library/Application Support/Plex Media Server/Logs",
    "/opt/plexmediaserver/Library/Application Support/Plex Media Server/Logs",
    "/volume1/Plex/Library/Application Support/Plex Media Server/Logs",   # Synology
    "/volume1/PlexMediaServer/Library/Application Support/Plex Media Server/Logs",
    "/mnt/user/appdata/plex/Library/Application Support/Plex Media Server/Logs",  # Unraid
    r"C:\Users\plex\AppData\Local\Plex Media Server\Logs",  # Windows server
    r"C:\ProgramData\Plex Media Server\Logs",
]

# Log files to scan within the log directory
LOG_FILENAME_PATTERNS = [
    "Plex Media Server.log",
    "Plex Media Server.log.*",
    "Plex Media Scanner.log",
    "Plex Media Scanner.log.*",
    "Plex Plug-in Framework.log",
    "Plex Plug-in Framework.log.*",
    "PMS Plugin Logs/*.log",
    "PMS Plugin Logs/*.log.*",
]

# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

TS_PATTERNS = [
    (re.compile(r'(\w{3}\s+\d{1,2},\s+\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+)'), "%b %d, %Y %H:%M:%S.%f"),
    (re.compile(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)'),          "%Y-%m-%d %H:%M:%S.%f"),
    (re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)'),            "%Y-%m-%dT%H:%M:%S.%f"),
    (re.compile(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'),               "%Y-%m-%d %H:%M:%S"),
    (re.compile(r'(\w{3}\s+\d{1,2},\s+\d{4}\s+\d{2}:\d{2}:\d{2})'),        "%b %d, %Y %H:%M:%S"),
]


def parse_ts(line: str):
    for rx, fmt in TS_PATTERNS:
        m = rx.search(line)
        if m:
            try:
                return datetime.strptime(m.group(1), fmt)
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------------------
# Classification: categories checked in priority order, first match wins.
# ---------------------------------------------------------------------------

CATEGORY_PATTERNS = OrderedDict([
    ("Playlist Deleted/Removed", [
        r'(?i)\bplaylist\b.{0,150}\b(delet|remov)\w*\b',
        r'(?i)\b(delet|remov)\w*\b.{0,100}\bplaylist\b',
        r'(?i)playlist.{0,80}(gone|missing|not\s+found)',
    ]),
    ("Collection Deleted/Removed", [
        r'(?i)\bcollection\b.{0,150}\b(delet|remov)\w*\b',
        r'(?i)\b(delet|remov)\w*\b.{0,100}\bcollection\b',
        r'(?i)collection.{0,80}(gone|missing|not\s+found)',
    ]),
    ("File / Track Deleted", [
        r'(?i)\bdelete\s+(file|track|media|audio)\b',
        r'(?i)\bdeleted\s+(the\s+)?(file|track|media\s+item|audio|song)\b',
        r'(?i)\b(removing|removed)\s+(local\s+)?(file|track|audio|song)\b',
        r'(?i)\b(file|track|audio|song)\b.{0,80}\b(delet|remov)\w*\b',
        r'(?i)\b(delet|remov)\w*\b.{0,80}\b(file|track|audio|song)\b',
    ]),
    ("Media Item Deleted from Library", [
        r'(?i)\bdeleted\s+(media\s+)?item\b',
        r'(?i)\b(remov|delet)\w*\b.{0,80}\b(media\s+item|library\s+item|catalog\s+item)\b',
        r'(?i)\blibrary\s+item\b.{0,80}\b(remov|delet)\w*\b',
        r'(?i)\bremoved\s+from\s+(the\s+)?(library|catalog|database|db)\b',
        r'(?i)\bitem\s+removed\b',
    ]),
    ("File / Path Not Found or Missing", [
        r'(?i)\b(file|path|item|media|track)\b.{0,100}\b(not\s+found|not\s+accessible|not\s+available|not\s+exist|missing|disappeared|no\s+longer\s+(exist|access|available|present))\b',
        r'(?i)\b(cannot|can\'t|couldn\'t|unable\s+to)\s+(find|access|open|read|locate)\b.{0,80}\b(file|media|track|item|path)\b',
        r'(?i)\bpath\s+does\s+not\s+exist\b',
        r'(?i)\bmissing\s+(from\s+)?(disk|filesystem|drive|storage|volume)\b',
        r'(?i)\bmedia\s+(is\s+)?(not\s+(found|accessible|available))\b',
        r'(?i)\bfile\s+is\s+(gone|missing|absent)\b',
        r'(?i)\bitem\s+no\s+longer\b',
        r'(?i)\binaccessible\b.{0,60}\b(file|media|path|item)\b',
        r'(?i)\b(file|media|path)\b.{0,60}\binaccessible\b',
    ]),
    ("Scanner: Removed Stale or Missing Items", [
        r'(?i)\bscanner\b.{0,150}\b(remov|delet|missing|not\s+found|unavailable|stale|gone)\w*\b',
        r'(?i)\b(remov|delet)\w*\b.{0,150}\bscanner\b',
        r'(?i)\bremoving\s+stale\b',
        r'(?i)\bstale\s+(item|entry|media|record|metadata)\b',
        r'(?i)\bclean\w*\s+(up\s+)?stale\b',
        r'(?i)\bscan.{0,30}\bdiscovering\s+(missing|deleted)\b',
        r'(?i)\bscan\w*\s+found\s+\d+\s+(missing|deleted|removed)\b',
    ]),
    ("Trash: Empty / Clear", [
        r'(?i)\b(empty|emptying|emptied|clear|cleared|flush|flushed|clean)\w*\b.{0,80}\btrash\b',
        r'(?i)\btrash\b.{0,80}\b(empty|clear|flush|delet|remov)\w*\b',
        r'(?i)\bempty\s+trash\b',
        r'(?i)\btrash\s+emptied\b',
        r'(?i)\bemptying\s+the\s+trash\b',
    ]),
    ("Trash: Items Moved to Trash", [
        r'(?i)\b(move|moved|moving|sent?|putting|adding)\b.{0,80}\b(to\s+|into\s+)?trash\b',
        r'(?i)\btrash(ed|ing)\b',
    ]),
    ("Metadata / Bundle Cleanup", [
        r'(?i)\b(clean|delet|remov)\w*\b.{0,80}\b(metadata|bundle|thumb|thumbnail|poster|artwork|cache|cover\s+art|fanart|image\s+cache)\b',
        r'(?i)\b(metadata|bundle|thumb|thumbnail|poster|artwork|cache)\b.{0,80}\b(clean|delet|remov)\w*\b',
        r'(?i)\bclean\s+(bundle|metadata)\b',
        r'(?i)\bcleaning\s+(up\s+)?(bundles?|metadata|cache|artwork|images?)\b',
        r'(?i)\b(bad|corrupt|invalid|malformed|broken)\s+(metadata|data|file|media)\b',
        r'(?i)\bmetadata\b.{0,80}\b(bad|corrupt|invalid|error|problem|issue|broken)\b',
        r'(?i)\bfixing\s+(metadata|database|corrupt)\b',
        r'(?i)\bimage\s+(not\s+valid|failed|missing|broken)\b',
        r'(?i)\bposter\s+(not\s+found|missing|failed|broken)\b',
    ]),
    ("Database Maintenance", [
        r'(?i)\b(database|db)\s+(cleanup|maintenance|vacuum|compact|prune|optimize)\b',
        r'(?i)\bvacuum\w*\b.{0,60}\b(database|db)\b',
        r'(?i)\b(database|db)\b.{0,60}\bvacuum\w*\b',
        r'(?i)\bdrop\w*\b.{0,60}\b(table|index|database)\b',
        r'(?i)\bpruning\s+(old|expired|stale)\b',
    ]),
    ("Agent / Plugin Housekeeping", [
        r'(?i)\bagent\b.{0,150}\b(remov|delet|clean|purge)\w*\b',
        r'(?i)\b(remov|delet|clean|purge)\w*\b.{0,150}\bagent\b',
        r'(?i)\bplug.?in\b.{0,80}\b(remov|delet|clean|purge)\w*\b',
        r'(?i)\bexpir\w+\b.{0,80}\b(token|session|cache|data)\b',
        r'(?i)\b(token|session|cache)\b.{0,80}\bexpir\w+\b',
    ]),
    ("Other Deletion / Purge", [
        r'(?i)\bdeleted?\b',
        r'(?i)\bpurged?\b',
    ]),
])

COMPILED_CATEGORIES = OrderedDict(
    (cat, [re.compile(p) for p in pats])
    for cat, pats in CATEGORY_PATTERNS.items()
)

# Lines to skip — these match "delete/remove" but are never real deletions
NOISE_PATTERNS = [
    re.compile(r'(?i)\bdo\s+not\s+(delet|remov)\b'),
    re.compile(r'(?i)\bdo\s+not\s+delete\b'),
    re.compile(r'(?i)\bshould\s+(not\s+)?(delet|remov)\b'),
    re.compile(r'(?i)\b(never|don\'t|please)\s+(delet|remov)\b'),
    re.compile(r'(?i)\ballow\w*\s+(delet|remov)\b'),
    re.compile(r'(?i)\bprevent\w*\s+(delet|remov)\b'),
    re.compile(r'(?i)\b(setting|option|preference|config)\b.{0,40}\b(delet|remov)\b'),
    re.compile(r'(?i)heartbeat'),
    re.compile(r'(?i)lock\s*file'),
    re.compile(r'(?i)\bping\b'),
]


def classify_line(line: str):
    """Return category string or None if the line is noise / doesn't match."""
    for noise in NOISE_PATTERNS:
        if noise.search(line):
            return None
    for cat, patterns in COMPILED_CATEGORIES.items():
        for rx in patterns:
            if rx.search(line):
                return cat
    return None


# ---------------------------------------------------------------------------
# Log reading: local and SSH
# ---------------------------------------------------------------------------

def iter_lines_local(log_path: Path):
    """Yield (filename, raw_line) from a local file, handling .gz."""
    name = log_path.name
    try:
        if name.endswith(".gz"):
            with gzip.open(log_path, "rt", encoding="utf-8", errors="replace") as f:
                for line in f:
                    yield name, line.rstrip()
        else:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    yield name, line.rstrip()
    except OSError as e:
        print(f"  [WARN] Cannot read {log_path}: {e}", file=sys.stderr)


def run_ssh(ssh_target: str, cmd: str, timeout: int = 60):
    """Run a command on the remote host, return stdout as text."""
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", ssh_target, cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode not in (0, 1):  # 1 = grep no match, which is fine
        err = result.stderr.strip()
        if err:
            raise RuntimeError(f"SSH error: {err}")
    return result.stdout


def find_log_dir_ssh(ssh_target: str):
    """Try default paths on the remote host; return the first that exists."""
    for path in DEFAULT_LOG_PATHS:
        out = run_ssh(ssh_target, f'test -d "{path}" && echo yes || echo no')
        if out.strip() == "yes":
            return path
    return None


def list_log_files_ssh(ssh_target: str, log_dir: str):
    """Return a list of log file paths on the remote host."""
    # Find main server logs, scanner logs, and plugin logs (not too deep)
    cmd = (
        f'find "{log_dir}" -maxdepth 2 '
        r'-name "Plex Media Server.log*" '
        r'-o -name "Plex Media Scanner.log*" '
        r'-o -name "Plex Plug-in Framework.log*" '
        r'-o -name "*.log" '
        r'-o -name "*.log.gz" '
        r'| sort'
    )
    out = run_ssh(ssh_target, cmd, timeout=30)
    return [p.strip() for p in out.splitlines() if p.strip()]


def iter_lines_ssh(ssh_target: str, remote_path: str):
    """Stream lines from a remote file (handles .gz via zcat)."""
    if remote_path.endswith(".gz"):
        cmd = f'zcat "{remote_path}"'
    else:
        cmd = f'cat "{remote_path}"'
    filename = remote_path.split("/")[-1]
    try:
        out = run_ssh(ssh_target, cmd, timeout=120)
        for line in out.splitlines():
            yield filename, line
    except RuntimeError as e:
        print(f"  [WARN] {remote_path}: {e}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"  [WARN] Timeout reading {remote_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------

def scan_lines(line_iter, cutoff: datetime):
    """
    Consume (filename, line) pairs, return list of dicts for matching events.
    Each dict: {ts, filename, category, line}
    """
    events = []
    for filename, line in line_iter:
        ts = parse_ts(line)
        if ts is None:
            continue
        if ts < cutoff:
            continue
        cat = classify_line(line)
        if cat:
            events.append({"ts": ts, "filename": filename, "category": cat, "line": line})
    return events


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------

SEPARATOR = "=" * 100
THIN_SEP  = "-" * 100


def write_report(events: list, output_path: str, log_dir: str, ssh_target: str,
                 cutoff: datetime, scanned_files: list):
    now = datetime.now()
    by_category = defaultdict(list)
    for e in events:
        by_category[e["category"]].append(e)

    with open(output_path, "w", encoding="utf-8") as f:
        def w(text=""):
            f.write(text + "\n")

        w(SEPARATOR)
        w("  PLEX MEDIA SERVER — DELETION / REMOVAL AUDIT REPORT")
        w(SEPARATOR)
        w(f"  Generated : {now.strftime('%Y-%m-%d %H:%M:%S')}")
        w(f"  Source    : {'SSH ' + ssh_target if ssh_target else 'Local'}")
        w(f"  Log dir   : {log_dir}")
        w(f"  Lookback  : since {cutoff.strftime('%Y-%m-%d')}  ({(now - cutoff).days} days)")
        w(f"  Log files : {len(scanned_files)}")
        w(f"  Events    : {len(events)}")
        w()
        w(SEPARATOR)
        w("  SUMMARY BY CATEGORY")
        w(SEPARATOR)
        for cat in CATEGORY_PATTERNS:
            count = len(by_category.get(cat, []))
            if count:
                w(f"  {count:>5}  {cat}")
        total_other = sum(len(v) for k, v in by_category.items() if k not in CATEGORY_PATTERNS)
        if total_other:
            w(f"  {total_other:>5}  (uncategorized)")
        w()
        w(SEPARATOR)
        w("  FILES SCANNED")
        w(SEPARATOR)
        for fp in sorted(scanned_files):
            w(f"  {fp}")
        w()

        # Events grouped by category, newest first within each
        for cat in CATEGORY_PATTERNS:
            ev_list = by_category.get(cat, [])
            if not ev_list:
                continue
            ev_list.sort(key=lambda e: e["ts"], reverse=True)
            w(SEPARATOR)
            w(f"  {cat.upper()}  ({len(ev_list)} events)")
            w(SEPARATOR)
            for e in ev_list:
                w(f"  [{e['ts'].strftime('%Y-%m-%d %H:%M:%S')}]  [{e['filename']}]")
                w(f"  {e['line'].strip()}")
                w()

        # Anything that landed in "Other" not in the ordered list
        for cat, ev_list in by_category.items():
            if cat in CATEGORY_PATTERNS:
                continue
            ev_list.sort(key=lambda e: e["ts"], reverse=True)
            w(SEPARATOR)
            w(f"  {cat.upper()}  ({len(ev_list)} events)")
            w(SEPARATOR)
            for e in ev_list:
                w(f"  [{e['ts'].strftime('%Y-%m-%d %H:%M:%S')}]  [{e['filename']}]")
                w(f"  {e['line'].strip()}")
                w()

        w(SEPARATOR)
        w("  END OF REPORT")
        w(SEPARATOR)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scan Plex logs for deletion/removal events and write a text report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--ssh",
        metavar="USER@HOST",
        default="",
        help="SSH target (e.g. plex@192.168.1.124). Requires key-based auth.",
    )
    parser.add_argument(
        "--log-dir",
        metavar="PATH",
        default="",
        help="Path to the Plex Logs directory. Auto-detected if omitted.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=LOOKBACK_DAYS,
        help=f"How many days back to scan (default {LOOKBACK_DAYS}).",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        default=OUTPUT_FILE,
        help=f"Output report file (default: {OUTPUT_FILE}).",
    )
    args = parser.parse_args()

    cutoff = datetime.now() - timedelta(days=args.days)
    ssh = args.ssh.strip()
    log_dir = args.log_dir.strip()

    # --- Determine log directory ---
    if ssh:
        if not log_dir:
            print("Detecting Plex log directory on remote host...")
            log_dir = find_log_dir_ssh(ssh)
            if not log_dir:
                print("ERROR: Could not find Plex log directory on remote host.")
                print("Tried:")
                for p in DEFAULT_LOG_PATHS:
                    print(f"  {p}")
                print("Specify it explicitly with --log-dir")
                sys.exit(1)
        print(f"Log directory: {log_dir}")
        print("Listing log files...")
        remote_files = list_log_files_ssh(ssh, log_dir)
        if not remote_files:
            print(f"ERROR: No log files found in {log_dir}")
            sys.exit(1)
        print(f"Found {len(remote_files)} log file(s). Scanning...")
        events = []
        scanned = []
        for rf in remote_files:
            short = rf.split("/")[-1]
            print(f"  {short}", end="", flush=True)
            before = len(events)
            events.extend(scan_lines(iter_lines_ssh(ssh, rf), cutoff))
            added = len(events) - before
            print(f" ({added} events)")
            scanned.append(short)
    else:
        if not log_dir:
            # Try local defaults
            for candidate in DEFAULT_LOG_PATHS:
                if Path(candidate).is_dir():
                    log_dir = candidate
                    break
        if not log_dir or not Path(log_dir).is_dir():
            print("ERROR: Cannot find Plex log directory locally.")
            print("Specify --log-dir PATH or --ssh USER@HOST")
            sys.exit(1)
        log_path = Path(log_dir)
        print(f"Log directory: {log_dir}")
        local_files = sorted(log_path.rglob("*.log")) + sorted(log_path.rglob("*.log.*"))
        # De-duplicate while preserving order
        seen = set()
        local_files_dedup = []
        for f in local_files:
            if f not in seen:
                seen.add(f)
                local_files_dedup.append(f)
        local_files = local_files_dedup
        if not local_files:
            print(f"ERROR: No log files found in {log_dir}")
            sys.exit(1)
        print(f"Found {len(local_files)} log file(s). Scanning...")
        events = []
        scanned = []
        for lf in local_files:
            print(f"  {lf.name}", end="", flush=True)
            before = len(events)
            events.extend(scan_lines(iter_lines_local(lf), cutoff))
            added = len(events) - before
            print(f" ({added} events)")
            scanned.append(lf.name)

    print(f"\nTotal events found: {len(events)}")
    print(f"Writing report to: {args.output}")
    write_report(events, args.output, log_dir, ssh, cutoff, scanned)
    print("Done.")

    # Print a quick summary to the console too
    by_cat = defaultdict(int)
    for e in events:
        by_cat[e["category"]] += 1
    if by_cat:
        print("\nCategory breakdown:")
        for cat in CATEGORY_PATTERNS:
            n = by_cat.get(cat, 0)
            if n:
                print(f"  {n:>5}  {cat}")


if __name__ == "__main__":
    main()
