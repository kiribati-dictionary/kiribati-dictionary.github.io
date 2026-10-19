# Project notes

Goal: an open, OED-style Kiribati–English dictionary website (simple, fast, good UI), later extended with more Kiribati language data.

## Decisions so far (Oct 2026)

- **Hosting:** fully static GitHub Pages site, no server. Search runs in the browser; every headword gets its own page/URL.
- **Primary data:** Stephen Trussel's combined dictionary (Bingham, Sabatier/Oliva, Goo & Banner, Luomala), taken from Internet Archive snapshots of trussel.com. The live site has a Cloudflare bot check; do not try to get around it.
- **Rights:** Trussel died in 2020. Emilio is contacting the current owner of trussel.com. Keep the repo private until that is resolved. Credit every source on every entry; never relicense dictionary content.
- **Legacy:** the friend's old app (Tabuariki/tabuariki.github.io + Tabuariki/tekitinari) is imported with full history under `legacy/`. Its `dictionary.db` is an OCR'd copy of Sabatier with parsing errors; use it only to cross-check.
- **Data format:** YAML per letter in `data/entries/`, faithful to Trussel's markup (source → forms → labelled parts). Reinterpretation (sense numbering, example splitting) belongs in the site renderer or later, reviewed passes, not in the converter.
- **Future:** pipeline for scanned dictionaries Emilio uploads, each kept as a separate source.
