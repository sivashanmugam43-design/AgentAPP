"""Parsers for temple.dinamalar.com: the district list, temple lists (district and menu category),
and a temple page.

HTML structure verified against live pages on 2026-10-09 (see tests/fixtures/fetch_fixtures.py).
All pages are server-rendered; nothing here needs JavaScript.

A temple page (Tamil new.php or English en/new_en.php, same layout) is a set of tabs, each a
div.TabbedPanelsContent:
  0 Details      - name (first span.topic), key/value table (td.style8 label, td.style5 value),
                   then headed sections: a header row carrying the l.gif ornament followed by a
                   td.newsdetails text cell (sometimes in the next table, so we walk document order)
  1 How to reach - span.subhead label followed by a span.newsdetails value
  2 Map          - hidden inputs #hfLat / #hfLan
  3 Photos       - popupimage.php?Photo=G_L<n>_<id>.jpg links, captions in the row below
  4 Nearby       - Tamil: li items (names only); English: new_en.php?id= links
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from config.settings import KV_LABELS, ROUTE_LABELS, SECTION_LABELS

_ID_RE = re.compile(r"[?&]id=(\d+)")
# A temple link on a list page: new.php?id=N, new.php?cat=1&id=N, or download.php?id=N (same ids)
_TEMPLE_HREF_RE = re.compile(r"(?:^|/)(?:new|download)\.php\?(?:[^#]*&)?id=(\d+)")
_PHOTO_RE = re.compile(r"Photo=([\w.]+)")


def normalize_label(text: str) -> str:
    """'  தல விருட்சம் :' -> 'தலவிருட்சம்', 'Agamam / Pooja' -> 'agamam/pooja'."""
    return re.sub(r"[\s:\xa0]+", "", text or "").lower()


def clean_text(node: Optional[Tag]) -> str:
    """Visible text of a node with <br>/<p> kept as line breaks. '-' (the site's 'none') -> ''."""
    if node is None:
        return ""
    node = BeautifulSoup(str(node), "lxml")  # work on a copy; the caller's tree stays intact
    for t in node(["script", "style"]):
        t.decompose()
    for br in node.find_all("br"):
        br.replace_with("\n")
    for p in node.find_all("p"):
        p.append("\n")
    text = node.get_text("").replace("\xa0", " ").replace("\r", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return "" if text in {"-", "--", "–", "—", "."} else text


def _id_of(href: str) -> Optional[str]:
    m = _ID_RE.search(href or "")
    return m.group(1) if m else None


# --- Listing pages --------------------------------------------------------------------------------

def parse_districts(html: str) -> List[Dict[str, str]]:
    """District list page -> [{district_id, district_name}], in page order, deduped."""
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.select('a[href*="district_temple.php?id="]'):
        did, name = _id_of(a["href"]), a.get_text(" ", strip=True)
        if did and name and did not in seen:
            seen.add(did)
            out.append({"district_id": did, "district_name": name})
    return out


def parse_list_page(html: str) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """One page of a temple list -> ([{temple_id, temple_name}], href of the "Next >>" page or None).
    Names lose the list numbering ("12. "); a temple linked only by its photo has an empty name."""
    soup = BeautifulSoup(html, "lxml")
    temples: Dict[str, Dict[str, str]] = {}
    for a in soup.find_all("a", href=True):
        m = _TEMPLE_HREF_RE.search(a["href"])
        if not m:
            continue
        name = re.sub(r"^\d+\.\s*", "", re.sub(r"\s+", " ", a.get_text(" ", strip=True))).strip()
        if m.group(1) not in temples or (name and not temples[m.group(1)]["temple_name"]):
            temples[m.group(1)] = {"temple_id": m.group(1), "temple_name": name}
    next_href = next((a["href"] for a in soup.find_all("a", href=True)
                      if "Next" in a.get_text() and "Page=" in a["href"]), None)
    return list(temples.values()), next_href


def parse_district_page(html: str) -> Tuple[List[Dict[str, str]], bool]:
    """One page of a district's temple list -> ([{temple_id, temple_name}], has_next_page)."""
    temples, next_href = parse_list_page(html)
    return [t for t in temples if t["temple_name"]], next_href is not None


def parse_sub_lists(html: str, marker: str) -> List[str]:
    """A hub page (one list per city or district) -> hrefs of its lists, in page order, deduped."""
    soup = BeautifulSoup(html, "lxml")
    return list(dict.fromkeys(a["href"] for a in soup.find_all("a", href=True) if marker in a["href"]))


# --- Temple page ----------------------------------------------------------------------------------

def _is_section_header(tr: Tag) -> bool:
    """A header row carries the l.gif ornament itself (rows that merely wrap a nested table don't count)."""
    return tr.find("table") is None and tr.find("img", src=re.compile(r"/l\.gif$")) is not None


def _parse_special_features(td: Tag) -> str:
    """The Special Features cell holds sub-sections (span.subhead label + text); join as 'label: text'."""
    parts = []
    for sub in td.select("span.subhead"):
        value = sub.find_next_sibling("span")
        text = clean_text(value)
        if text and text != "0":  # English pages print "0" for an empty sub-section
            parts.append(f"{sub.get_text(' ', strip=True).rstrip(': ')}: {text}")
    return "\n".join(parts) if td.select("span.subhead") else clean_text(td)


def _parse_details_tab(panel: Tag, lang: str, out: Dict[str, Any], extra: Dict[str, str]) -> None:
    topic = panel.select_one("span.topic")
    out["name"] = clean_text(topic)

    for label_td in panel.select("td.style8"):
        cells = label_td.find_next_siblings("td")
        if len(cells) < 2:
            continue
        label, value = label_td.get_text(" ", strip=True), clean_text(cells[1])
        key = KV_LABELS.get(normalize_label(label))
        if key:
            out[key] = value
        elif value:
            extra[label] = value

    # Walk headers and text cells in document order; each text cell belongs to the latest header.
    current: Optional[str] = None
    for el in panel.find_all(["tr", "td"]):
        if el.name == "tr" and _is_section_header(el):
            current = el.get_text(" ", strip=True)
        elif el.name == "td" and "newsdetails" in (el.get("class") or []) and current:
            if el.find_parent("td", class_="newsdetails"):
                continue  # nested cell; its parent was already taken
            key = SECTION_LABELS.get(normalize_label(current))
            text = _parse_special_features(el) if key == "special_features" else clean_text(el)
            if key:
                out[key] = "\n".join(filter(None, [out.get(key, ""), text]))
            elif text:
                extra[current.rstrip(": ")] = text
            current = None

    # Category: the "« 274 Shivalayas home" style link under the sections, when present
    cat = panel.select_one('a[href*="koillist"][href*="cat="]')
    if cat:
        out["category"] = re.sub(r"^[«\s]+|\s*(முதல் பக்கம்|Home|home)\s*$", "",
                                 cat.get_text(" ", strip=True)).strip()
        out["category_id"] = parse_qs(urlparse(cat["href"]).query).get("cat", [""])[0]

    img = panel.select_one('img[alt="[Image1]"]') or panel.select_one("a#Image1 img")
    out["main_image"] = img.get("src", "") if img else ""
    out["has_english_page"] = panel.select_one('a[href*="new_en.php?id="]') is not None


def _parse_route_tab(panel: Tag, out: Dict[str, Any], extra: Dict[str, str]) -> None:
    for sub in panel.select("span.subhead"):
        label = sub.get_text(" ", strip=True)
        text = clean_text(sub.find_next_sibling("span", class_="newsdetails"))
        key = ROUTE_LABELS.get(normalize_label(label))
        if key:
            out[key] = text
        elif text:
            extra[label.rstrip(": ")] = text


def _parse_gallery(soup: BeautifulSoup, image_base_url: str) -> List[Dict[str, str]]:
    """[{photo, url, thumb, caption}] - caption sits in the same column of the next row."""
    photos = []
    for a in soup.select('a[href*="popupimage.php?Photo=G_"]'):
        m = _PHOTO_RE.search(a["href"])
        td = a.find_parent("td")
        if not m or td is None:
            continue
        caption = ""
        tr = td.find_parent("tr")
        caption_tr = tr.find_next_sibling("tr") if tr else None
        if caption_tr:
            idx = tr.find_all("td", recursive=False).index(td)
            cells = caption_tr.find_all("td", recursive=False)
            caption = clean_text(cells[idx]) if idx < len(cells) else ""
        thumb = a.find("img")
        photos.append({
            "photo": m.group(1),
            "url": f"{image_base_url}/GalleryLarge/{m.group(1)}",
            "thumb": thumb.get("src", "") if thumb else "",
            "caption": caption,
        })
    return photos


def _parse_nearby(panel: Optional[Tag]) -> List[str]:
    if panel is None:
        return []
    names = [li.get_text(" ", strip=True) for li in panel.select("ul#selPlace li")]
    if not names:  # English layout: thumbnail + name links
        names = [a.get_text(" ", strip=True) for a in panel.select('a.newsdetails[href*="new_en.php?id="]')]
    return [n for n in names if n]


def parse_temple(html: str, lang: str, image_base_url: str) -> Dict[str, Any]:
    """Temple page (lang 'ta' or 'en') -> flat dict of the fields in config TEXT_FIELDS (those found),
    plus latitude, longitude, main_image, gallery, nearby, extra, has_english_page, found."""
    soup = BeautifulSoup(html, "lxml")
    panels = soup.select("div.TabbedPanelsContent")
    out: Dict[str, Any] = {}
    extra: Dict[str, str] = {}
    if panels:
        _parse_details_tab(panels[0], lang, out, extra)
    if len(panels) > 1:
        _parse_route_tab(panels[1], out, extra)
    out["nearby"] = _parse_nearby(panels[4] if len(panels) > 4 else None)
    out["gallery"] = _parse_gallery(soup, image_base_url)
    for key, sel in (("latitude", "#hfLat"), ("longitude", "#hfLan")):
        el = soup.select_one(sel)
        out[key] = (el.get("value") or "").strip() if el else ""
    out["extra"] = extra
    # An unknown id (or a temple with no English version) still returns HTTP 200 with an empty
    # template: name "அருள்மிகு திருக்கோயில்" / "Sri temple", and on English pages placeholder
    # District/State/Old year values. A real page always has a Moolavar or a town.
    out["found"] = bool(out.get("moolavar") or out.get("town"))
    return out
