"""The HR&CE Department's published temple register (a PDF list of every temple with its number), and the
linking of our Dinamalar records to it.

The register PDF ("Latest Temple List", one row per temple: serial, TM number, name and place with pincode,
district, office) was printed from a spreadsheet in a legacy Tamil font. Its text layer therefore comes out
scrambled: ligatures appear as stand-in characters, and vowel signs written before a consonant come before it.
Numbers and pincodes are sound. `repair` puts the Tamil back as far as a table can; `skeleton` reduces a name to
its consonants, which is what the linking compares, so that a leftover slip in a vowel sign does not matter.

A link is never taken on trust: the HR&CE page read for it carries the temple's name, and `hrce.py` keeps it.
"""

import csv
import difflib
import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.settings import settings

log = logging.getLogger("agentapp")

# Stand-in character -> the syllable it prints, read from words in the register (அ௠ள்௘ஶ = அருள்மிகு, ...).
GLYPHS: Dict[str, str] = {
    "௠": "ரு", "௫": "ரு", "௡": "ரூ", "ொ": "தி", "ோ": "தீ", "ௌ": "து", "௘": "மி",
    "௙": "மீ", "௚": "மு", "௛": "மூ", "ஶ": "கு", "௜": "யி", "௝": "யீ", "௞": "யு",
    "௟": "யூ", "௳": "வி", "௴": "வீ", "௵": "வு", "௶": "வூ", "஼": "சி", "஽": "சீ",
    "௖": "பு", "ௗ": "பூ", "௔": "பி", "௕": "பீ", "௄": "டு", "௅": "டூ", "௃": "டீ",
    "௧": "லி", "௨": "லீ", "௩": "லு", "௪": "லூ", "௥": "று", "௣": "றி", "௤": "றீ",
    "௱": "ழு", "௲": "ழூ", "௯": "ழி", "௰": "ழீ", "௑": "னு", "௒": "னூ", "௭": "ளூ",
    "௬": "ளு", "௷": "ஜு", "௸": "ஜீ", "௹": "ஷி", "௺": "ஷீ", "௏": "நூ", "௎": "நு",
    "௽": "ஹி", "௿": "க்ஷி", "ఁ": "ஸ்ரீ",
}
CONSONANTS = "கஙசஞடணதநபமயரலவழளறனஜஷஸஹ"
PRE = "ெேை"          # vowel signs the font writes before the consonant
_WORDS = re.compile(r"அருள்மிகு|அ/மி\.?|திருக்கோயில்|திருக்கோவில்|கோயில்|கோவில்|சுவாமி|ஸ்வாமி|சாமி|ஸ்ரீ|ஶ்ரீ")


_C = f"[{CONSONANTS}]"
# Marks the font sets after the wrong letter: கோடை் ட = கோட்டை, சீரக் ாழி = சீர்காழி, புரஸீ ் வரர் = புரீஸ்வரர்.
_DISPLACED = [
    (re.compile(f"({_C})ை் ({_C})"), r"\g<1>்\g<2>ை"),
    (re.compile(f"({_C})({_C})் ா"), r"\g<1>்\g<2>ா"),
    (re.compile(f"({_C})({_C})ீ ் "), r"\g<1>ீ\g<2>்"),
    (re.compile("ாவா௘"), " \ue000வா௘"),        # ...நாதாவா௘ = ...நாத சுவாமி
    (re.compile("ாந்தர"), " \ue000ந்தர"),                  # ாந்தேரஸ்வரர் = சுந்தரேஸ்வரர்
    (re.compile("ாப்(?=[ர௔])"), " \ue000ப்"),         # ாப்ரமணிய = சுப்ரமணிய
]


