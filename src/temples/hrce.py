"""HR&CE (hrce.tn.gov.in) as a second source: what the department's own temple pages say, beside Dinamalar's.

A temple is addressed by its HR&CE number (TM0nnnnn -> tid). The numbers come from the department's published
temple register, linked to our records in `output/hrce_links.csv` by `hrce_register.py` (rows without a tid are
temples that could not be linked). The site's search form is protected by a CAPTCHA and is not used.

Two public pages are read per temple, both plain server-rendered HTML:
    history.php?tid=N      the temple's history (தல வரலாறு), in full
    speciality.php?tid=N   the list of its specialities: kind and heading (the detail opens in a pop-up, not read)

Content is the HR&CE Department's. Like the Dinamalar text, it is kept under output/ (git-ignored) for
personal research.
"""

import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from config.settings import settings

log = logging.getLogger("agentapp")

BASE = "https://hrce.tn.gov.in/hrcehome/"


def page_url(page: str, tid: int) -> str:
    return f"{BASE}{page}.php?tid={tid}"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_title(html: str) -> Dict[str, str]:
    """Name, place and number from the page title: 'Arulmigu X Temple, Place - 600004, Y District [TM000001].,…'"""
    soup = BeautifulSoup(html, "lxml")
    title = _clean(soup.title.get_text() if soup.title else "")
    m = re.search(r"^(.*?)\s*\[(TM\d{6})\]", title)
    # the Tamil name is printed in the page head: "அருள்மிகு … திருக்கோயில், ஊர் - 600004, … மாவட்டம்."
    ta = re.search(r"அருள்மிகு[^\[\]<>]{3,220}?மாவட்டம்", soup.get_text(" "))
    title_ta = _clean(ta.group(0)) if ta else ""
    if not m:
        return {"hrce_title": title, "hrce_title_ta": title_ta, "hrce_no": ""}
    return {"hrce_title": m.group(1).rstrip(" ,"), "hrce_title_ta": title_ta, "hrce_no": m.group(2)}


def parse_history(html: str) -> str:
    """The history text. The page shows a short start with 'மேலும்..'; the rest is in the same paragraph, hidden."""
    soup = BeautifulSoup(html, "lxml")
    box = soup.select_one("div.history-con")
    if box is None:
        return ""
    for a in box.select("a, script, style"):  # the 'more / less' links
        a.decompose()
    parts = [_clean(p.get_text(" ")) for p in box.select("p.pgh_text")]
    return "\n".join(p for p in parts if p)


def parse_speciality(html: str) -> List[Dict[str, str]]:
    """Rows of the speciality table: [{kind, heading}]."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for tr in soup.select("table tr"):
        cells = [_clean(td.get_text(" ")) for td in tr.find_all("td")]
        if len(cells) >= 3 and cells[0].isdigit():
            out.append({"kind": cells[1], "heading": cells[2]})
    return out


class HrceStore:
    """output/hrce_links.csv (input) and output/hrce.jsonl (one record per temple, appended as read)."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.out = output_dir or settings.output_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.links_path = self.out / "hrce_links.csv"
        self.records_path = self.out / "hrce.jsonl"

    def load_links(self) -> List[Dict[str, str]]:
        if not self.links_path.exists():
            return []
        with self.links_path.open(encoding="utf-8-sig", newline="") as f:
            return [r for r in csv.DictReader(f) if r.get("temple_id") and str(r.get("tid", "")).isdigit()]

    def done_ids(self) -> set:
        if not self.records_path.exists():
            return set()
        with self.records_path.open(encoding="utf-8") as f:
            return {json.loads(line)["temple_id"] for line in f if line.strip()}

    def append(self, record: Dict) -> None:
        with self.records_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load(self) -> List[Dict]:
        if not self.records_path.exists():
            return []
        with self.records_path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


async def stage_hrce(client, store: HrceStore, limit: Optional[int] = None) -> Dict[str, int]:
    """Read the history and speciality pages of every linked temple not read yet. Resumable."""
    done = store.done_ids()
    todo = [l for l in store.load_links() if l["temple_id"] not in done]
    if limit:
        todo = todo[:limit]
    stats = {"read": 0, "failed": 0, "skipped": len(done)}
    for link in todo:
        tid = int(link["tid"])
        try:
            history_html = await client.get_text(page_url("history", tid))
            speciality_html = await client.get_text(page_url("speciality", tid))
        except Exception as e:  # FetchError: logged, the temple is retried on the next run
            log.warning(f"HR&CE {link['temple_id']} (tid {tid}): {e}")
            stats["failed"] += 1
            continue
        store.append({
            "temple_id": link["temple_id"], "tid": tid, **parse_title(history_html),
            "history_ta": parse_history(history_html), "speciality": parse_speciality(speciality_html),
            "read_at": datetime.now().isoformat(timespec="seconds"),
        })
        stats["read"] += 1
    return stats
