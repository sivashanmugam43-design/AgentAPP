"""translate.py tests with a fake model (no torch / model download needed)."""

import json

import pytest

import translate as tr


class FakeModel:
    name = "fake"

    def __init__(self):
        self.batches = []

    def count_tokens(self, text):
        return len(text.split())  # one "token" per word

    def translate(self, sentences):
        self.batches.append(list(sentences))
        return [f"<{s}>" for s in sentences]


@pytest.fixture
def glossary(tmp_path):
    path = tmp_path / "glossary.json"
    path.write_text(json.dumps({"pre": {"மயிலாப்பூர்": "Mylapore"}, "post": {r"\bTemplee\b": "Temple"}}),
                    encoding="utf-8")
    return tr.load_glossary(path)


def make(tmp_path, glossary, batch_size=4):
    model = FakeModel()
    return tr.FieldTranslator(model, tr.Cache(tmp_path / "cache.jsonl"), glossary, batch_size), model


def test_glossary_defaults_merge_with_file(glossary):
    assert glossary["pre"] == {"அருள்மிகு": "Arulmigu", "திருக்கோயில்": "Temple", "மயிலாப்பூர்": "Mylapore"}
    assert tr.apply_pre("அருள்மிகு கபாலீஸ்வரர் திருக்கோயில்", glossary) == "Arulmigu கபாலீஸ்வரர் Temple"
    assert tr.apply_post("Sri Templee", glossary) == "Sri Temple"


def test_split_sentences_on_punctuation_and_keeps_abbreviations_together():
    assert tr.split_sentences("முதல் வாக்கியம் இது. இரண்டாம் வாக்கியம் இது? மூன்றாம் வாக்கியம் இது।") == [
        "முதல் வாக்கியம் இது.", "இரண்டாம் வாக்கியம் இது?", "மூன்றாம் வாக்கியம் இது।"]
    # "10 கி.மீ." is a short fragment and stays with the rest of its sentence; "12.30" never splits
    assert tr.split_sentences("சென்னையிலிருந்து 10 கி.மீ. தொலைவில் உள்ளது, காலை 12.30 மணி") == [
        "சென்னையிலிருந்து 10 கி.மீ. தொலைவில் உள்ளது, காலை 12.30 மணி"]


def test_split_long_respects_token_limit():
    sentence = ", ".join(" ".join(["சொல்"] * 30) for _ in range(10))  # 300 "tokens"
    pieces = tr.split_long(sentence, lambda s: len(s.split()), max_tokens=100)
    assert len(pieces) > 1 and all(len(p.split()) <= 100 for p in pieces)


def test_lines_rejoined_and_non_tamil_lines_copied(tmp_path, glossary):
    ft, model = make(tmp_path, glossary)
    text = "நிர்வாக அதிகாரி, அருள்மிகு கபாலீஸ்வரர் திருக்கோயில்.\n+91- 44 - 2464 1670.\n\nமயிலாப்பூர் கோயில்."
    [out] = ft.translate_texts([text])
    assert out == ("<நிர்வாக அதிகாரி, Arulmigu கபாலீஸ்வரர் Temple.>\n+91- 44 - 2464 1670.\n\n"
                   "<Mylapore கோயில்.>")


def test_batches_dedupe_and_cache_across_runs(tmp_path, glossary):
    ft, model = make(tmp_path, glossary, batch_size=2)
    texts = ["ஒன்று இரண்டு மூன்று.", "நான்கு ஐந்து ஆறு.", "ஒன்று இரண்டு மூன்று.", "ஏழு எட்டு ஒன்பது."]
    first = ft.translate_texts(texts)
    assert [len(b) for b in model.batches] == [2, 1]  # 3 unique sentences in batches of 2
    ft2, model2 = make(tmp_path, glossary)  # fresh run, same cache file
    assert ft2.translate_texts(texts) == first and model2.batches == []


def test_translate_records_fills_only_missing_and_marks_machine(tmp_path, glossary):
    rec = {"temple_id": "1", "district_id": "46",
           "name_ta": "அருள்மிகு ராமர் திருக்கோயில்", "name_en": "", "name_source_en": "",
           "moolavar_ta": "ராமர்", "moolavar_en": "Rama", "moolavar_source_en": "site",
           "urchavar_ta": "", "urchavar_en": "", "urchavar_source_en": "",
           "nearby_ta": ["ராமர்"]}
    assert tr.missing_fields(rec) == ["name"]
    ft, _ = make(tmp_path, glossary)
    saved = []
    stats = tr.translate_records([rec], [rec], ft, checkpoint_every=50, save=lambda r: saved.append(1))
    assert (rec["name_en"], rec["name_source_en"]) == ("<Arulmigu ராமர் Temple>", "machine")
    assert (rec["moolavar_en"], rec["moolavar_source_en"]) == ("Rama", "site")
    assert (rec["urchavar_en"], rec["urchavar_source_en"]) == ("", "")
    assert stats == {"temples": 1, "fields": 1} and saved == [1]


def test_cache_survives_a_cut_last_line(tmp_path):
    path = tmp_path / "c.jsonl"
    path.write_text('{"h": "a", "en": "x"}\n{"h": "b", "en', encoding="utf-8")
    assert tr.Cache(path).data == {"a": "x"}
