"""Set what HR&CE says about a temple beside what Dinamalar says, and check each link on the way.

A link made from the register is confirmed here by the HR&CE page itself: its Tamil title carries the temple's
name, place and pincode. A row is `confirmed` when the pincode is the same or the place is, and the temple's (or
its deity's) name is nearly the same; otherwise `doubtful`, and its HR&CE text should not be used for that temple.

output/hrce_compare.csv has one row per linked temple: the two names, the check, HR&CE's remedy (பரிகாரம்) and
prayer (பிரார்த்தனை) headings, and for each theme named by Dinamalar's prayer text whether HR&CE's text names it.
"""

import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from config.settings import settings
from .hrce_register import _ratio, latin_skeleton, record_pincode, skeleton

# theme -> Tamil words that name it (in Dinamalar's prayer text, and in HR&CE's history and speciality headings)
THEMES: Dict[str, str] = {
    "rahu_ketu_naga": r"நாக ?தோஷ|சர்ப்ப|சர்ப ?தோஷ|ராகு|இராகு|கேது",
    "sani": r"சனி ?தோஷ|சனி ?பகவான|சனீஸ்வர|சனிபகவான|ஏழரை|சனிப்பெயர்ச்சி|அஷ்டம ?சனி",
    "sevvai": r"செவ்வாய்|அங்காரக",
    "guru": r"குரு ?தோஷ|குரு ?பகவான|குருபகவான|குரு ?பரிகார|குரு ?பெயர்ச்சி|குரு ?ஸ்தல",
    "surya_chandra_budha_sukra": r"சூரிய ?தோஷ|சூரியன்|சந்திர ?தோஷ|சந்திரன்|புதன்|சுக்கிர",
    "navagraha": r"நவக்கிரக|நவகிரக|கிரக ?தோஷ|ஜாதக",
    "pitru": r"பித்ரு|பிதுர்|முன்னோர்|தர்ப்பண",
    "brahmahatti": r"பிரம்மஹத்தி|பிரம்மகத்தி|பிரமகத்தி|பிரம்ம ?ஹத்தி",
    "child_boon": r"புத்திர|குழந்தை|மகப்பேறு|பிள்ளைப்பேறு|பிள்ளை வரம்|சந்தான",
    "marriage": r"திருமண|கல்யாண|விவாக|மாங்கல்ய",
}
COLUMNS = (["temple_id", "hrce_no", "link", "check", "name_ta", "town_ta", "hrce_name_ta", "hrce_has_text",
            "hrce_pariharam", "hrce_prayer"] + [f"{t}" for t in THEMES])


def check_link(rec: Dict, hrce: Dict) -> str:
    """confirmed / doubtful, from the HR&CE page's own Tamil title."""
    title = hrce.get("hrce_title_ta") or ""
    if not title:
        return "doubtful"
    head = title.split(" - ")[0]
    parts = [p.strip() for p in head.split(",")]
    their_name, their_places = skeleton(parts[0]), skeleton(" ".join(parts[1:]))
    names = {skeleton(rec.get("name_ta") or "")} | {skeleton(m) for m in re.split(r"[,/()]", rec.get("moolavar_ta") or "")}
    name = max((_ratio(n, their_name) for n in names if len(n) >= 3), default=0.0)
    town = skeleton(rec.get("town_ta") or "")
    pin = record_pincode(rec)
    same_pin = bool(pin) and pin in title
    same_place = bool(their_places) and len(town) >= 3 and (
        town in their_places or their_places in town or _ratio(town, their_places) >= 0.75)
    if not same_place:                      # HR&CE gives some places in English
        theirs = latin_skeleton(" ".join(p for p in parts[1:] if re.search(r"[A-Za-z]{3}", p)))
        ours = latin_skeleton(rec.get("town_en") or "")
        same_place = len(ours) >= 3 and len(theirs) >= 3 and (ours in theirs or theirs in ours or _ratio(ours, theirs) >= 0.75)
    # the same place and a close name; or, where only the pincode agrees, the same name. Many temple names end
    # alike (…ஈஸ்வரர், …நாதர்), so "close" is set high.
    return "confirmed" if (same_place and name >= 0.8) or (same_pin and name >= 0.95) else "doubtful"


def compare(records: List[Dict], hrce_records: List[Dict], links: List[Dict]) -> List[Dict]:
    by_id = {r["temple_id"]: r for r in records}
    link_by_id = {l["temple_id"]: l for l in links}
    rows = []
    for h in hrce_records:
        rec = by_id.get(h["temple_id"])
        if rec is None:
            continue
        spec = h.get("speciality") or []
        text = (h.get("history_ta") or "") + " " + " ".join(f"{s['kind']} {s['heading']}" for s in spec)
        has_text = len(text.strip()) >= 40
        dinamalar = " ".join(str(rec.get(k) or "") for k in ("prayers_ta", "speciality_ta", "special_features_ta"))
        row = {
            "temple_id": h["temple_id"], "hrce_no": h.get("hrce_no", ""),
            "link": link_by_id.get(h["temple_id"], {}).get("confidence", ""), "check": check_link(rec, h),
            "name_ta": rec.get("name_ta") or "", "town_ta": rec.get("town_ta") or "",
            "hrce_name_ta": h.get("hrce_title_ta") or h.get("hrce_title") or "",
            "hrce_has_text": "yes" if has_text else "no",
            "hrce_pariharam": "; ".join(s["heading"] for s in spec if "பரிகார" in s["kind"] and s["heading"]),
            "hrce_prayer": "; ".join(s["heading"] for s in spec if "பிரார்த்த" in s["kind"] and s["heading"]),
        }
        for theme, words in THEMES.items():
            claimed = bool(re.search(words, dinamalar))
            # blank: Dinamalar does not name it; yes / no: whether HR&CE's text names it; ?: HR&CE has no text
            row[theme] = "" if not claimed else "?" if not has_text else "yes" if re.search(words, text) else "no"
        rows.append(row)
    return rows


def stage_compare(output_dir: Optional[Path] = None) -> Dict[str, int]:
    out = output_dir or settings.output_dir

    def jsonl(name):
        with (out / name).open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    with (out / "hrce_links.csv").open(encoding="utf-8-sig", newline="") as f:
        links = list(csv.DictReader(f))
    rows = compare(jsonl("temples.jsonl"), jsonl("hrce.jsonl"), links)
    with (out / "hrce_compare.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    good = [r for r in rows if r["check"] == "confirmed"]
    stats = {"read": len(rows), "confirmed": len(good), "doubtful": len(rows) - len(good),
             "confirmed_with_text": sum(r["hrce_has_text"] == "yes" for r in good),
             "confirmed_with_pariharam": sum(bool(r["hrce_pariharam"]) for r in good)}
    return stats
