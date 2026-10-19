# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Check that converting Trussel's pages lost no words.

For every entry, compares the words visible on the original HTML page with
the words in data/entries/, ignoring our markup. Prints any differences.

Usage: uv run scripts/check_trussel.py > reports/trussel-check.txt
"""

import collections
import html
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from convert_trussel import ENTRY_SPLIT, LETTERS, OUT, SRC, SOURCES, TEXT_LT, protect  # noqa: E402


def words(text):
    return collections.Counter(re.findall(r"[^\W_]+", text.lower()))


def html_words(chunk):
    chunk = re.sub(r"<SUP>.*?</SUP>", "", protect(chunk), flags=re.I | re.S)  # homograph numbers
    chunk = re.sub(r"</?(A|FONT|B|I)\b[^>]*>", "", chunk, flags=re.I)  # inline tags don't break words
    text = html.unescape(re.sub(r"<[^>]+>", " ", chunk).replace(TEXT_LT, "<"))
    w = words(text)
    for code in SOURCES:  # the B / O / G / L source markers
        w[code.lower()] -= 1
    return +w


def yaml_words(entry):
    text = [entry["headword"]]
    for src in entry["sources"]:
        for form in src["forms"]:
            text.append(form["form"])
            for part in form["parts"]:
                text.append(part.get("label", ""))
                t = part.get("text", "")
                # [[id|shown]] -> shown ; [[id]] -> id with hyphens as spaces
                t = re.sub(r"\[\[[^|\]]+\|([^\]]+)\]\]", r"\1", t)
                t = re.sub(r"\[\[([^\]]+)\]\]", lambda m: m.group(1).replace("-", " "), t)
                text.append(t)
    return words(" ".join(text))


def main():
    problems = 0
    for letter in LETTERS:
        page = (SRC / f"dic_{letter}.htm").read_text(encoding="latin-1")
        page = page.split('<P><CENTER><A HREF="#TOP">', 1)[0]
        chunks = ENTRY_SPLIT.split(page)[1:]
        entries = yaml.safe_load((OUT / f"{letter}.yaml").read_text(encoding="utf-8"))
        if len(chunks) != len(entries):
            print(f"{letter}: {len(chunks)} blocks on page but {len(entries)} entries")
        for chunk, entry in zip(chunks, entries):
            a, b = html_words(chunk), yaml_words(entry)
            missing, extra = a - b, b - a
            # hyphenated ids ("tae-ua") are matched against words, so ignore hyphen noise
            if missing or extra:
                problems += 1
                print(f"{entry['id']}: missing {dict(missing)} extra {dict(extra)}")
    print(f"{problems} entries with differences", file=sys.stderr)


if __name__ == "__main__":
    main()
