"""The HR&CE register: repairing its scrambled Tamil, and linking records to it."""
from src.temples import hrce_register as hr

# scrambled text as the register PDF gives it -> what it prints
SAMPLES = {
    "அ௠ள்௘ஶ கபா௨ாவரர்ொ௠க்ேகா௜ல்": "அருள்மிகு கபாலீசுவரர்திருக்கோயில்",
    "ம௜லாப்ௗர்": "மயிலாப்பூர்",
    "ெசன்ைன": "சென்னை",
    "ொ௠வல்௧க்ேகணி": "திருவல்லிக்கேணி",
    "்த்ௌக்ஶூ": "தூத்துக்குடி",
    "ஆலங்ஶூ": "ஆலங்குடி",
    "நாகநாதாவா௘": "நாகநாத சுவாமி",
    "ொ௠ெவண் கா௄": "திருவெண்காடு",
    "ம௜லா௄ௌைற": "மயிலாடுதுறை",
    "ொெரௗபொயம்மன்": "திரௌபதியம்மன்",
    "௖ௌக்ேகாடை் ட": "புதுக்கோட்டை",
    "஽ரக் ா௯": "சீர்காழி",
    "ேசஷ௖ரஸீ ் வரர்": "சேஷபுரீஸ்வரர்",
    "ாந்தேரஸ் வரர்": "சுந்தரேஸ்வரர்",
    "தஞ்சா௶ர்": "தஞ்சாவூர்",
}


def test_repair_restores_the_registers_tamil():
    for scrambled, printed in SAMPLES.items():
        assert hr.repair(scrambled) == printed, scrambled


def test_skeleton_drops_stock_words_and_vowel_signs():
    assert hr.skeleton("அருள்மிகு நாகநாத சுவாமி திருக்கோயில்") == hr.skeleton("நாகநாத") == "நகநத"
    assert hr.skeleton("கீழப்பெரும்பள்ளம்") == "ககபபரமபளளம"          # ழ is read as க
    assert hr.latin_skeleton("Thirunageswaram") == "trngswrm"


def _row(tid, name, places, pincode):
    return {"tm": f"TM{tid:06d}", "tid": tid, "name": name, "places": places, "places_raw": places, "pincode": pincode}


def _rec(temple_id, name, town, address, moolavar=""):
    return {"temple_id": temple_id, "name_ta": name, "town_ta": town, "town_en": "", "address_ta": address, "moolavar_ta": moolavar}


def test_linking_goes_by_pincode_then_name_and_refuses_a_tie():
    register = [
        _row(1, "அருள்மிகு நாகநாத சுவாமி திருக்கோயில்", ["திருநாகேஸ்வரம்"], "612204"),
        _row(2, "அருள்மிகு சந்தனமாரியம்மன் திருக்கோயில்", ["திருநாகேஸ்வரம்"], "612204"),
        _row(3, "அருள்மிகு மாரியம்மன் திருக்கோயில்", ["கரூர்"], "639001"),
        _row(4, "அருள்மிகு மாரியம்மன் திருக்கோயில்", ["கரூர்"], "639001"),
        _row(5, "அருள்மிகு பாபநாசநாதர் திருக்கோயில்", ["பாபநாசம்"], "627425"),
    ]
    records = [
        # the temple's name differs from the register's, but one of the deity's names is the same
        _rec("T1", "அருள்மிகு நாகேஸ்வரர் திருக்கோயில்", "திருநாகேஸ்வரம்", "திருநாகேஸ்வரம் - 612 204", "நாகேஸ்வரர், நாகநாதர்"),
        _rec("T2", "அருள்மிகு மாரியம்மன் திருக்கோயில்", "கரூர்", "கரூர் - 639 001"),          # two entries alike: no link
        _rec("T3", "அருள்மிகு பாபநாசநாதர் திருக்கோயில்", "பாபநாசம்", "பாபநாசம் - 627 551"),   # another pincode: by place
        _rec("T4", "அருள்மிகு காசி விஸ்வநாதர் திருக்கோயில்", "வாரணாசி", "வாரணாசி"),
    ]
    links = {l["temple_id"]: l for l in hr.link_records(records, register)}
    assert (links["T1"]["tid"], links["T1"]["confidence"], links["T1"]["pincode_match"]) == (1, "exact", "yes")
    assert (links["T2"]["tid"], links["T2"]["confidence"]) == ("", "none")
    assert (links["T3"]["tid"], links["T3"]["confidence"], links["T3"]["pincode_match"]) == (5, "likely", "no")
    assert (links["T4"]["tid"], links["T4"]["confidence"]) == ("", "none")
    assert hr.record_pincode(records[0]) == "612204" and hr.record_pincode(records[3]) == ""
