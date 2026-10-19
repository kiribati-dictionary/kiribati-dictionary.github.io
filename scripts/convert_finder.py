# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Convert Trussel's English-Kiribati finder pages into data/english.yaml.

Reads  sources/trussel/html/find_*.htm, data/entries/*.yaml
Writes data/english.yaml

The finder is Trussel's English index: each English word lists the Kiribati
entries whose definitions use it, with the definition line. We keep it as he
made it, and only replace his page anchors with our entry ids:

    - english: fish
      refs:
      - source: sabatier
        entry: aikai
        homograph: 1
        text: a species of fish (small *tauman*).

Run convert_trussel.py first. Usage: uv run scripts/convert_finder.py
"""

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from convert_trussel import LETTERS, OUT, SOURCES, SRC, TEXT_LT, Dumper, clean, make_id, protect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "english.yaml"

BLOCK = re.compile(r"<TABLE CELLPADDING=10 CELLSPACING=0 BORDER=0 WIDTH=75% BGCOLOR=white>", re.I)
KEY = re.compile(r"<FONT COLOR=darkblue SIZE=\+1><B>(.*?)</B></FONT>", re.I | re.S)
REF_SPLIT = re.compile(r"<BR><FONT SIZE=-1>([A-Z]+) </FONT>\s*&nbsp;", re.I)
REF = re.compile(r'<A HREF="dic_\w+\.htm#([^"]+)">\s*<FONT COLOR=darkred><B>(.*?)</B></A>\.?\s*</FONT>(.*)', re.I | re.S)


def snippet(fragment):
    """Definition line -> text with *kiribati* markup. The finder's markup is looser than the dictionary's."""
    s = protect(fragment)
    s = re.sub(r"<FONT COLOR=darkred>(?:<B>)?(.*?)(?:</B>)?</FONT>",
               lambda m: f"*{clean(m.group(1))}*", s, flags=re.I | re.S)
    s = re.sub(r"<I>(.*?)</I>", lambda m: f"_{clean(m.group(1))}_", s, flags=re.I | re.S)
    return clean(s.replace(TEXT_LT, "<")).rstrip()


def main():
    entries = [e for l in LETTERS for e in yaml.safe_load((OUT / f"{l}.yaml").read_text(encoding="utf-8"))]
    by_anchor = {}
    for e in entries:
        by_anchor.setdefault(e["trussel"], []).append(e)

    index, unresolved = [], set()
    for page in sorted(SRC.glob("find_*.htm")):
        text = page.read_text(encoding="latin-1")
        for block in BLOCK.split(text)[1:]:
            km = KEY.search(block)
            if not km:
                continue  # keys with no references
            english = clean(km.group(1))
            refs = []
            pieces = REF_SPLIT.split(block[km.end():])
            for code, body in zip(pieces[1::2], pieces[2::2]):
                m = REF.search(body)
                if not m:
                    continue
                anchor, head, rest = m.groups()
                sup = re.search(r"<SUP>(\d+)</SUP>", head, re.I)
                form = clean(re.sub(r"<SUP>.*?</SUP>", "", head, flags=re.I | re.S))
                candidates = by_anchor.get(anchor, [])
                if not candidates:
                    unresolved.add(anchor)
                    continue
                best = next((c for c in candidates if make_id(c["headword"]) == make_id(form)), candidates[0])
                ref = {"source": SOURCES.get(code, code), "entry": best["id"]}
                if sup:
                    ref["homograph"] = int(sup.group(1))
                rest = re.split(r"</TD></TR></TABLE>", rest, flags=re.I)[0]
                ref["text"] = snippet(rest)
                refs.append(ref)
            if refs:
                index.append({"english": english, "refs": refs})

    with open(DEST, "w", encoding="utf-8") as f:
        yaml.dump(index, f, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=100)
    print(f"{len(index)} English words, {sum(len(x['refs']) for x in index)} references")
    if unresolved:
        print(f"{len(unresolved)} references to entries we don't have, e.g. {', '.join(sorted(unresolved)[:10])}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
