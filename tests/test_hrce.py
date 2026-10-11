"""HR&CE pages: parsing the title, the history text and the speciality table (markup as on the live pages, 2026-10-11)."""
import asyncio

from src.temples import hrce

HISTORY = """<html><head><title>Arulmigu Arunachaleswarar Temple, Tiruvannamalai - 606601, Tiruvannamalai District [TM020343].,Annamalaiyar</title>
<script>function paragtraphevent(id){ if($(".read_"+id).text()=="மேலும்.."){} }</script></head><body>
<div class="container-fluid history-con col-pad-lr-0"><p id="span_subhead"><b><u>தல வரலாறு</u></b></p>
<div class="thumbnails"><img src="x.jpeg"/></div>
<p class="pgh_text"><span class=readless_1>இத்திருத்தலத்தின் சிறப்புகள்   அருணாச்சல புராணம்...</span>
<span id="1" style="display:none">என்ற நூலில் விரிவாக காணலாம். பிரம்மன் அன்னப் பறவையாக உருவெடுத்தார்.</span>
<a class="read_1" onclick="paragtraphevent(1)">மேலும்..</a></p></div></body></html>"""

SPECIALITY = """<html><head><title>X [TM020343].</title></head><body><table>
<tr><th>வரிசை எண்</th><th>திருத்தல சிறப்பு</th><th>தலைப்பு</th><th>விவரம்</th></tr>
<tr><td align="center">1</td><td>புராதனம்</td><td>நால்வர்</td><td><button>காண்க</button></td></tr>
<tr><td align="center">3</td><td>தல விருட்சம்</td><td>மகிழமரம்</td><td><button>காண்க</button></td></tr>
</table></body></html>"""


def test_title_gives_the_name_and_the_number():
    t = hrce.parse_title(HISTORY)
    assert t == {"hrce_title": "Arulmigu Arunachaleswarar Temple, Tiruvannamalai - 606601, Tiruvannamalai District",
                 "hrce_title_ta": "", "hrce_no": "TM020343"}
    head = "<html><title>X [TM000001].</title><body><span>அருள்மிகு கபாலீசுவரர் திருக்கோயில், மயிலாப்பூர் - 600004, சென்னை மாவட்டம்.</span></body></html>"
    assert hrce.parse_title(head)["hrce_title_ta"] == "அருள்மிகு கபாலீசுவரர் திருக்கோயில், மயிலாப்பூர் - 600004, சென்னை மாவட்டம்"
    assert hrce.parse_title("<html><title>HR&CE</title></html>")["hrce_no"] == ""


def test_history_keeps_the_hidden_rest_and_drops_the_more_link():
    text = hrce.parse_history(HISTORY)
    assert text.startswith("இத்திருத்தலத்தின் சிறப்புகள் அருணாச்சல புராணம்")
    assert "பிரம்மன் அன்னப் பறவையாக உருவெடுத்தார்." in text and "மேலும்" not in text and "தல வரலாறு" not in text
    assert hrce.parse_history("<html><body>nothing</body></html>") == ""


def test_speciality_rows():
    assert hrce.parse_speciality(SPECIALITY) == [{"kind": "புராதனம்", "heading": "நால்வர்"},
                                                 {"kind": "தல விருட்சம்", "heading": "மகிழமரம்"}]


def test_the_stage_reads_linked_temples_once(tmp_path):
    store = hrce.HrceStore(tmp_path)
    store.links_path.write_text("temple_id,tid,confidence\nT0001,20343,exact\nT0002,,none\n", encoding="utf-8")
    asked = []

    class Client:
        async def get_text(self, url):
            asked.append(url)
            return HISTORY if "history" in url else SPECIALITY

    stats = asyncio.run(hrce.stage_hrce(Client(), store))
    assert stats == {"read": 1, "failed": 0, "skipped": 0} and len(asked) == 2 and asked[0].endswith("history.php?tid=20343")
    record = store.load()[0]
    assert record["temple_id"] == "T0001" and record["hrce_no"] == "TM020343" and len(record["speciality"]) == 2
    again = asyncio.run(hrce.stage_hrce(Client(), store))          # nothing is fetched twice
    assert again == {"read": 0, "failed": 0, "skipped": 1} and len(asked) == 2
