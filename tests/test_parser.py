"""Parser tests against real pages saved from temple.dinamalar.com on 2026-10-09.
The pages aren't committed (Dinamalar's copyright): run tests/fixtures/fetch_fixtures.py first."""

from pathlib import Path

import pytest

from src.temples.parser import (normalize_label, parse_district_page, parse_districts, parse_list_page,
                                parse_sub_lists, parse_temple)

FIX = Path(__file__).parent / "fixtures"
IMG = "https://imgtemple.dinamalar.com/kovilimages"


def read(name: str) -> str:
    path = FIX / name
    if not path.exists():
        pytest.skip(f"{name} missing; run tests/fixtures/fetch_fixtures.py")
    return path.read_bytes().decode("utf-8")


def test_normalize_label():
    assert normalize_label(" தல விருட்சம் :") == "தலவிருட்சம்"
    assert normalize_label("Agamam / Pooja") == "agamam/pooja"
    assert normalize_label("Near By Railway Station  :") == "nearbyrailwaystation"


def test_districts():
    districts = parse_districts(read("districts.html"))
    assert len(districts) == 33
    assert {"district_id": "46", "district_name": "சென்னை"} in districts
    assert districts[0] == {"district_id": "622", "district_name": "அரியலூர்"}


def test_district_pages_and_next_link():
    temples, has_next = parse_district_page(read("district_46_p1.html"))
    assert has_next and len(temples) == 50
    assert temples[0] == {"temple_id": "11", "temple_name": "அருள்மிகு அஷ்டலட்சுமி திருக்கோயில், பெசன்ட் நகர், சென்னை"}
    temples2, has_next2 = parse_district_page(read("district_46_p2.html"))
    assert not has_next2 and len(temples2) == 30
    assert not {t["temple_id"] for t in temples} & {t["temple_id"] for t in temples2}


def test_tamil_temple_page():
    t = parse_temple(read("temple_628_ta.html"), "ta", IMG)
    assert t["found"] and t["has_english_page"]
    assert t["name"] == "அருள்மிகு கபாலீஸ்வரர் திருக்கோயில்"
    assert (t["moolavar"], t["amman"], t["sthala_vriksham"]) == ("கபாலீசுவரர்", "கற்பகாம்பாள்", "புன்னை மரம்")
    assert (t["agamam"], t["town"], t["district"], t["state"]) == ("காமீகம்", "மயிலாப்பூர்", "சென்னை", "தமிழ்நாடு")
    assert t["timings"].startswith("காலை 5 மணி முதல் 12.30 மணி வரை")
    assert t["address"] == "நிர்வாக அதிகாரி,\nஅருள்மிகு கபாலீஸ்வரர் திருக்கோயில்,\nமயிலாப்பூர்,\nசென்னை - 600 004."
    assert t["phone"] == "+91- 44 - 2464 1670."
    assert t["singers"].startswith("திருஞான சம்பந்தர், திருநாவுக்கரசர், சுந்தரர்")
    for key in ("festivals", "speciality", "general_info", "prayers", "thanksgiving", "greatness", "history"):
        assert len(t[key]) > 40, key
    assert t["special_features"].startswith("அதிசயத்தின் அடிப்படையில்: இங்கு சிவன்")
    assert (t["category"], t["category_id"]) == ("274 சிவாலயங்கள்", "7")
    assert (t["railway"], t["airport"]) == ("எக்மோர், மயிலாப்பூர்", "மீனம்பாக்கம், சென்னை")
    assert t["location"] and t["accommodation"].startswith("சென்னை")
    assert (t["latitude"], t["longitude"]) == ("13.033712608281427", "80.26977831871136")
    assert t["main_image"] == f"{IMG}/T_500_628.jpg"
    assert len(t["gallery"]) == 9
    assert t["gallery"][0] == {"photo": "G_L1_628.jpg", "url": f"{IMG}/GalleryLarge/G_L1_628.jpg",
                               "thumb": f"{IMG}/GalleryThumb/G_T1_628.jpg", "caption": "அம்மன் கற்பகாம்பாள்"}
    assert t["nearby"][:2] == ["கபாலீஸ்வரர்", "அஷ்டலட்சுமி"]
    assert t["extra"] == {}


