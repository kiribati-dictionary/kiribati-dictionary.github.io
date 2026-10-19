# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Convert Trussel's dictionary HTML pages into structured YAML entries.

Reads  sources/trussel/html/dic_*.htm
Writes data/entries/<letter>.yaml

The conversion is deliberately faithful: it records what Trussel marked up
(which source said what, the labels such as "n." or "ex.", which words are
Kiribati) without trying to reinterpret the content. Inline text uses a small
markup the website understands:

    *kai antai*          Kiribati word or phrase
    [[ai-antai]]         cross-reference to another entry, by its id
    [[ai-antai|ai antai]] cross-reference whose shown text differs from the id
    _Cypraea_            scientific name (italic in the original)

Usage: uv run scripts/convert_trussel.py
"""

import html
import re
import unicodedata
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "sources" / "trussel" / "html"
OUT = ROOT / "data" / "entries"

LETTERS = ["a", "b", "e", "i", "k", "m", "n", "ng", "o", "r", "t", "u", "w"]

SOURCES = {
    "B": "bingham",
    "O": "sabatier",
    "G": "goo-banner",
    "L": "luomala",
}

ENTRY_SPLIT = re.compile(r"(?=<TABLE CELLPADDING=10 CELLSPACING=0 BORDER=0 WIDTH=75% BGCOLOR=white>)", re.I)
SOURCE_SPLIT = re.compile(
    r"<CENTER><TABLE CELLSPACING=0 BORDER=0 WIDTH=90%><TR VALIGN=TOP><TD WIDTH=10>\s*"
    r"<FONT SIZE=-1>([A-Z]+)</FONT>&nbsp;</TD><TD>", re.I)
# a source block may hold several homographs, each introduced by a dark green form
FORM = re.compile(r"(?:<BR>)?<FONT COLOR=darkgreen><B>(.*?)</B>\.?\s*</FONT>", re.I | re.S)
LABEL = re.compile(r"<FONT COLOR=blue>([^<]*)</FONT>", re.I)


# Trussel writes editorial notes and topic tags in literal angle brackets, e.g.
# "<myth>" or "<majority -- gwg>" (gwg = Gordon W. Groves). Anything in angle
# brackets that is not a real HTML tag is text and must be kept.
TEXT_LT = "\x01"


def protect(s):
    s = s.replace("<", TEXT_LT)
    return re.sub(TEXT_LT + r"(?=/?(?:A|B|I|FONT|SUP|BR|TD|TR|TABLE|CENTER|P|HR|IMG)\b)", "<", s, flags=re.I)


def inline(fragment):
    """Turn an HTML fragment into plain text with our light markup."""
    s = protect(fragment)
    # cross-references: <A HREF="dic_a.htm#aiantai"><FONT COLOR=darkred><B>ai antai</B></FONT></A>
    # targets are Trussel anchors for now; resolve_xrefs() turns them into our ids
    def xref(m):
        return f"[[{m.group(1)}|{clean(m.group(2))}]]"
    s = re.sub(r'<A HREF="dic_\w+\.htm#([^"]+)">\s*<FONT COLOR=darkred><B>(.*?)</B></FONT>\s*</A>', xref, s, flags=re.I | re.S)
    # Kiribati words and phrases
    s = re.sub(r"<FONT COLOR=darkred><B>(.*?)</B></FONT>", lambda m: f"*{clean(m.group(1))}*", s, flags=re.I | re.S)
    s = re.sub(r"<I>(.*?)</I>", lambda m: f"_{clean(m.group(1))}_", s, flags=re.I | re.S)
    s = re.sub(r"<SUP>(.*?)</SUP>", r"\1", s, flags=re.I | re.S)
    return clean(s)


def lines(fragment):
    """Items in the original end with '&nbsp;' and a newline; keep one per line."""
    items = (inline(x) for x in re.split(r"&nbsp;\s*\n", fragment))
    return "\n".join(x for x in items if x)


def clean(s):
    s = re.sub(r"<[^>]+>", "", protect(s))   # drop remaining tags (English index links etc.)
    s = s.replace(TEXT_LT, "<")
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:!?)])", r"\1", s)  # "stick , a" -> "stick, a"
    return s


def make_id(headword):
    """'Tae ua' -> 'tae-ua'. Unlike Trussel's anchors, keeps word boundaries."""
    s = unicodedata.normalize("NFKD", headword.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "entry"


def assign_ids(entries):
    """Give every entry a unique id; return {trussel anchor: [ids]}."""
    seen, by_anchor = {}, {}
    for e in entries:
        base = make_id(e["headword"])
        n = seen.get(base, 0) + 1
        seen[base] = n
        e["id"] = base if n == 1 else f"{base}-{n}"
        by_anchor.setdefault(e["trussel"], []).append(e)
    return by_anchor


def resolve_xrefs(entries, by_anchor, unresolved):
    """Rewrite [[anchor|text]] to [[id]] or [[id|text]]."""
    def fix(m):
        anchor, text = m.group(1), m.group(2)
        candidates = by_anchor.get(anchor, [])
        if not candidates:
            unresolved.append(anchor)
            return f"*{text}*"  # keep the word, drop the dead link
        best = next((c for c in candidates if make_id(c["headword"]) == make_id(text)), candidates[0])
        return f"[[{best['id']}]]" if best["id"] == make_id(text) else f"[[{best['id']}|{text}]]"

    for e in entries:
        for src in e["sources"]:
            for form in src["forms"]:
                for part in form["parts"]:
                    if "text" in part:
                        part["text"] = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", fix, part["text"])


def parse_form(head_html):
    """'ka<FONT SIZE=-1><SUP>1</SUP></FONT>' -> ('ka', 1)"""
    m = re.search(r"<SUP>(\d+)</SUP>", head_html, re.I)
    number = int(m.group(1)) if m else None
    text = clean(re.sub(r"<SUP>.*?</SUP>", "", head_html, flags=re.I | re.S))
    return text.rstrip(":").strip(), number


def parse_parts(body):
    """Split a form's body into [{label, text}] at each blue label."""
    parts = []
    pieces = LABEL.split(body)
    # pieces = [text before first label, label1, text1, label2, text2, ...]
    lead = lines(pieces[0])
    if lead:
        parts.append({"text": lead})
    for label, text in zip(pieces[1::2], pieces[2::2]):
        part = {"label": clean(label)}
        t = lines(text)
        if t:
            part["text"] = t
        parts.append(part)
    return parts


def parse_source(code, block):
    forms = []
    matches = list(FORM.finditer(block))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        body = block[m.end():end]
        body = re.split(r"</TD></TR></TABLE></CENTER>", body, flags=re.I)[0]
        form, number = parse_form(m.group(1))
        f = {"form": form}
        if number is not None:
            f["homograph"] = number
        f["parts"] = parse_parts(body)
        forms.append(f)
    return {"source": SOURCES.get(code, code), "forms": forms}


def parse_entry(chunk):
    m = re.search(r"<A NAME=\"?([^\">]+)\"?>+</A>\s*<FONT COLOR=darkred SIZE=\+1><B>(.*?)</B></FONT>", chunk, re.I | re.S)
    if not m:
        return None
    entry = {"id": None, "headword": clean(m.group(2)), "trussel": m.group(1), "sources": []}
    blocks = SOURCE_SPLIT.split(chunk)
    # blocks = [preamble, code1, html1, code2, html2, ...]
    for code, block in zip(blocks[1::2], blocks[2::2]):
        entry["sources"].append(parse_source(code, block))
    return entry


def convert_letter(letter):
    path = SRC / f"dic_{letter}.htm"
    text = path.read_text(encoding="latin-1")
    text = text.split("<P><CENTER><A HREF=\"#TOP\">", 1)[0]  # drop page footer
    entries = []
    for chunk in ENTRY_SPLIT.split(text)[1:]:
        e = parse_entry(chunk)
        if e:
            entries.append(e)
        else:
            print(f"  {letter}: could not parse block starting {chunk[:120]!r}", file=sys.stderr)
    return entries


class Dumper(yaml.SafeDumper):
    pass


def _str(dumper, s):
    style = "|" if "\n" in s else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)


Dumper.add_representer(str, _str)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    by_letter = {}
    for letter in LETTERS:
        if not (SRC / f"dic_{letter}.htm").exists():
            print(f"{letter}: missing source page, skipped", file=sys.stderr)
            continue
        by_letter[letter] = convert_letter(letter)

    everything = [e for entries in by_letter.values() for e in entries]
    by_anchor = assign_ids(everything)
    unresolved = []
    resolve_xrefs(everything, by_anchor, unresolved)

    for letter, entries in by_letter.items():
        with open(OUT / f"{letter}.yaml", "w", encoding="utf-8") as f:
            yaml.dump(entries, f, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=100)
        print(f"{letter}: {len(entries)} entries")
    print(f"total: {len(everything)}")
    if unresolved:
        print(f"{len(unresolved)} cross-references point to missing entries, e.g. "
              f"{', '.join(sorted(set(unresolved))[:10])}", file=sys.stderr)


if __name__ == "__main__":
    main()