def repair(text: str) -> str:
    """The register's scrambled Tamil put back in order, as far as the table goes."""
    for pattern, to in _DISPLACED:
        text = pattern.sub(to, text)
    text = text.replace(" \ue000", "\ue000") if text.startswith(" \ue000") else text
    out: List[str] = []
    chars = list(text)
    i = 0
    while i < len(chars):
        ch = chars[i]
        prev = out[-1][-1] if out else " "
        if ch in PRE and i + 1 < len(chars):                       # ெச -> செ ; ேகா -> கோ
            nxt = chars[i + 1]
            base = GLYPHS.get(nxt, nxt)
            if base[:1] in CONSONANTS:
                sign = ch
                if i + 2 < len(chars) and chars[i + 2] == "ா" and ch in "ெே":
                    sign = "ொ" if ch == "ெ" else "ோ"
                    i += 1
                elif i + 2 < len(chars) and chars[i + 2] == "ௗ" and ch == "ெ":
                    sign = "ௌ"
                    i += 1
                out.append(base[0] + sign)
                i += 2
                continue
        if ch == "\ue000":
            out.append("சு")
        elif ch == "ூ":                                             # ஆலங்ஶூ = ஆலங்குடி
            out.append("டி")
        elif ch == "ா" and prev not in CONSONANTS:                  # ாவா௘ = சுவாமி
            out.append("சு")
        elif ch == "்" and prev not in CONSONANTS:                  # ்த்ௌக்ஶூ = தூத்துக்குடி
            out.append("தூ")
        elif ch == " " and prev == "்" and i + 1 < len(chars) and chars[i + 1] in CONSONANTS + "".join(GLYPHS):
            pass                                                    # ஸ் வரர் = ஸ்வரர்
        else:
            out.append(GLYPHS.get(ch, ch))
        i += 1
    return "".join(out)


def skeleton(text: str) -> str:
    """The consonants of a Tamil name, in order, without the stock words (அருள்மிகு, திருக்கோயில், சுவாமி).
    ழ and க are taken as one letter: the register's font prints கி with the sign for ழ."""
    text = _WORDS.sub(" ", text or "")
    return "".join("க" if ch == "ழ" else ch for ch in text if ch in CONSONANTS)


def latin_skeleton(text: str) -> str:
    """The consonant letters of a name in English, for register rows whose place is given in English."""
    return re.sub(r"[^bcdfghjklmnpqrstvwxyz]", "", (text or "").lower().replace("th", "t").replace("sh", "s"))


# --- Reading the PDF --------------------------------------------------------------------------------

_ROW = re.compile(r"^\s*(\d{1,5})\s+(TM\d{6})\s*(.*)$")


def read_register(pdf_path: Path) -> List[Dict]:
    """[{tm, tid, raw, name, places, pincode, rest}] from the register PDF."""
    import pypdfium2 as pdfium  # only this stage needs it

    pdf = pdfium.PdfDocument(str(pdf_path))
    rows: List[Dict] = []
    cur: Optional[Dict] = None
    for i in range(len(pdf)):
        for line in pdf[i].get_textpage().get_text_range().replace("\r", "").split("\n"):
            m = _ROW.match(line)
            if m:
                cur = {"tm": m.group(2), "tid": int(m.group(2)[2:]), "raw": m.group(3).strip(), "page": i + 1}
                rows.append(cur)
            elif cur is not None and line.strip() and "TM0" not in line and not line.startswith("Generated on"):
                cur["raw"] += " " + line.strip()
    seen, out = set(), []
    for r in rows:
        if r["tm"] in seen:
            continue
        seen.add(r["tm"])
        m = re.search(r"^(.*?)\s*-\s*(6\d{5})\b(.*)$", r["raw"])
        head, r["pincode"], r["rest"] = (m.group(1), m.group(2), m.group(3).strip()) if m else (r["raw"], "", "")
        parts = [p.strip() for p in head.split(",") if p.strip()]
        r["name_raw"], r["places_raw"] = (parts[0] if parts else ""), parts[1:]
        r["name"], r["places"] = repair(r["name_raw"]), [repair(p) for p in parts[1:]]
        out.append(r)
    return out


# --- Linking ----------------------------------------------------------------------------------------

LINK_COLUMNS = ["temple_id", "tid", "hrce_no", "confidence", "score", "pincode_match", "name_ta", "town_ta",
                "register_name", "register_place", "runner_up"]


def record_pincode(rec: Dict) -> str:
    m = re.findall(r"(?<!\d)(6\d{2})\s?(\d{3})(?!\d)", f"{rec.get('address_ta') or ''} {rec.get('address_en') or ''}")
    return m[0][0] + m[0][1] if m else ""


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _place_score(town_ta: str, town_en: str, row: Dict) -> float:
    want, want_en = skeleton(town_ta), latin_skeleton(town_en)
    best = 0.0
    for raw, fixed in zip(row["places_raw"], row["places"]):
        if re.search(r"[A-Za-z]{3}", raw):
            have = latin_skeleton(raw)
            score = 1.0 if want_en and (want_en in have or have in want_en) and min(len(have), len(want_en)) >= 3 else _ratio(want_en, have)
        else:
            have = skeleton(fixed)
            score = 1.0 if want and (want in have or have in want) and min(len(have), len(want)) >= 3 else _ratio(want, have)
        best = max(best, score)
    return best