def test_english_temple_page_same_fields():
    t = parse_temple(read("temple_628_en.html"), "en", IMG)
    assert t["found"]
    assert (t["name"], t["moolavar"], t["town"], t["district"]) == (
        "Sri Kapaleeswarar temple", "Kapaleeswarar", "Mylapore", "Chennai")
    assert t["urchavar"] == ""  # '-' on the site
    assert t["age"] == "1000-2000 years old"
    assert t["timings"] == "The temple is open from 5.00 a.m. to 12.30 p.m. and from 4.00 p.m. to 9.30 p.m."
    assert t["history"].startswith("Mother Uma wanted to know")
    assert t["special_features"] == "Miracle Based: Lord Shiva in the temple is Swayambumurthi."
    assert t["railway"] == "Chennai Central, Egmore."
    assert t["gallery"][0]["caption"] == "Amman Karpagambal"
    assert t["extra"] == {}


def test_english_zero_placeholders_dropped():
    html = """<div class="TabbedPanelsContent"><span class="topic">Sri X temple</span>
      <table><tr><td><img src="//s/images/l.gif"></td><td><span class="subhead">Special Features:</span></td></tr>
      <tr><td class="newsdetails"><span class="subhead">Miracle Based:</span> <span class="newsdetails">0</span>
      <span class="subhead">Scientific Based:</span> <span class="newsdetails">0</span></td></tr></table></div>"""
    assert parse_temple(html, "en", IMG)["special_features"] == ""


def test_temple_without_english_page():
    ta = parse_temple(read("temple_2363_ta.html"), "ta", IMG)
    assert ta["found"] and not ta["has_english_page"]
    assert ta["urchavar"] == "கஜேந்திர வரதராஜ பெருமாள்"
    # The English URL still answers 200, with a placeholder template
    assert not parse_temple(read("temple_2363_en.html"), "en", IMG)["found"]


def test_unknown_temple_id():
    assert not parse_temple(read("temple_missing_ta.html"), "ta", IMG)["found"]


def test_list_page_link_forms_numbering_and_next():
    html = """<a href="new.php?id=314">1. திருவானைக்கா  ஜம்புகேஸ்வரர் திருக்கோயில்</a>
              <a href="new.php?cat=1&id=1072">2. அருள்மிகு\xa0\xa0சுப்பிரமணிய சுவாமி</a>
              <a href="download.php?id=906">ராமநாதர், ராமநாதபுரம்</a>
              <a href="new.php?id=498"><img src="x.jpg"></a>
              <a href="ayyappatharisanam_new.php?id=5">not a temple</a>
              <a href="news_detail.php?id=7">news</a>
              <a href="koillist.php?cat=7&Page=2">2</a><a href="koillist.php?cat=7&Page=2">Next &gt;&gt;</a>"""
    temples, next_href = parse_list_page(html)
    assert temples == [
        {"temple_id": "314", "temple_name": "திருவானைக்கா ஜம்புகேஸ்வரர் திருக்கோயில்"},
        {"temple_id": "1072", "temple_name": "அருள்மிகு சுப்பிரமணிய சுவாமி"},
        {"temple_id": "906", "temple_name": "ராமநாதர், ராமநாதபுரம்"},
        {"temple_id": "498", "temple_name": ""},
    ]
    assert next_href == "koillist.php?cat=7&Page=2"
    assert parse_list_page('<a href="new.php?id=1">அ</a>')[1] is None


def test_sub_lists_of_a_hub_page():
    html = """<a href="cholar_temple.php?cat=534&dt=5">சித்தூர்</a><a href="cholar_dist.php">menu</a>
              <a href="cholar_temple.php?cat=534&dt=46">சென்னை</a><a href="cholar_temple.php?cat=534&dt=5">again</a>"""
    assert parse_sub_lists(html, "cholar_temple.php?") == ["cholar_temple.php?cat=534&dt=5",
                                                           "cholar_temple.php?cat=534&dt=46"]
