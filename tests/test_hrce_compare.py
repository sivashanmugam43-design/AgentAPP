"""HR&CE beside Dinamalar: confirming a link from the page's own title, and the theme columns."""
from src.temples import hrce_compare as hc

REC = {"temple_id": "T1", "name_ta": "அருள்மிகு நாகேஸ்வரர் திருக்கோயில்", "moolavar_ta": "நாகேஸ்வரர், நாகநாதர்",
       "town_ta": "திருநாகேஸ்வரம்", "town_en": "Tirunageswaram", "address_ta": "திருநாகேஸ்வரம் - 612 204",
       "prayers_ta": "திருமணத்தடை, குழந்தை பாக்கியம் வேண்டி பிரார்த்திக்கலாம். இத்தலம் ராகு தோஷ பரிகார தலம்."}
PAGE = {"temple_id": "T1", "hrce_no": "TM017999",
        "hrce_title_ta": "அருள்மிகு நாகநாத சுவாமி திருக்கோயில், திருநாகேஸ்வரம் - 612204, தஞ்சாவூர் மாவட்டம்",
        "history_ta": "முன்பொரு காலத்தில் செண்பகமரம் நிறைந்த இடமாக இருந்ததால் செண்பக வனம் என்று பெயர் பெற்றது. " * 2,
        "speciality": [{"kind": "பரிகாரம்", "heading": "அருள்மிகு இராகு பகவான்"}]}


def test_a_link_is_confirmed_by_the_pages_own_name_and_place():
    assert hc.check_link(REC, PAGE) == "confirmed"                       # the deity's other name, the same place
    other = {**PAGE, "hrce_title_ta": "அருள்மிகு சந்திரமொழீஸ்வரர் திருக்கோயில், மேலையூர் - 612204, தஞ்சாவூர் மாவட்டம்"}
    assert hc.check_link(REC, other) == "doubtful"                       # the same pincode alone is not enough
    english_place = {**PAGE, "hrce_title_ta": "அருள்மிகு நாகநாத சுவாமி திருக்கோயில், Thirunageswaram - 612204, தஞ்சாவூர் மாவட்டம்"}
    assert hc.check_link(REC, english_place) == "confirmed"
    assert hc.check_link(REC, {**PAGE, "hrce_title_ta": ""}) == "doubtful"


def test_themes_say_whether_hrce_names_what_dinamalar_names():
    row = hc.compare([REC], [PAGE], [{"temple_id": "T1", "confidence": "exact"}])[0]
    assert (row["link"], row["check"], row["hrce_has_text"]) == ("exact", "confirmed", "yes")
    assert row["hrce_pariharam"] == "அருள்மிகு இராகு பகவான்" and row["hrce_prayer"] == ""
    assert row["rahu_ketu_naga"] == "yes"            # named by both
    assert row["marriage"] == "no" and row["child_boon"] == "no"         # Dinamalar only
    assert row["sani"] == "" and row["pitru"] == ""                      # Dinamalar does not name them
    empty = hc.compare([REC], [{**PAGE, "history_ta": "", "speciality": []}], [])[0]
    assert empty["hrce_has_text"] == "no" and empty["rahu_ketu_naga"] == "?"
