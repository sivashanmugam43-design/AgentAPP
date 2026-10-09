"""Download the site pages the parser tests run against (kept out of git: Dinamalar's copyright).

    python tests/fixtures/fetch_fixtures.py
"""

import time
from pathlib import Path

import httpx

BASE = "https://temple.dinamalar.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
PAGES = {
    "districts.html": "/district_temple_list.php",
    "district_46_p1.html": "/district_temple.php?id=46",
    "district_46_p2.html": "/district_temple.php?id=46&Page=2",
    "temple_628_ta.html": "/new.php?id=628",          # Kapaleeswarar: has an English page
    "temple_628_en.html": "/en/new_en.php?id=628",
    "temple_2363_ta.html": "/new.php?id=2363",        # no English page
    "temple_2363_en.html": "/en/new_en.php?id=2363",  # ...so this is the empty English template
    "temple_missing_ta.html": "/new.php?id=99999999", # unknown id: HTTP 200, empty template
}

if __name__ == "__main__":
    here = Path(__file__).parent
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        for name, path in PAGES.items():
            r = client.get(BASE + path)
            r.raise_for_status()
            (here / name).write_bytes(r.content)
            print(f"{name}: {len(r.content):,} bytes")
            time.sleep(1.5)