def link_records(records: List[Dict], register: List[Dict]) -> List[Dict]:
    """One row per record: the best register entry, with a confidence of exact, likely or none."""
    by_pin: Dict[str, List[Dict]] = defaultdict(list)
    by_gram: Dict[str, List[Dict]] = defaultdict(list)
    for row in register:
        row["_name"] = skeleton(row["name"])
        row["_all"] = skeleton(" ".join(row["places"]))
        if row["pincode"]:
            by_pin[row["pincode"]].append(row)
        for k in range(len(row["_all"]) - 2):
            by_gram[row["_all"][k:k + 3]].append(row)
    links = []
    for rec in records:
        town = skeleton(rec.get("town_ta") or "")
        # the temple's name, and each name of its deity: the register often has the deity's other name
        names = {skeleton(rec.get("name_ta") or "")} | {skeleton(m) for m in re.split(r"[,/()]", rec.get("moolavar_ta") or "")}
        names = {n for n in names if len(n) >= 3}
        pin = record_pincode(rec)
        def score_all(rows) -> List[Tuple[float, bool, Dict]]:
            out = []
            for row in rows:
                same_pin = bool(pin) and row["pincode"] == pin
                place = max(_place_score(rec.get("town_ta") or "", rec.get("town_en") or "", row), 0.6 if same_pin else 0.0)
                score = 0.6 * max((_ratio(n, row["_name"]) for n in names), default=0.0) + 0.4 * place
                out.append((round(score + (0.03 if same_pin else 0.0), 3), same_pin, row))
            return sorted(out, key=lambda x: -x[0])

        # entries with the record's own pincode first; if none of them is a good match (the two sources do not
        # always give a temple the same pincode), entries whose place has the same name
        scored = score_all(by_pin.get(pin, [])) if pin else []
        if len(town) >= 3 and (not scored or scored[0][0] < 0.8):
            grams = [town[k:k + 3] for k in range(len(town) - 2)]
            hits: Dict[int, int] = defaultdict(int)
            pool = {}
            for g in grams:
                for r in by_gram.get(g, []):
                    hits[id(r)] += 1
                    pool[id(r)] = r
            wider = [pool[key] for key, n in hits.items() if n >= max(1, len(grams) - 1) and not (pin and pool[key]["pincode"] == pin)]
            scored = sorted(scored + score_all(wider), key=lambda x: -x[0])
        link = {"temple_id": rec["temple_id"], "tid": "", "hrce_no": "", "confidence": "none", "score": "",
                "pincode_match": "", "name_ta": rec.get("name_ta") or "", "town_ta": rec.get("town_ta") or "",
                "register_name": "", "register_place": "", "runner_up": ""}
        if scored:
            score, same_pin, row = scored[0]
            second = scored[1][0] if len(scored) > 1 else 0.0
            if score >= 0.86 and score - second >= 0.06 and (same_pin or not pin):
                confidence = "exact"
            elif score >= 0.72 and score - second >= 0.03:
                confidence = "likely"
            else:
                confidence = "none"
            link.update({"score": score, "pincode_match": "yes" if same_pin else "no", "register_name": row["name"],
                         "register_place": ", ".join(row["places"]), "runner_up": second, "confidence": confidence})
            if confidence != "none":
                link.update({"tid": row["tid"], "hrce_no": row["tm"]})
        links.append(link)
    return links


def stage_link(pdf_path: Path, output_dir: Optional[Path] = None) -> Dict[str, int]:
    """Read the register, save it repaired, and write output/hrce_links.csv for every record in temples.jsonl."""
    out = output_dir or settings.output_dir
    register = read_register(pdf_path)
    with (out / "hrce_register.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hrce_no", "tid", "name", "place", "pincode", "district_and_office", "page"])
        for r in register:
            w.writerow([r["tm"], r["tid"], r["name"], ", ".join(r["places"]), r["pincode"], repair(r["rest"]), r["page"]])
    with (out / "temples.jsonl").open(encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    links = link_records(records, register)
    with (out / "hrce_links.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LINK_COLUMNS)
        w.writeheader()
        w.writerows(links)
    stats = {"register": len(register), "records": len(records)}
    for level in ("exact", "likely", "none"):
        stats[level] = sum(l["confidence"] == level for l in links)
    return stats
