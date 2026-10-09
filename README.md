# AgentAPP

Collects temple details for every district listed under **மாவட்ட கோயில்**
(`https://temple.dinamalar.com/district_temple_list.php`), in Tamil and English.

Content is Dinamalar's copyright. This project is for personal research use. Everything it saves
(`output/`, `data/`) is git-ignored, and so are the saved pages the parser tests use.

The project uses the same layout as AgentSYNC: `main.py` (CLI) → `config/settings.py` → `src/temples/`
(`scraper`, `parser`, `pipeline`, `store`, plus `translate`). The site is plain server-rendered HTML,
so it uses httpx + BeautifulSoup and doesn't need a browser.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then set ANTHROPIC_API_KEY (only needed for machine translation)
```

## Usage

```bash
python main.py --district 46 --limit 5     # test: Chennai, 5 temples
python main.py                             # everything: stages 1, 2, 3, then CSV/XLSX export
```

| Flag | Notes |
|---|---|
| `--stage 1\|2\|3` | run one stage only; also `translate` and `export` (default: `all` = 1, 2, 3, export) |
| `--district <id>` | one district only (stages 2, 3, translate), e.g. `46` = சென்னை |
| `--limit N` | at most N items this run (stage 2: districts, stage 3 / translate: temples) |
| `--no-translate` | English only from the site's English pages; fill the gaps later with `--stage translate` |
| `--refresh-districts` | download the district list again |
| `-v` | show retries and each failure on screen (always written to `logs/`) |

Every stage can resume. Stop it at any point and run the same command again: it skips
district pages and temples already done. A run that had failures exits with code 1; re-run it to
retry only the failed items.

## Stages

| Stage | Reads | Writes |
|---|---|---|
| 1 | `district_temple_list.php` | `output/districts.json` (33 districts) |
| 2 | `district_temple.php?id=<d>&Page=N`, until a page has no **Next >>** | `output/temples_index.csv`: one row per temple, unique by `temple_id`; progress in `data/progress/stage2.json` |
| 3 | `new.php?id=<t>`, and `en/new_en.php?id=<t>` when the Tamil page links to it | `output/temples.jsonl`: one line per temple, appended as parsed |
| translate | `temples.jsonl` | the same file, with blank English fields machine-translated |
| export | `temples.jsonl` | `output/temples.csv` (UTF-8 with BOM, so Excel shows Tamil) and `output/temples.xlsx` |

Failures (URL + reason) go to `output/failed.log`. A single failure never stops the run.

## Politeness

At most 3 requests in flight. Each request slot waits a random 1–2 s after every request.
Timeouts, connection errors and 5xx responses are retried up to 5 times with exponential backoff.
HTTP 429 pauses all requests for `Retry-After` seconds. Other 4xx responses fail immediately.
The client sends a normal browser User-Agent and doesn't try to get around any bot protection
or rate limit. All of these settings can be changed in `.env` (see `.env.example`).

## Fields

Each text field is stored three times: `<field>_ta`, `<field>_en` and `<field>_source_en`. The
source is `site` (from the English page), `machine` (translated), or empty (no Tamil text either).

| Field | Tamil label | English label |
|---|---|---|
| name | (page title) | (page title) |
| category | e.g. 274 சிவாலயங்கள் (+ `category_id`) | (machine) |
| moolavar | மூலவர் | Moolavar |
| urchavar | உற்சவர் | Urchavar |
| amman | அம்மன்/தாயார் | Amman / Thayar |
| sthala_vriksham | தல விருட்சம் | Thala Virutcham |
| theertham | தீர்த்தம் | Theertham |
| agamam | ஆகமம்/பூஜை | Agamam / Pooja |
| age | பழமை | Old year |
| old_name | புராண பெயர் | Historical Name |
| town / district / state | ஊர் / மாவட்டம் / மாநிலம் | City / District / State |
| singers | பாடியவர்கள் (incl. Devaram verse) | Singers |
| festivals | திருவிழா | Festival |
| speciality | தல சிறப்பு | Temple's Speciality |
| timings | திறக்கும் நேரம் | Opening Time |
| address / phone | முகவரி / போன் | Address / Phone |
| general_info | பொது தகவல் | General Information |
| prayers / thanksgiving | பிரார்த்தனை / நேர்த்திக்கடன் | Prayers / Thanks giving |
| greatness / history | தலபெருமை / தல வரலாறு | Greatness Of Temple / Temple History |
| special_features | சிறப்பம்சம் (sub-sections as `label: text`) | Special Features |
| location / railway / airport / accommodation | செல்லும் வழி tab | How to reach tab |

Other columns: `temple_id`, `district_id`, `district_name`, `url_ta`, `url_en`, `english_page`,
`latitude`, `longitude`, `main_image`, `gallery` (JSON list: large image URL, thumbnail, Tamil and
English caption), `nearby_ta` / `nearby_en` (names), `extra_ta` / `extra_en` (any section with a
label not listed above), `scraped_at`.

Site quirks the parser handles:
- An unknown id, or the English URL of a temple without an English version, still returns HTTP 200,
  with an empty template. Such pages are detected and skipped.
- The English pages print `-` or `0` for empty values; these are stored as blank.

## Machine translation

Fields with Tamil text but no English are translated with the Claude API (model `claude-haiku-4-5`,
set with `TRANSLATE_MODEL`). Text is sent in chunks of about 1,000 characters, split at paragraphs
and sentences. Names of temples, deities and places are transliterated instead of translated, with
the glossary அருள்மிகு = Arulmigu, திருக்கோயில் = Temple. Each chunk's translation is cached in
`data/cache/translations.jsonl`, keyed by the SHA-256 of the Tamil text, so reruns never translate
the same text twice. Photo captions and nearby-temple names are not translated.

## Tests

```bash
python tests/fixtures/fetch_fixtures.py   # once: saves the 8 site pages the parser tests use
python -m pytest tests
```
