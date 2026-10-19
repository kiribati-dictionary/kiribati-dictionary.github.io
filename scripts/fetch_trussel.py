"""Download Stephen Trussel's Kiribati-English dictionary pages from the Internet Archive.

The live site (trussel.com) sits behind a bot check, so we take the most recent
successful Wayback Machine snapshot of each page instead. Files are saved
unmodified to sources/trussel/html/ along with a manifest recording which
snapshot each one came from.

Usage: python3 scripts/fetch_trussel.py [--force]
"""

import gzip
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sources" / "trussel" / "html"
MANIFEST = ROOT / "sources" / "trussel" / "manifest.json"

DICT_LETTERS = ["a", "b", "e", "i", "k", "m", "n", "ng", "o", "r", "t", "u", "w"]
FINDER_LETTERS = list("abcdefghijklmnopqrstuvwxyz")
PAGES = [f"dic_{l}.htm" for l in DICT_LETTERS] + [f"find_{l}.htm" for l in FINDER_LETTERS]
BASE = "www.trussel.com/kir/dic/"
MIN_SIZE = 5000  # anything smaller is an error or bot-check page


def get(url, tries=5):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kiribati-english-dictionary/0.1"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            # the archive sometimes replays the original gzip-encoded body as-is
            return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        except Exception as e:
            wait = 10 * (attempt + 1)
            print(f"  retry in {wait}s ({e})", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"failed: {url}")


def snapshots(page):
    q = urllib.parse.urlencode({
        "url": BASE + page, "fl": "timestamp,length",
        "filter": "statuscode:200", "output": "json",
    })
    rows = json.loads(get(f"https://web.archive.org/cdx/search/cdx?{q}") or b"[]")
    # newest first; skip the header row
    return sorted((r[0] for r in rows[1:]), reverse=True)


def main():
    force = "--force" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    for page in PAGES:
        dest = OUT / page
        if dest.exists() and page in manifest and not force:
            continue
        for ts in snapshots(page)[:6]:
            data = get(f"https://web.archive.org/web/{ts}id_/https://{BASE}{page}")
            time.sleep(2)
            if len(data) >= MIN_SIZE and b"<HTML" in data[:200].upper():
                dest.write_bytes(data)
                manifest[page] = {
                    "snapshot": ts,
                    "url": f"https://web.archive.org/web/{ts}/https://{BASE}{page}",
                    "bytes": len(data),
                }
                print(f"{page}: {ts} ({len(data):,} bytes)")
                break
        else:
            print(f"{page}: NO USABLE SNAPSHOT", file=sys.stderr)
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        time.sleep(2)


if __name__ == "__main__":
    main()
