"""The scrape stages, independent of HTTP details (the fetcher is passed in).

Stage 1  district list            -> districts.json
Stage 2  each district's pages    -> temples_index.csv   (follows Page=N until there is no "Next >>")
Stage 3  each temple (ta + en)    -> temples.jsonl       (English from the site's English page)
Categories  menu lists 1-28       -> temple_categories.csv, and temples.jsonl for temples not in it yet
Missing English is filled afterwards by translate.py (local model).
"""

import asyncio
import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from tqdm import tqdm

from config.settings import CATEGORIES, TEXT_FIELDS, settings
from src.temples.parser import (parse_district_page, parse_districts, parse_list_page, parse_sub_lists,
                                parse_temple)
from src.temples.store import Store

log = logging.getLogger("agentapp")

MAX_PAGES_PER_DISTRICT = 500  # safety stop in case a "Next >>" link ever points back at itself


class Fetcher(Protocol):
    async def get_text(self, url: str) -> str: ...


# --- Stage 1 ---------------------------------------------------------------------------------------

async def stage1_districts(fetcher: Fetcher, store: Store, refresh: bool = False) -> List[Dict[str, str]]:
    existing = store.load_districts()
    if existing and not refresh:
        log.info(f"Stage 1: {len(existing)} districts already in {store.districts_path.name} (skipping)")
        return existing
    url = settings.districts_url
    try:
        districts = parse_districts(await fetcher.get_text(url))
    except Exception as e:
        store.log_failure(url, e)
        raise
    if not districts:
        store.log_failure(url, "no district links found")
        raise RuntimeError("No districts found on the district list page")
    store.save_districts(districts)
    log.info(f"Stage 1: saved {len(districts)} districts to {store.districts_path}")
    return districts


# --- Stage 2 ---------------------------------------------------------------------------------------

async def stage2_index(fetcher: Fetcher, store: Store, districts: List[Dict[str, str]],
                       limit: Optional[int] = None) -> None:
    state = store.load_stage2_state()
    seen = {row["temple_id"] for row in store.load_index()}
    pending = [d for d in districts if not state.get(d["district_id"], {}).get("complete")]
    todo = pending[:limit] if limit else pending
    log.info(f"Stage 2: {len(todo)} district(s) to crawl, {len(districts) - len(pending)} already complete")
    bar = tqdm(total=len(todo), desc="Stage 2 districts", unit="district")

    async def crawl(d: Dict[str, str]) -> None:
        did = d["district_id"]
        progress = state.setdefault(did, {"last_page": 0, "complete": False, "temples": 0})
        page = progress["last_page"] + 1
        while page <= MAX_PAGES_PER_DISTRICT:
            url = settings.district_url(did, page)
            try:
                temples, has_next = parse_district_page(await fetcher.get_text(url))
            except Exception as e:
                store.log_failure(url, e)
                log.error(f"[{d['district_name']}] page {page} failed ({e}); will resume here next run")
                break
            new = [t for t in temples if t["temple_id"] not in seen]
            seen.update(t["temple_id"] for t in new)
            store.append_index({"district_id": did, "district_name": d["district_name"], **t} for t in new)
            # Rows are written before progress, so a crash in between only re-reads one page
            progress.update(last_page=page, complete=not has_next,
                            temples=progress.get("temples", 0) + len(new))
            store.save_stage2_state(state)
            if not temples and page == 1:
                log.warning(f"[{d['district_name']}] has no temples listed")
            if not has_next:
                break
            page += 1
        bar.update(1)

    await asyncio.gather(*(crawl(d) for d in todo))
    bar.close()


# --- Stage 3 ---------------------------------------------------------------------------------------

class TempleNotFound(Exception):
    pass


