# Kiribati–English Dictionary

A free, searchable Kiribati (Gilbertese)–English dictionary for the web, built as a static site with no server.

> Work in progress. Live at https://kiribati-dictionary.github.io/. We are still seeking permission from rights holders; see below.

## Sources

The dictionary content comes from **A Combined Kiribati-English Dictionary**, compiled by Stephen Trussel and Gordon W. Groves (University of Hawaiʻi, 1978) and revised and edited by Stephen Trussel (2003), as published on [trussel.com](https://www.trussel.com/f_kir.htm#Gil). It combines these works:

| Code | Work |
| --- | --- |
| `bingham` | Hiram Bingham, *A Gilbertese-English Dictionary* (1908, 1953). American Board of Commissioners for Foreign Missions. |
| `sabatier` | Ernest Sabatier, M.S.C., *Dictionnaire Gilbertin-Français* (1954), translated by Sr. M. Oliva as *Gilbertese-English Dictionary* (1971). South Pacific Commission Publications Bureau. |
| `goo-banner` | Fannie C. C. Goo & Albert H. Banner, *A Preliminary Compilation of Gilbertese Animal and Plant Names* (1963). |
| `luomala` | Katharine Luomala, *Ethnobotany of the Gilbert Islands* (1953). Bernice P. Bishop Museum Bulletin 213. |

Stephen Trussel (d. 2020) spent decades documenting the Kiribati language. This project builds on his work.

## Rights

- **Code** in this repository is released under the MIT licence.
- **Dictionary content** remains the property of its respective rights holders and is not covered by the MIT licence. Bingham (1908) is in the public domain. We are seeking permission for the remaining material; if you hold rights to any of it and have concerns, please open an issue.

## Layout

```
data/entries/        dictionary entries, one YAML file per letter
data/english.yaml    Trussel's English index: each English word and the entries that use it
data/topics.yaml     topics for browsing (keyword lists; edit freely)
data/labels.yaml     what each abbreviation (n., vt., ex. ...) means
sources/trussel/     archived copies of the original pages, unmodified, with a manifest
scripts/             tools to fetch and convert source material, and to build the site
web/                 the site's stylesheet, script, icon and service worker
site/                the built website (generated, not committed)
legacy/              the earlier Tekitinari app (website + API), kept with its history
```

## Entry format

Each entry records what each source says, in that source's own terms:

```yaml
- id: kurikuri
  headword: kurikuri
  sources:
  - source: bingham
    forms:
    - form: kúrikuri          # Bingham marks stress
      parts:
      - label: n.
        text: a portion of the entrails of a shark.
  - source: sabatier
    forms:
    - form: kurikuri
      parts:
      - label: va.
        text: '*ua kurikuri*: to have or produce fruit in profusion.'
```

Inside `text`: `*kiribati words*`, `[[cross-reference]]` (or `[[entry-id|shown text]]`), and `_scientific names_`. Multiple examples are on separate lines.

## Rebuilding the data

Requires [uv](https://docs.astral.sh/uv/).

```sh
python3 scripts/fetch_trussel.py        # download archived source pages (slow, polite)
uv run scripts/convert_trussel.py       # regenerate data/entries/
uv run scripts/convert_finder.py        # regenerate data/english.yaml (needs data/entries/)
```

## Building the website

```sh
uv run scripts/build_site.py            # writes site/
python3 -m http.server -d site          # preview at http://localhost:8000
```

The site is plain HTML with relative links. It has a page for every entry, every English word in the index, every letter and every topic.

- **Search** runs in the browser, from the header of every page. `headwords.json` loads on the first keystroke, then `english.json`; `fulltext.json` only when someone searches the full text.
- **Offline:** a service worker (`web/sw.js`) saves the small pages, the search data and `bundle/` (every entry's content) after the first visit. Pages that weren't visited are drawn from the bundle by `offline.html`.
- **Corrections:** every entry links to a pre-filled GitHub issue form (`.github/ISSUE_TEMPLATE/correction.yml`).
- **Deploying:** every push to `main` rebuilds the site and publishes it to GitHub Pages (`.github/workflows/pages.yml`).
