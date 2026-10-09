"""Everything the scraper keeps on disk. Writes are append-only or atomic, so a run can be stopped at
any point (Ctrl+C, crash, power cut) and the next run carries on from where it stopped.

output/districts.json        stage 1: [{district_id, district_name}]
output/temples_index.csv     stage 2: one row per temple, appended page by page, unique temple_id
data/progress/stage2.json    stage 2: per district, the last list page done and whether it's complete
output/temples.jsonl         stage 3: one record per temple, appended as each temple is parsed
output/failed.log            every failure: time, URL, reason (tab separated)
output/temples.csv / .xlsx   export of temples.jsonl
"""

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from config.settings import TEXT_FIELDS, settings

INDEX_COLUMNS = ["district_id", "district_name", "temple_id", "temple_name", "url"]

# Record columns in export order; each TEXT_FIELDS entry expands to _ta, _en, _source_en
LEAD_COLUMNS = ["temple_id", "district_id", "district_name", "url_ta", "url_en", "english_page"]
TAIL_COLUMNS = ["category_id", "latitude", "longitude", "main_image", "gallery",
                "nearby_ta", "nearby_en", "extra_ta", "extra_en", "scraped_at"]
RECORD_COLUMNS = (LEAD_COLUMNS
                  + [f"{f}_{suffix}" for f in TEXT_FIELDS for suffix in ("ta", "en", "source_en")]
                  + TAIL_COLUMNS)

_EXCEL_CELL_MAX = 32767


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Store:
    def __init__(self, output_dir: Optional[Path] = None, progress_dir: Optional[Path] = None):
        self.out = output_dir or settings.output_dir
        self.progress = progress_dir or settings.progress_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.progress.mkdir(parents=True, exist_ok=True)
        self.districts_path = self.out / "districts.json"
        self.index_path = self.out / "temples_index.csv"
        self.stage2_path = self.progress / "stage2.json"
        self.records_path = self.out / "temples.jsonl"
        self.failed_path = self.out / "failed.log"

    # --- Stage 1 ---------------------------------------------------------------------------------
    def save_districts(self, districts: List[Dict[str, str]]) -> None:
        _write_atomic(self.districts_path, json.dumps(districts, ensure_ascii=False, indent=2))

    def load_districts(self) -> List[Dict[str, str]]:
        if not self.districts_path.exists():
            return []
        return json.loads(self.districts_path.read_text(encoding="utf-8"))

    # --- Stage 2 ---------------------------------------------------------------------------------
    def load_stage2_state(self) -> Dict[str, Dict[str, Any]]:
        if not self.stage2_path.exists():
            return {}
        return json.loads(self.stage2_path.read_text(encoding="utf-8"))

    def save_stage2_state(self, state: Dict[str, Dict[str, Any]]) -> None:
        _write_atomic(self.stage2_path, json.dumps(state, indent=2))

    def load_index(self) -> List[Dict[str, str]]:
        if not self.index_path.exists():
            return []
        with self.index_path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def append_index(self, rows: Iterable[Dict[str, str]]) -> None:
        rows = list(rows)
        if not rows:
            return
        if not self.index_path.exists():
            # BOM once, at file creation, so Excel reads Tamil correctly; appends are plain UTF-8
            with self.index_path.open("w", encoding="utf-8-sig", newline="") as f:
                csv.DictWriter(f, INDEX_COLUMNS).writeheader()
        with self.index_path.open("a", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, INDEX_COLUMNS).writerows(rows)

    # --- Stage 3 ---------------------------------------------------------------------------------
    def load_records(self) -> List[Dict[str, Any]]:
        if not self.records_path.exists():
            return []
        records = []
        for line in self.records_path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                continue  # a line cut short by a crash; that temple is simply fetched again
        return records

    def done_temple_ids(self) -> Set[str]:
        return {r["temple_id"] for r in self.load_records()}

    def append_record(self, record: Dict[str, Any]) -> None:
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        with self.records_path.open("ab+") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":  # previous run died mid-line
                    line = b"\n" + line
            f.write(line)
            f.flush()

    def rewrite_records(self, records: List[Dict[str, Any]]) -> None:
        _write_atomic(self.records_path,
                      "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))

    def log_failure(self, url: str, reason: str) -> None:
        reason = " ".join(str(reason).split())
        with self.failed_path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}\t{url}\t{reason}\n")

    # --- Export ----------------------------------------------------------------------------------
    @staticmethod
    def _flat(record: Dict[str, Any]) -> List[str]:
        row = []
        for col in RECORD_COLUMNS:
            value = record.get(col, "")
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False) if value else ""
            row.append("" if value is None else str(value))
        return row

    def export(self, records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Path]:
        """temples.csv (utf-8-sig, so Excel shows Tamil) and temples.xlsx from temples.jsonl."""
        from openpyxl import Workbook
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

        records = self.load_records() if records is None else records
        records = sorted(records, key=lambda r: (int(r.get("district_id") or 0), int(r["temple_id"])))
        csv_path, xlsx_path = self.out / "temples.csv", self.out / "temples.xlsx"

        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(RECORD_COLUMNS)
            w.writerows(self._flat(r) for r in records)

        wb = Workbook(write_only=True)
        ws = wb.create_sheet("temples")
        ws.append(RECORD_COLUMNS)
        for r in records:
            # Excel caps a cell at 32,767 characters; the CSV and JSONL keep the full text
            ws.append([ILLEGAL_CHARACTERS_RE.sub("", v)[:_EXCEL_CELL_MAX] for v in self._flat(r)])
        wb.save(xlsx_path)
        return {"csv": csv_path, "xlsx": xlsx_path}