def build_record(row: Dict[str, str], ta: Dict[str, Any], en: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """One flat record: <field>_ta / <field>_en / <field>_source_en for every text field."""
    tid = row["temple_id"]
    record: Dict[str, Any] = {
        "temple_id": tid,
        "district_id": row.get("district_id", ""),
        "district_name": row.get("district_name", ""),
        "english_page": "yes" if en else "no",
    }
    for f in TEXT_FIELDS:
        en_value = (en or {}).get(f, "")
        record[f"{f}_ta"] = ta.get(f, "")
        record[f"{f}_en"] = en_value
        record[f"{f}_source_en"] = "site" if en_value else ""

    # Photo captions: Tamil and English pages list the same photo files
    en_captions = {g["photo"]: g["caption"] for g in (en or {}).get("gallery", [])}
    record.update({
        "category_id": ta.get("category_id", ""),
        "latitude": ta.get("latitude", ""),
        "longitude": ta.get("longitude", ""),
        "gallery": [{"caption_ta": g["caption"], "caption_en": en_captions.get(g["photo"], "")}
                    for g in ta.get("gallery", [])],
        "nearby_ta": ta.get("nearby", []),
        "nearby_en": (en or {}).get("nearby", []),
        "extra_ta": ta.get("extra", {}),
        "extra_en": (en or {}).get("extra", {}),
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
    })
    return record


async def scrape_temple(fetcher: Fetcher, row: Dict[str, str]) -> Dict[str, Any]:
    tid = row["temple_id"]
    ta = parse_temple(await fetcher.get_text(settings.temple_url(tid)), "ta", settings.image_base_url)
    if not ta["found"]:
        raise TempleNotFound("page has no temple details (empty template)")
    en = None
    if ta.get("has_english_page"):
        en = parse_temple(await fetcher.get_text(settings.temple_url_en(tid)), "en", settings.image_base_url)
        if not en["found"]:
            en = None
    return build_record(row, ta, en)


async def stage3_temples(fetcher: Fetcher, store: Store, district_id: Optional[str] = None,
                         limit: Optional[int] = None) -> Counter:
    index = store.load_index()
    if district_id:
        index = [r for r in index if r["district_id"] == district_id]
    done = store.done_temple_ids()
    todo = [r for r in index if r["temple_id"] not in done]
    if limit:
        todo = todo[:limit]
    log.info(f"Stage 3: {len(todo)} temple(s) to fetch, {len(index) - len(todo)} already done or beyond --limit")
    return await _fetch_temples(fetcher, store, todo, "Stage 3 temples")


async def _fetch_temples(fetcher: Fetcher, store: Store, todo: List[Dict[str, str]], label: str) -> Counter:
    stats: Counter = Counter()
    queue: asyncio.Queue = asyncio.Queue()
    for row in todo:
        queue.put_nowait(row)
    bar = tqdm(total=len(todo), desc=label, unit="temple")

    async def worker() -> None:
        while True:
            try:
                row = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            url = settings.temple_url(row["temple_id"])
            try:
                record = await scrape_temple(fetcher, row)
                store.append_record(record)
                stats["ok"] += 1
                stats["english_page"] += record["english_page"] == "yes"
            except Exception as e:
                stats["failed"] += 1
                store.log_failure(url, f"{type(e).__name__}: {e}")
                log.debug(f"Failed {url}: {e}")
            bar.update(1)

    await asyncio.gather(*(worker() for _ in range(settings.concurrency)))
    bar.close()
    return stats


# --- Categories ------------------------------------------------------------------------------------

async def _crawl_list(fetcher: Fetcher, href: str) -> List[Dict[str, str]]:
    """Every temple of one list, following its "Next >>" pages."""
    temples: List[Dict[str, str]] = []
    visited: set = set()
    while href and href not in visited and len(visited) < MAX_PAGES_PER_DISTRICT:
        visited.add(href)
        found, href = parse_list_page(await fetcher.get_text(settings.page_url(href)))
        temples += found
    return temples


async def stage_categories(fetcher: Fetcher, store: Store, number: Optional[int] = None,
                           limit: Optional[int] = None) -> Counter:
    """List the menu categories in temple_categories.csv, then fetch the temples temples.jsonl lacks.
    A temple already in temples.jsonl is not fetched again: its row refers to that record by temple_id."""
    rows = store.load_categories()
    listed = {r["category_no"] for r in rows}
    done = store.done_temple_ids()
    for no, name, path, sub_list in CATEGORIES:
        if (number and no != number) or str(no) in listed:
            continue
        url = settings.page_url(path)
        try:
            hrefs = parse_sub_lists(await fetcher.get_text(url), sub_list) if sub_list else [path]
            temples: Dict[str, Dict[str, str]] = {}
            for href in hrefs:
                for t in await _crawl_list(fetcher, href):
                    if t["temple_id"] not in temples or not temples[t["temple_id"]]["temple_name"]:
                        temples[t["temple_id"]] = t
        except Exception as e:
            store.log_failure(url, e)
            log.error(f"Category {no} ({name}) failed ({e}); it will be listed again next run")
            continue
        rows += [{"category_no": str(no), "category_name": name, **t,
                  "source": "existing" if t["temple_id"] in done else "new"} for t in temples.values()]
        store.save_categories(rows)  # whole categories only, so a failed one is simply listed again
        log.info(f"Category {no} ({name}): {len(temples)} temple(s), "
                 f"{sum(t not in done for t in temples)} not in {store.records_path.name} yet")

    wanted = [r for r in rows if not number or r["category_no"] == str(number)]
    todo = list({r["temple_id"]: {"temple_id": r["temple_id"]} for r in wanted
                 if r["temple_id"] not in done}.values())
    if limit:
        todo = todo[:limit]
    log.info(f"Categories: {len(todo)} temple(s) to fetch; the rest are already in {store.records_path.name}")
    return await _fetch_temples(fetcher, store, todo, "Category temples")


# --- Summary ---------------------------------------------------------------------------------------

def district_counts(store: Store) -> List[Dict[str, Any]]:
    """Per district: temples listed (index) and scraped (jsonl)."""
    listed = Counter(r["district_id"] for r in store.load_index())
    scraped = Counter(r["district_id"] for r in store.load_records())
    names = {d["district_id"]: d["district_name"] for d in store.load_districts()}
    return [{"district_id": did, "district_name": names.get(did, ""), "listed": listed[did],
             "scraped": scraped[did]}
            for did in sorted(set(listed) | set(scraped), key=lambda d: int(d or 0))]  # "" = category-only temple
