"""Configuration settings for AgentAPP (temple.dinamalar.com district temple scraper)."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

# Base Project Root
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")


# --- Field labels -------------------------------------------------------------------------------
# Labels as printed on the Tamil (new.php) and English (en/new_en.php) detail pages, verified
# against live pages on 2026-10-09 (ids 628, 1579, 2363). Labels are matched after normalize_label()
# (whitespace and ':' removed, lowercased). A label not listed here is kept under extra_ta / extra_en.

# Key / value table at the top of the "விபரம்" (Details) tab
KV_LABELS: Dict[str, str] = {
    "மூலவர்": "moolavar", "moolavar": "moolavar",
    "உற்சவர்": "urchavar", "urchavar": "urchavar",
    "அம்மன்/தாயார்": "amman", "amman/thayar": "amman",
    "தலவிருட்சம்": "sthala_vriksham", "thalavirutcham": "sthala_vriksham",
    "தீர்த்தம்": "theertham", "theertham": "theertham",
    "ஆகமம்/பூஜை": "agamam", "agamam/pooja": "agamam",
    "பழமை": "age", "oldyear": "age",
    "புராணபெயர்": "old_name", "historicalname": "old_name",
    "ஊர்": "town", "city": "town",
    "மாவட்டம்": "district", "district": "district",
    "மாநிலம்": "state", "state": "state",
}

# Headed sections of the Details tab (a header row with the l.gif/r.gif ornaments, then a text cell)
SECTION_LABELS: Dict[str, str] = {
    "பாடியவர்கள்": "singers", "singers": "singers",
    "திருவிழா": "festivals", "festival": "festivals",
    "தலசிறப்பு": "speciality", "temple'sspeciality": "speciality",
    "திறக்கும்நேரம்": "timings", "openingtime": "timings",
    "முகவரி": "address", "address": "address",
    "போன்": "phone", "phone": "phone",
    "பொதுதகவல்": "general_info", "generalinformation": "general_info",
    "பிரார்த்தனை": "prayers", "prayers": "prayers",
    "நேர்த்திக்கடன்": "thanksgiving", "thanksgiving": "thanksgiving",
    "தலபெருமை": "greatness", "greatnessoftemple": "greatness",
    "தலவரலாறு": "history", "templehistory": "history",
    "சிறப்பம்சம்": "special_features", "specialfeatures": "special_features",
}

# "செல்லும் வழி" (How to reach) tab
ROUTE_LABELS: Dict[str, str] = {
    "இருப்பிடம்": "location", "location": "location",
    "அருகிலுள்ளரயில்நிலையம்": "railway", "nearbyrailwaystation": "railway",
    "அருகிலுள்ளவிமானநிலையம்": "airport", "nearbyairport": "airport",
    "தங்கும்வசதி": "accommodation", "accomodation": "accommodation", "accommodation": "accommodation",
}

# Every text field stored as <field>_ta, <field>_en and <field>_source_en, in export column order
TEXT_FIELDS: List[str] = [
    "name", "category",
    "moolavar", "urchavar", "amman", "sthala_vriksham", "theertham", "agamam", "age", "old_name",
    "town", "district", "state",
    "singers", "festivals", "speciality", "timings", "address", "phone", "general_info",
    "prayers", "thanksgiving", "greatness", "history", "special_features",
    "location", "railway", "airport", "accommodation",
]


@dataclass
class Settings:
    """Global configuration settings for AgentAPP."""
    # Site
    base_url: str = os.getenv("SITE_BASE_URL", "https://temple.dinamalar.com")
    image_base_url: str = "https://imgtemple.dinamalar.com/kovilimages"

    # Politeness: each of the (at most) `concurrency` request slots waits a random
    # delay_min..delay_max seconds after every request before it sends the next one.
    concurrency: int = min(3, int(os.getenv("CONCURRENCY", "3")))
    delay_min: float = float(os.getenv("DELAY_MIN", "1.0"))
    delay_max: float = float(os.getenv("DELAY_MAX", "2.0"))
    max_attempts: int = int(os.getenv("MAX_ATTEMPTS", "5"))
    backoff_base: float = float(os.getenv("BACKOFF_BASE", "2.0"))  # seconds; doubles per attempt
    timeout: float = float(os.getenv("HTTP_TIMEOUT", "30"))
    user_agent: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    )

    # Machine translation of fields the site has no English for (key: ANTHROPIC_API_KEY)
    translate_model: str = os.getenv("TRANSLATE_MODEL", "claude-haiku-4-5")
    translate_chunk_chars: int = int(os.getenv("TRANSLATE_CHUNK_CHARS", "1000"))

    # Storage
    output_dir: Path = BASE_DIR / os.getenv("OUTPUT_DIR", "output")
    progress_dir: Path = BASE_DIR / "data" / "progress"
    cache_dir: Path = BASE_DIR / "data" / "cache"
    logs_dir: Path = BASE_DIR / "logs"

    glossary: Dict[str, str] = field(default_factory=lambda: {
        "அருள்மிகு": "Arulmigu",
        "திருக்கோயில்": "Temple",
    })

    # URLs
    @property
    def districts_url(self) -> str:
        return f"{self.base_url}/district_temple_list.php"

    def district_url(self, district_id: str, page: int = 1) -> str:
        url = f"{self.base_url}/district_temple.php?id={district_id}"
        return url if page == 1 else f"{url}&Page={page}"

    def temple_url(self, temple_id: str) -> str:
        return f"{self.base_url}/new.php?id={temple_id}"

    def temple_url_en(self, temple_id: str) -> str:
        return f"{self.base_url}/en/new_en.php?id={temple_id}"

    def ensure_directories(self):
        """Ensure runtime directories exist."""
        for d in (self.output_dir, self.progress_dir, self.cache_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


# Singleton settings instance
settings = Settings()
settings.ensure_directories()
