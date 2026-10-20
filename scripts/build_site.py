# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Build the static website from data/.

Reads  data/entries/*.yaml, data/corrections.yaml, data/community.yaml, data/english.yaml,
       data/topics.yaml, data/labels.yaml,
       web/ (stylesheet, script, service worker template)
Writes site/  (plain HTML, ready for GitHub Pages)

    site/index.html               home page with search
    site/<letter>/                Kiribati headwords for a letter
    site/word/<id>/               one page per entry
    site/english/, english/<l>/   the English index, A-Z
    site/en/<slug>/               one page per English word: the Kiribati words for it
    site/topics/, topics/<id>/    topic lists (see data/topics.yaml)
    site/slang/                   community words marked as slang
    site/add/                     the "Add a word" form
    site/about/
    site/headwords.json           search: id, headword, other spellings, gloss
    site/english.json             search: English word, page slug, entries (best first) with the line that uses the word
    site/fulltext.json            search: plain text of each entry
    site/bundle/<c>.json          every entry page's content, by first letter of id, for offline use
    site/offline.html, sw.js      offline support (service worker)

All links are relative, so the site works from any folder (GitHub Pages serves
project sites from /<repo>/).

Usage: uv run scripts/build_site.py
       python3 -m http.server -d site    # then open http://localhost:8000
"""

import hashlib
import html
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from urllib.parse import quote, urlencode

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEB = ROOT / "web"
MANIFEST = ROOT / "sources" / "trussel" / "manifest.json"
OUT = ROOT / "site"

LETTERS = ["a", "b", "e", "i", "k", "m", "n", "ng", "o", "r", "t", "u", "w"]
TITLE = "Kiribati–English Dictionary"
SITE = "https://kiribati-dictionary.github.io/"
REPO = "https://github.com/kiribati-dictionary/kiribati-dictionary.github.io"
# Web3Forms access key for the correction form (web3forms.com; it is safe to publish:
# it can only send mail to the dictionary's inbox). Empty: entries link to GitHub instead.
CORRECTIONS_KEY = "38953b87-dfc6-45cd-bbdc-4f58bf6691f4"

# short name, full citation; keep in step with README.md
SOURCES = {
    "bingham": ("Bingham", "Hiram Bingham, <i>A Gilbertese-English Dictionary</i> (1908, 1953). "
                "American Board of Commissioners for Foreign Missions."),
    "sabatier": ("Sabatier", "Ernest Sabatier, M.S.C., <i>Dictionnaire Gilbertin-Français</i> (1954), "
                 "translated by Sr. M. Oliva as <i>Gilbertese-English Dictionary</i> (1971). "
                 "South Pacific Commission Publications Bureau."),
    "goo-banner": ("Goo & Banner", "Fannie C. C. Goo &amp; Albert H. Banner, <i>A Preliminary Compilation "
                   "of Gilbertese Animal and Plant Names</i> (1963)."),
    "luomala": ("Luomala", "Katharine Luomala, <i>Ethnobotany of the Gilbert Islands</i> (1953). "
                "Bernice P. Bishop Museum Bulletin 213."),
    "community": ("Community", "Words and meanings contributed by readers of this dictionary and checked "
                  "by the editor. Not from the printed dictionaries."),
}
PRINTED = {"bingham", "sabatier", "goo-banner", "luomala"}
COMPILATION = ("<i>A Combined Kiribati-English Dictionary</i>, compiled by Stephen Trussel and "
               "Gordon W. Groves (University of Hawaiʻi, 1978), revised and edited by Stephen "
               "Trussel (2003), as published on trussel.com.")

esc = html.escape
written = hashlib.sha1()


def key(s):
    """Search key: lowercase, no accents, letters and digits only ('Nga n tarire' -> 'ngantarire')."""
    s = unicodedata.normalize("NFKD", s.lower().replace("æ", "ae"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)))


def slug(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "x"


ENTRY_IDS = set()  # filled in by main(): every entry id, for linking Kiribati words


def render_text(text, base, here=None):
    """Our light markup (see convert_trussel.py) -> HTML. Escapes first, then marks up.
    A Kiribati word in bold that is exactly an entry's headword links to it (unless that
    entry is `here`); Trussel's own cross-references link as he made them."""
    s = esc(text, quote=False)

    def xref(m):
        target, shown = m.group(1), m.group(2) or m.group(1).replace("-", " ")
        return f'<a class="k" lang="gil" href="{base}word/{target}/">{shown}</a>'

    def kiribati(m):
        target = slug(html.unescape(m.group(1)))
        if target in ENTRY_IDS and target != here:
            return f'<a class="k" lang="gil" href="{base}word/{target}/">{m.group(1)}</a>'
        return f'<b class="k" lang="gil">{m.group(1)}</b>'

    s = re.sub(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]", xref, s)
    s = re.sub(r"\*([^*\n]+)\*", kiribati, s)
    s = re.sub(r"(?<![\w])_([^_\n]+)_(?![\w])", r"<i>\1</i>", s)
    return s


def plain(text):
    """Our markup -> plain text, for search and summaries."""
    text = re.sub(r"\[\[[^|\]]+\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", lambda m: m.group(1).replace("-", " "), text)
    return re.sub(r"[*_]", "", text)


def definitions(entry, labels):
    """Plain-text lines of an entry's definitions, leaving out examples and cross-references."""
    for src in entry["sources"]:
        for form in src["forms"]:
            for part in form["parts"]:
                if "text" in part and labels.get(part.get("label"), {}).get("kind") not in ("example", "xref"):
                    yield from plain(part["text"]).split("\n")


def gloss(entry, labels, limit=90):
    """A short summary: the first definition."""
    for t in definitions(entry, labels):
        return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"
    return ""


def apply_corrections(by_id, corrections):
    """data/corrections.yaml -> edits to the converted entries. Returns problems (the build stops on any)."""
    problems = []
    for c in corrections:
        e = by_id.get(c["entry"])
        src = next((s for s in e["sources"] if s["source"] == c["source"]), None) if e else None
        if not src:
            problems.append(f"correction for {c['entry']}: " + (f"no {c['source']} section in that entry" if e else "no entry with that id"))
            continue
        hits = [(f, p) for f in src["forms"] for p in f["parts"] if c["find"] in p.get("text", "")]
        if len(hits) != 1:
            problems.append(f"correction for {c['entry']}: “{c['find']}” appears {len(hits)} times in {c['source']}, not once")
            continue
        form, part = hits[0]
        part["text"] = part["text"].replace(c["find"], c["replace"], 1)
        if c.get("kind") == "editorial":
            form["parts"].insert(form["parts"].index(part) + 1,
                                 {"label": "corrected", "text": f"The printed dictionary has “{c['find']}”."})
    return problems


def add_community(by_letter, by_id, community):
    """data/community.yaml -> a Community source on existing entries, or new entries.
    Returns [(entry, word)] and problems (the build stops on any)."""
    added, problems = [], []
    for w in community:
        parts = []
        if w.get("meaning"):
            parts.append({"label": w["label"], "text": w["meaning"]} if w.get("label") else {"text": w["meaning"]})
        if w.get("example"):
            parts.append({"label": "ex.", "text": w["example"]})
        notes = (["Slang"] if w.get("slang") else []) + ([f"used in {w['region']}"] if w.get("region") else [])
        if notes:
            parts.append({"label": "note.", "text": "; ".join(notes) + "."})
        src = {"source": "community", "forms": [{"form": w["headword"], "parts": parts}]}
        wid = slug(w["headword"])
        if wid in by_id:
            e = by_id[wid]
            e["sources"].append(src)
        else:
            k = key(w["headword"])
            letter = "ng" if k.startswith("ng") else k[:1]
            if letter not in by_letter:
                problems.append(f"community word “{w['headword']}”: no letter page for “{letter}”")
                continue
            e = {"id": wid, "headword": w["headword"], "trussel": None, "sources": [src]}
            words = by_letter[letter]
            at = next((i for i, x in enumerate(words) if key(x["headword"]) > k), len(words))
            words.insert(at, e)
            by_id[wid] = e
        added.append((e, w))
    return added, problems


def ranked_refs(item):
    """An English word's references grouped by entry, best translations first:
    entries whose definition is just the word ("eat.", "to eat, to consume."), then
    entries more sources agree on, then shorter definitions. Returns [(entry id, refs, best ref)]."""
    word = re.escape(item["english"].lower())
    direct = re.compile(rf"(?:to |a |an |the )?{word}(?:e?s)?(?:[.,;:]|$)")

    def score(ref):
        return (0 if direct.match(plain(ref["text"]).lower()) else 1, len(ref["text"]))

    groups = {}
    for ref in item["refs"]:
        groups.setdefault(ref["entry"], []).append(ref)
    ranked = [(eid, refs, min(refs, key=score)) for eid, refs in groups.items()]
    ranked.sort(key=lambda g: (score(g[2])[0], -len(g[1]), score(g[2])[1]))
    return ranked


def short(text, limit=80):
    t = plain(text).split("\n")[0]
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"


def topic_members(entries, topics, labels):
    """{topic id: [entry, ...]} -- see data/topics.yaml for the rule."""
    members = {t["id"]: [] for t in topics}
    patterns = {}
    for t in topics:
        if "keywords" in t:
            words = "|".join(re.escape(k) for k in sorted(t["keywords"], key=len, reverse=True))
            patterns[t["id"]] = re.compile(rf"(?:^|(?<!\bto) )(?:{words})(?:e?s)?(?= |$)")
    for e in entries:
        used = {s["source"] for s in e["sources"]}
        lines = [re.findall(r"[a-z'-]+", line.lower()) for line in definitions(e, labels)]
        for t in topics:
            within = t.get("within", 6)
            if t.get("source") in used or (t["id"] in patterns and any(
                    patterns[t["id"]].search(" ".join(words[:within])) for words in lines)):
                members[t["id"]].append(e)
    return members


def render_part(part, labels, base, here=None):
    out = ['<div class="part">']
    label = part.get("label")
    info = labels.get(label, {})
    kind = info.get("kind", "note")
    if label:
        title = f' title="{esc(info["name"])}"' if "name" in info else ""
        out.append(f'<abbr class="label {kind}"{title}>{esc(label)}</abbr> ')
    text = part.get("text", "")
    if kind == "example" and "\n" in text:
        items = "".join(f"<li>{render_text(t, base, here)}</li>" for t in text.split("\n"))
        out.append(f'<ul class="examples">{items}</ul>')
    elif text:
        out.append(f'<span class="text">{"<br>".join(render_text(t, base, here) for t in text.split(chr(10)))}</span>')
    out.append("</div>")
    return "".join(out)


def render_source(src, labels, base, here=None):
    short, citation = SOURCES.get(src["source"], (src["source"], esc(src["source"])))
    plain_citation = esc(re.sub("<[^>]+>", "", html.unescape(citation)))
    out = [f'<section class="source"><h2 class="source-name" title="{plain_citation}">{esc(short)}</h2>']
    for form in src["forms"]:
        sup = f'<sup>{form["homograph"]}</sup>' if "homograph" in form else ""
        out.append(f'<div class="form"><p class="form-head"><b lang="gil">{esc(form["form"])}</b>{sup}</p>')
        out.extend(render_part(p, labels, base, here) for p in form["parts"])
        out.append("</div>")
    out.append("</section>")
    return "".join(out)


def wordlist(entries, base, labels, limit=90):
    items = "".join(
        f'<li><a href="{base}word/{e["id"]}/" lang="gil">{esc(e["headword"])}</a> '
        f'<span class="gloss">{esc(gloss(e, labels, limit))}</span></li>' for e in entries)
    return f'<ul class="wordlist">{items}</ul>'


def correction_url(e):
    return f"{REPO}/issues/new?" + urlencode(
        {"template": "correction.yml", "title": f"Correction: {e['headword']}", "entry": e["id"]}, quote_via=quote)


def page(title, body, base, description="", home=False):
    desc = f'<meta name="description" content="{esc(description)}">\n' if description else ""
    back = "" if home else f'<a class="back" href="{base}" data-back aria-label="Back">←<span> Back</span></a>'
    search = "" if home else f"""<form class="top-search" action="{base}" role="search">
    <input type="search" name="q" placeholder="Search" aria-label="Search the dictionary" autocomplete="off" autocapitalize="off" spellcheck="false">
  </form>"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<script>try{{var t=localStorage.getItem("kd-theme");if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
{desc}<link rel="stylesheet" href="{base}style.css">
{f'<meta name="corrections-key" content="{CORRECTIONS_KEY}">' if CORRECTIONS_KEY else ""}
<link rel="icon" href="{base}icon.svg" type="image/svg+xml">
<link rel="manifest" href="{base}manifest.webmanifest">
<meta name="theme-color" content="#8a1c1c">
<script src="{base}app.js" defer></script>
</head>
<body>
<header class="top">
  <div class="top-inner">
  {back}
  <a class="brand" href="{base}">Kiribati–English Dictionary</a>
  {search}
  <button class="theme" type="button" data-theme-toggle aria-label="Switch between day and night mode" title="Day / night">◐</button>
  </div>
  <div class="top-results" id="top-results" hidden></div>
</header>
<main id="main">
{body}
</main>
<footer class="bottom">
  <nav class="footer-nav"><a href="{base}">Search</a><a href="{base}english/">English index</a><a href="{base}topics/">Topics</a><a href="{base}slang/">Slang</a><a href="{base}add/">Add a word</a><a href="{base}about/">About</a></nav>
  <p>Content from {COMPILATION} Each entry credits the dictionaries it combines.</p>
</footer>
</body>
</html>
"""


def letter_nav(base, current=None):
    links = "".join(
        f'<a href="{base}{l}/"{" aria-current=page" if l == current else ""} lang="gil">{"Ng" if l == "ng" else l.upper()}</a>'
        for l in LETTERS)
    return f'<nav class="letters" aria-label="Browse Kiribati words by letter">{links}</nav>'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    written.update(str(path.relative_to(OUT)).encode() + text.encode())


def main():
    labels = yaml.safe_load((DATA / "labels.yaml").read_text(encoding="utf-8"))
    topics = yaml.safe_load((DATA / "topics.yaml").read_text(encoding="utf-8"))
    corrections = yaml.safe_load((DATA / "corrections.yaml").read_text(encoding="utf-8")) or []
    community = yaml.safe_load((DATA / "community.yaml").read_text(encoding="utf-8")) or []
    english = yaml.safe_load((DATA / "english.yaml").read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    by_letter = {l: yaml.safe_load((DATA / "entries" / f"{l}.yaml").read_text(encoding="utf-8")) for l in LETTERS}
    converted = {e["id"]: e for l in LETTERS for e in by_letter[l]}
    problems = apply_corrections(converted, corrections)
    community_words, more = add_community(by_letter, converted, community)
    if problems + more:
        sys.exit("\n".join(["Can't build:"] + problems + more))
    # people credited for corrections and words, in the order they were added
    contributors = list(dict.fromkeys(c["contributor"] for c in corrections + community if c.get("contributor")))
    everything = [(l, e) for l in LETTERS for e in by_letter[l]]
    entries = [e for _, e in everything]
    ENTRY_IDS.update(e["id"] for e in entries)
    by_id = {e["id"]: e for e in entries}
    position = {e["id"]: i for i, e in enumerate(entries)}

    # who links to whom
    backlinks = {}
    for e in entries:
        for src in e["sources"]:
            for form in src["forms"]:
                for part in form["parts"]:
                    for target in re.findall(r"\[\[([^|\]]+)", part.get("text", "")):
                        if target != e["id"] and target in by_id:
                            backlinks.setdefault(target, {})[e["id"]] = None

    members = topic_members(entries, topics, labels)
    topics_of = {}
    for t in topics:
        for e in members[t["id"]]:
            topics_of.setdefault(e["id"], []).append(t)

    # English words get a page each; give each a unique slug
    seen = {}
    for item in english:
        s = slug(item["english"])
        seen[s] = seen.get(s, 0) + 1
        item["slug"] = s if seen[s] == 1 else f"{s}-{seen[s]}"

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for f in WEB.iterdir():
        if f.name != "sw.js":  # filled in at the end
            write(OUT / f.name, f.read_text(encoding="utf-8"))

    def entry_body(i, letter, e, base):
        prev_link = next_link = ""
        if i > 0:
            p = entries[i - 1]
            prev_link = f'<a rel="prev" href="{base}word/{p["id"]}/">← <span lang="gil">{esc(p["headword"])}</span></a>'
        if i + 1 < len(entries):
            n = entries[i + 1]
            next_link = f'<a rel="next" href="{base}word/{n["id"]}/"><span lang="gil">{esc(n["headword"])}</span> →</a>'
        original = manifest.get(f"dic_{letter}.htm", {}).get("url", "")
        credits = "".join(f"<li><b>{esc(SOURCES[s][0])}</b>: {SOURCES[s][1]}</li>"
                          for s in dict.fromkeys(src["source"] for src in e["sources"]) if s in SOURCES)
        tlinks = ", ".join(f'<a href="{base}topics/{t["id"]}/">{esc(t["title"])}</a>' for t in topics_of.get(e["id"], []))
        linked = [by_id[x] for x in backlinks.get(e["id"], {})]
        return f"""<article class="entry">
<h1 class="headword" lang="gil">{esc(e["headword"])}</h1>
{"".join(render_source(s, labels, base, e["id"]) for s in e["sources"]) or '<p class="empty">No definition recorded.</p>'}
{f'<p class="entry-topics">Topics: {tlinks}</p>' if tlinks else ""}
{f'<section class="related"><h2>Words that link here</h2>{wordlist(linked, base, labels, 70)}</section>' if linked else ""}
<aside class="credits">
<h2>Sources</h2>
<ul>{credits}</ul>
{f"""<p>From {COMPILATION}{f' <a href="{esc(original)}#{esc(e["trussel"])}">Original page (archived)</a>.' if original and e["trussel"] else ""}</p>""" if any(s["source"] in PRINTED for s in e["sources"]) else ""}
<details class="correct" data-entry="{e["id"]}" data-headword="{esc(e["headword"])}" data-sources="{",".join(dict.fromkeys(s["source"] for s in e["sources"]))}">
<summary>Suggest a correction</summary>
<p class="correct-github">Have a GitHub account? You can also <a href="{esc(correction_url(e))}">report it on GitHub</a>.</p>
</details>
</aside>
<nav class="prevnext">{prev_link}{next_link}</nav>
</article>"""

    headwords, fulltext, bundle = [], [], {}
    for i, (letter, e) in enumerate(everything):
        g = gloss(e, labels)
        write(OUT / "word" / e["id"] / "index.html",
              page(f"{e['headword']} — {TITLE}", entry_body(i, letter, e, "../../"), "../../",
                   description=f"{e['headword']}: {g}"))
        bundle[e["id"]] = [e["headword"], entry_body(i, letter, e, "")]
        forms = {f["form"] for s in e["sources"] for f in s["forms"]}
        headwords.append([e["id"], e["headword"], sorted({key(f) for f in forms} - {key(e["headword"])}), g])
        text = " ".join(plain(p.get("text", "")) for s in e["sources"] for f in s["forms"] for p in f["parts"])
        fulltext.append(re.sub(r"\s+", " ", text).lower())

    # Kiribati letter pages
    for letter in LETTERS:
        name = "Ng" if letter == "ng" else letter.upper()
        body = f"""{letter_nav("../", letter)}
<h1 class="letter-title" lang="gil">{name}</h1>
<p class="count">{len(by_letter[letter]):,} Kiribati words</p>
{wordlist(by_letter[letter], "../", labels, 60)}"""
        write(OUT / letter / "index.html", page(f"{name} — {TITLE}", body, "../"))

    # English index
    en_letters = {}
    for item in english:
        first = slug(item["english"])[:1]
        en_letters.setdefault(first if first.isalpha() else "other", []).append(item)
    en_order = sorted(l for l in en_letters if l != "other") + (["other"] if "other" in en_letters else [])

    def en_nav(base, current=None):
        links = "".join(f'<a href="{base}english/{l}/"{" aria-current=page" if l == current else ""}>{l.upper() if l != "other" else "…"}</a>'
                        for l in en_order)
        return f'<nav class="letters" aria-label="Browse English words by letter">{links}</nav>'

    for item in english:
        groups = item["ranked"] = ranked_refs(item)
        lis = []
        for eid, refs, _ in groups:
            lines = "".join(f'<li><span class="src">{esc(SOURCES.get(r["source"], (r["source"],))[0])}</span> '
                            f'{render_text(r["text"], "../../")}</li>' for r in refs)
            lis.append(f'<li><a href="../../word/{eid}/" lang="gil">{esc(by_id[eid]["headword"])}</a><ul>{lines}</ul></li>')
        first = slug(item["english"])[:1]
        letter = first if first.isalpha() else "other"
        body = f"""<p class="crumbs"><a href="../../english/">English index</a> › <a href="../../english/{letter}/">{letter.upper() if letter != "other" else "…"}</a></p>
<h1 class="headword">{esc(item["english"])}</h1>
<p class="count">{len(groups)} Kiribati {"word" if len(groups) == 1 else "words"}</p>
<ul class="en-refs">{"".join(lis)}</ul>"""
        write(OUT / "en" / item["slug"] / "index.html",
              page(f"{item['english']} in Kiribati — {TITLE}", body, "../../",
                   description=f"Kiribati words for “{item['english']}”."))

    for l in en_order:
        items = "".join(f'<li><a href="../../en/{x["slug"]}/">{esc(x["english"])}</a> <span class="n">{len({r["entry"] for r in x["refs"]})}</span></li>'
                        for x in en_letters[l])
        body = f"""{en_nav("../../", l)}
<h1 class="letter-title">{l.upper() if l != "other" else "…"}</h1>
<p class="count">{len(en_letters[l]):,} English words</p>
<ul class="columns">{items}</ul>"""
        write(OUT / "english" / l / "index.html", page(f"English {l.upper()} — {TITLE}", body, "../../"))

    body = f"""<h1>English index</h1>
<p class="lede">Look up an English word to find the Kiribati words whose definitions use it. This is Stephen Trussel's finder list: {len(english):,} English words.</p>
{en_nav("../")}"""
    write(OUT / "english" / "index.html", page(f"English index — {TITLE}", body, "../"))

    # topics
    cards = "".join(f'<li><a href="{t["id"]}/"><b>{esc(t["title"])}</b><span>{esc(t["blurb"])}</span>'
                    f'<span class="n">{len(members[t["id"]]):,} words</span></a></li>' for t in topics)
    body = f"""<h1>Topics</h1>
<p class="lede">Kiribati words grouped by subject. Topics are picked out automatically from the English definitions, so a list may include the odd word that doesn't belong.</p>
<ul class="cards">{cards}</ul>"""
    write(OUT / "topics" / "index.html", page(f"Topics — {TITLE}", body, "../"))
    for t in topics:
        body = f"""<p class="crumbs"><a href="../../topics/">Topics</a></p>
<h1>{esc(t["title"])}</h1>
<p class="lede">{esc(t["blurb"])}</p>
<p class="count">{len(members[t["id"]]):,} Kiribati words</p>
{wordlist(members[t["id"]], "../../", labels, 70)}"""
        write(OUT / "topics" / t["id"] / "index.html", page(f"{t['title']} — {TITLE}", body, "../../"))

    # add a word: a plain form that works without JavaScript (Web3Forms then redirects to
    # thanks/); app.js sends it in place instead, and keeps it for later when offline
    body = f"""<article class="prose">
<h1>Add a word</h1>
<p class="lede">Know a Kiribati word or expression that's missing, including slang or new words? Or heard one and want to know what it means? Tell us here. Words are checked before they're added, and appear under “Community”, separate from the printed dictionaries.</p>
<form class="correct-form word-form" method="post" action="https://api.web3forms.com/submit" data-message-form
      data-thing="word" data-subject="New word" data-sent="It will be checked before it's added to the dictionary.">
  <input type="hidden" name="access_key" value="{CORRECTIONS_KEY}">
  <input type="hidden" name="subject" value="New word">
  <input type="hidden" name="redirect" value="{SITE}thanks/">
  <label><span class="t">Kiribati word or phrase</span><input name="word" required lang="gil" autocapitalize="off" spellcheck="false"></label>
  <label><span class="t">What it means <span>(leave blank if you're asking)</span></span><textarea name="meaning" rows="3"></textarea></label>
  <label><span class="t">An example of it in use <span>(optional)</span></span><textarea name="example" rows="2"></textarea></label>
  <label class="check"><input type="checkbox" name="slang" value="Yes"> It's slang or informal</label>
  <label><span class="t">Where it's used <span>(optional: an island, a region, or a group of people)</span></span><input name="region"></label>
  <label><span class="t">Your name <span>(optional)</span></span><input name="name" autocomplete="name"></label>
  <label class="check"><input type="checkbox" name="credit" value="Yes, credit me by name"> Credit me by name on the About page</label>
  <label><span class="t">Your email <span>(optional, only used to ask about your word)</span></span><input type="email" name="email" autocomplete="email"></label>
  <input type="checkbox" name="botcheck" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true">
  <button type="submit">Send word</button>
  <p class="status" role="status"></p>
</form>
</article>"""
    write(OUT / "add" / "index.html", page(f"Add a word — {TITLE}", body, "../", description="Suggest a Kiribati word for the dictionary."))
    body = """<article class="prose">
<h1>Thank you!</h1>
<p>Your message was sent to the dictionary.</p>
<p><a href="../">Back to the dictionary</a></p>
</article>"""
    write(OUT / "thanks" / "index.html", page(f"Thank you — {TITLE}", body, "../"))

    # slang: community words marked as slang
    slang = [(e, w) for e, w in community_words if w.get("slang")]
    items = "".join(f'<li><a href="../word/{e["id"]}/" lang="gil">{esc(e["headword"])}</a> '
                    f'<span class="gloss">{esc(plain(w.get("meaning", "")))}</span></li>' for e, w in slang)
    body = f"""<h1>Kiribati slang</h1>
<p class="lede">Informal words and everyday expressions. The printed dictionaries rarely record slang, so this list is built by the people who use it: each word is contributed by a reader and checked before it's added.</p>
{f'<ul class="wordlist">{items}</ul>' if slang else '<p class="empty">No slang words yet. Be the first to add one.</p>'}
<p><a href="../add/?slang=1">Add a slang word →</a></p>"""
    write(OUT / "slang" / "index.html", page(f"Slang — {TITLE}", body, "../", description="Kiribati slang and informal expressions, contributed by readers."))

    # home
    cards = "".join(f'<li><a href="topics/{t["id"]}/"><b>{esc(t["title"])}</b><span class="n">{len(members[t["id"]]):,} words</span></a></li>'
                    for t in topics[:8])
    body = f"""<section class="hero">
<h1>Kiribati–English Dictionary</h1>
<p class="lede">{len(entries):,} Kiribati words, with definitions from Bingham, Sabatier, Goo &amp; Banner and Luomala.</p>
<form class="search" role="search" action="">
  <input id="q" type="search" name="q" placeholder="Type a Kiribati or English word" aria-label="Search the dictionary" autocomplete="off" autocapitalize="off" spellcheck="false" autofocus>
</form>
<div id="results" aria-live="polite"></div>
</section>
<section class="ways">
<h2>Browse Kiribati words</h2>
{letter_nav("")}
<h2>Browse in English</h2>
<p><a href="english/">The English index</a>: {len(english):,} English words, each with the Kiribati words for it.</p>
<h2>Topics</h2>
<ul class="cards small">{cards}</ul>
<p><a href="topics/">All {len(topics)} topics →</a></p>
<h2>From readers</h2>
<p><a href="slang/">Kiribati slang</a>, and words contributed by readers. Know one that's missing? <a href="add/">Add a word</a>.</p>
</section>"""
    write(OUT / "index.html", page(TITLE, body, "", description="A free, searchable Kiribati (Gilbertese)–English dictionary.", home=True))

    # about
    cites = "".join(f"<li><b>{esc(s)}</b>: {c}</li>" for s, c in SOURCES.values())
    body = f"""<article class="prose">
<h1>About this dictionary</h1>
<p>This is {COMPILATION}</p>
<p>It combines these works. Every entry shows which of them each definition comes from.</p>
<ul>{cites}</ul>
<p>Stephen Trussel (d. 2020) spent decades documenting the Kiribati language. This site builds on his work.</p>
<h2>Who made this</h2>
<p>This site was put together by <a href="https://emiliobarkett.github.io/">Emilio Barkett</a>. It grew out of <i>Tekitinari</i>, an earlier Kiribati dictionary app made by <a href="https://www.linkedin.com/in/jacob-roberts-6b748a2a5/">Jacob Roberts</a>.</p>
<h2>Reading an entry</h2>
<p>Labels such as <abbr class="label pos">n.</abbr> or <abbr class="label pos">vt.</abbr> are shown as each source wrote them; hover over a label to see what it stands for. Kiribati words inside definitions are in <b class="k" lang="gil">bold</b>, and links lead to other entries.</p>
<h2>Using it offline</h2>
<p>After your first visit, the whole dictionary is saved in your browser and works without a connection.</p>
<h2>Corrections</h2>
<p>Every entry has a “Suggest a correction” form; no account is needed. Corrections are checked against the original printed sources. If you leave your name and ask to be credited, it will be listed on this page once your correction is made.</p>
<h2>Adding words</h2>
<p>Know a word that's missing, including slang? <a href="../add/">Add it</a>. Words are checked before they're added, and appear under “Community”, separate from the printed dictionaries.</p>
{f'<h3>Thank you to</h3><p>{", ".join(esc(c) for c in contributors)}, for corrections and new words.</p>' if contributors else ""}
<h2>Ideas for the website</h2>
<p>Have an idea for a feature, or something that would make the dictionary easier to use? Tell us.</p>
<form class="correct-form" method="post" action="https://api.web3forms.com/submit" data-message-form
      data-thing="suggestion" data-subject="Website suggestion" data-sent="We read every one.">
  <input type="hidden" name="access_key" value="{CORRECTIONS_KEY}">
  <input type="hidden" name="subject" value="Website suggestion">
  <input type="hidden" name="redirect" value="{SITE}thanks/">
  <label><span class="t">Your idea</span><textarea name="idea" rows="4" required></textarea></label>
  <label><span class="t">Your name <span>(optional)</span></span><input name="name" autocomplete="name"></label>
  <label><span class="t">Your email <span>(optional, only used to ask about your idea)</span></span><input type="email" name="email" autocomplete="email"></label>
  <input type="checkbox" name="botcheck" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true">
  <button type="submit">Send idea</button>
  <p class="status" role="status"></p>
</form>
<h2>Rights</h2>
<p>The dictionary content belongs to its respective rights holders. Bingham (1908) is in the public domain.</p>
</article>"""
    write(OUT / "about" / "index.html", page(f"About — {TITLE}", body, "../"))

    # offline shell: the service worker serves this, with a <base> pointing at the site root,
    # for pages that aren't cached; app.js fills it from bundle/ or english.json
    write(OUT / "offline.html", page(TITLE, '<p class="empty" data-offline>Loading…</p>', ""))

    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    write(OUT / "headwords.json", dump(headwords))
    write(OUT / "english.json", dump([[x["english"], x["slug"], [[position[eid], short(best["text"])] for eid, _, best in x["ranked"]]]
                                      for x in english]))
    write(OUT / "fulltext.json", dump(fulltext))
    shards = {}
    for eid, item in bundle.items():
        shards.setdefault(eid[0], {})[eid] = item
    for c, shard in shards.items():
        write(OUT / "bundle" / f"{c}.json", dump(shard))
    write(OUT / ".nojekyll", "")

    precache = (["./", "about/", "topics/", "english/", "slang/", "add/", "thanks/", "offline.html", "style.css", "app.js", "icon.svg", "manifest.webmanifest",
                 "headwords.json", "english.json", "fulltext.json"]
                + [f"bundle/{c}.json" for c in sorted(shards)]
                + [f"{l}/" for l in LETTERS] + [f"english/{l}/" for l in en_order] + [f"topics/{t['id']}/" for t in topics])
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    sw = sw.replace("__VERSION__", written.hexdigest()[:12]).replace("__PRECACHE__", json.dumps(precache))
    (OUT / "sw.js").write_text(sw, encoding="utf-8")

    mb = lambda n: f"{(OUT / n).stat().st_size / 1e6:.1f} MB"
    print(f"{len(entries)} entries, {len(english)} English words, {len(topics)} topics")
    print(f"headwords.json {mb('headwords.json')}, english.json {mb('english.json')}, "
          f"fulltext.json {mb('fulltext.json')}, bundle {sum(f.stat().st_size for f in (OUT / 'bundle').iterdir()) / 1e6:.1f} MB")
    for t in topics:
        print(f"  topic {t['id']}: {len(members[t['id']])}")


if __name__ == "__main__":
    sys.exit(main())
