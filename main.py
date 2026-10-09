"""AgentAPP: temple details for every district under "மாவட்ட கோயில்" on temple.dinamalar.com.

Full run (stages 1-3, then export to CSV/XLSX):
    python main.py

Test run on Chennai, 5 temples:
    python main.py --district 46 --limit 5

One stage only:
    python main.py --stage 2
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import date

from tqdm import tqdm

from config.settings import settings
from src.temples import pipeline
from src.temples.store import Store

log = logging.getLogger("agentapp")

STAGES = ["1", "2", "3", "translate", "export", "all"]


class TqdmHandler(logging.StreamHandler):
    """Console log lines that don't break the progress bars."""
    def emit(self, record):
        tqdm.write(self.format(record))


def setup_logging(verbose: bool = False) -> None:
    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    log.setLevel(logging.DEBUG)
    console = TqdmHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    file = logging.FileHandler(settings.logs_dir / f"scrape_{date.today().isoformat()}.log", encoding="utf-8")
    file.setLevel(logging.DEBUG)
    for handler in (console, file):
        handler.setFormatter(fmt)
        log.addHandler(handler)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape district temples from temple.dinamalar.com.")
    parser.add_argument("--stage", choices=STAGES, default="all",
                        help="1 = districts, 2 = temple index, 3 = temple details, translate = fill "
                             "missing English, export = CSV/XLSX; default: all (1, 2, 3, export)")
    parser.add_argument("--district", help="Only this district id (e.g. 46 = Chennai) in stages 2, 3, translate")
    parser.add_argument("--limit", type=int, help="Process at most N items in this run "
                                                  "(stage 2: districts, stage 3 / translate: temples)")
    parser.add_argument("--no-translate", action="store_true",
                        help="Don't machine-translate; English comes only from the site's English pages")
    parser.add_argument("--refresh-districts", action="store_true", help="Re-download the district list")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug messages (retries, each failure)")
    args = parser.parse_args(argv)
    if args.district is not None and not args.district.isdigit():
        parser.error("--district must be a numeric district id, e.g. 46")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    return args


def make_translator(args):
    if args.no_translate:
        return None
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set (add it to .env), or run with --no-translate.")
    from src.temples.translate import Translator
    return Translator()


def print_summary(store: Store, district_id=None) -> None:
    rows = pipeline.district_counts(store)
    if district_id:
        rows = [r for r in rows if r["district_id"] == district_id]
    if not rows:
        return
    width = max(len(r["district_name"]) for r in rows) + 2
    print(f"\n{'id':>5}  {'district'.ljust(width)}{'listed':>8}{'scraped':>9}")
    for r in rows:
        print(f"{r['district_id']:>5}  {r['district_name'].ljust(width)}{r['listed']:>8}{r['scraped']:>9}")
    print(f"{'':>5}  {'TOTAL'.ljust(width)}{sum(r['listed'] for r in rows):>8}{sum(r['scraped'] for r in rows):>9}")


async def run(args) -> int:
    store = Store()
    stages = ["1", "2", "3", "export"] if args.stage == "all" else [args.stage]
    translator = make_translator(args) if ("3" in stages or "translate" in stages) else None
    failed_before = store.failed_path.stat().st_size if store.failed_path.exists() else 0

    from src.temples.scraper import PoliteClient
    async with PoliteClient() as client:
        if "1" in stages or "2" in stages:
            districts = await pipeline.stage1_districts(client, store, refresh=args.refresh_districts)
            if "2" in stages:
                if args.district:
                    districts = [d for d in districts if d["district_id"] == args.district]
                    if not districts:
                        log.error(f"District id {args.district} is not on the district list.")
                        return 2
                await pipeline.stage2_index(client, store, districts, limit=args.limit)
        if "3" in stages:
            if not store.load_index():
                log.error("No temple index yet; run stage 2 first.")
                return 2
            stats = await pipeline.stage3_temples(client, store, translator, args.district, args.limit)
            log.info(f"Stage 3: {dict(stats)}")
    if "translate" in stages:
        stats = await pipeline.stage_translate(store, translator, args.district, args.limit)
        log.info(f"Translate: {dict(stats)}")
    if translator is not None:
        log.info(f"Translation: {translator.api_calls} API call(s), {len(translator.cache)} cached text(s)")
    if "export" in stages or "translate" in stages:
        paths = store.export()
        log.info(f"Exported {store.records_path.name} -> {paths['csv'].name}, {paths['xlsx'].name}")

    print_summary(store, args.district)
    failed_now = store.failed_path.stat().st_size if store.failed_path.exists() else 0
    if failed_now > failed_before:
        log.warning(f"Some requests failed this run; see {store.failed_path}. Re-run to retry them.")
        return 1
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Tamil on a Windows console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    setup_logging(args.verbose)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        log.warning("Stopped. Progress is saved; run the same command again to resume.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
