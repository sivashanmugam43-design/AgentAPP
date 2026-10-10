"""Fill missing English fields in temples.jsonl with a free local translation model.

Self-contained (no imports from this repo), so it also runs on Google Colab with just this file,
glossary.json and temples.jsonl. For every text field with Tamil (<field>_ta) but no English
(<field>_en), it writes the translation to <field>_en and sets <field>_source_en = "machine".
English that came from the site (source_en "site") is never touched.

Models:
  indictrans2  ai4bharat/indictrans2-indic-en-dist-200M (+ IndicTransToolkit). Gated on Hugging Face:
               accept its terms on the model page, then set HF_TOKEN (or `huggingface-cli login`).
  nllb         facebook/nllb-200-distilled-600M (no login needed)
  auto         indictrans2, falling back to nllb if it can't be installed or loaded (default)

Text is split into sentences (on "।", ".", "?", "!" and line breaks; pieces over ~200 tokens are
split again at commas/spaces), translated in batches, and rejoined with the original line breaks.
Every sentence's translation is cached in a JSONL file keyed by the SHA-256 of its Tamil text, so a
rerun (or a Colab session that disconnected) skips finished work. temples.jsonl is rewritten every
--checkpoint-every temples and at the end.

    pip install -r requirements-translate.txt
    python translate.py                                   # output/temples.jsonl in place
    python translate.py --district 46 --limit 5           # test on 5 Chennai temples
    python translate.py --model nllb --batch-size 16
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

log = logging.getLogger("translate")

HERE = Path(__file__).resolve().parent
MODELS = {
    "indictrans2": "ai4bharat/indictrans2-indic-en-dist-200M",
    "nllb": "facebook/nllb-200-distilled-600M",
}
SRC_LANG, TGT_LANG = "tam_Taml", "eng_Latn"
MAX_TOKENS = 200          # per sentence piece sent to the model
MAX_NEW_TOKENS = 256      # per translated piece

TAMIL = re.compile(r"[஀-௿]")
SENTENCE_END = re.compile(r"(?<=[.?!।])\s+")
DEFAULT_GLOSSARY = {
    "pre": {"அருள்மிகு": "Arulmigu", "திருக்கோயில்": "Temple"},
    "post": {},
}


# --- Glossary ------------------------------------------------------------------------------------

def load_glossary(path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    """glossary.json: {"pre": {tamil: english}, "post": {regex: replacement}}.
    "pre" terms are swapped into the Tamil text before translation, so the model copies them as is.
    "post" rules are regexes applied to the English output (fix a model's spelling of a name)."""
    glossary = {k: dict(v) for k, v in DEFAULT_GLOSSARY.items()}
    if path and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for section in ("pre", "post"):
            glossary[section].update(data.get(section, {}))
    return glossary


def apply_pre(text: str, glossary) -> str:
    """Swap whole glossary words only: an inflected form (திருக்கோயிலில் = "in the temple") is left to
    the model. Longest terms first, so a phrase wins over a word inside it."""
    for ta in sorted(glossary["pre"], key=len, reverse=True):
        text = re.sub(rf"(?<![஀-௿]){re.escape(ta)}(?![஀-௿])", glossary["pre"][ta], text)
    return text


def apply_post(text: str, glossary) -> str:
    for pattern, replacement in glossary["post"].items():
        text = re.sub(pattern, replacement, text)
    return text


# --- Splitting -----------------------------------------------------------------------------------

def _ends_with_abbreviation(piece: str) -> bool:
    """'... 10 கி.மீ.' - a final word with a dot inside is an abbreviation, not a sentence end.
    (Length can't tell: real words like இது are as short as initials.)"""
    words = piece.split()
    return bool(words) and "." in words[-1].rstrip(".")


def split_sentences(line: str, min_chars: int = 15) -> List[str]:
    """One line -> sentences. Never splits after an abbreviation; fragments under min_chars are merged."""
    out: List[str] = []
    for part in SENTENCE_END.split(line.strip()):
        if out and (len(out[-1]) < min_chars or (out[-1].endswith(".") and _ends_with_abbreviation(out[-1]))):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return [s for s in out if s.strip()]


def split_long(sentence: str, count_tokens, max_tokens: int = MAX_TOKENS) -> List[str]:
    """Split a sentence over max_tokens at commas, then at spaces."""
    if count_tokens(sentence) <= max_tokens:
        return [sentence]
    for sep in (", ", " "):
        words = sentence.split(sep)
        if len(words) == 1:
            continue
        pieces, current = [], ""
        for w in words:
            candidate = f"{current}{sep}{w}" if current else w
            if current and count_tokens(candidate) > max_tokens:
                pieces.append(current)
                current = w
            else:
                current = candidate
        pieces.append(current)
        out: List[str] = []
        for p in pieces:
            out.extend(split_long(p, count_tokens, max_tokens) if count_tokens(p) > max_tokens else [p])
        return out
    return [sentence]  # one huge "word"; the model truncates it


# --- Cache ---------------------------------------------------------------------------------------

class Cache:
    """Append-only JSONL: {"h": sha256(tamil), "en": english, "m": model}."""

    def __init__(self, path: Path):
        self.path = path
        self.data: Dict[str, str] = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    self.data[row["h"]] = row["en"]
                except (ValueError, KeyError):
                    continue  # a line cut short by a crash / disconnect

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, text: str) -> Optional[str]:
        return self.data.get(self.key(text))

    def put_many(self, pairs: Iterable[Tuple[str, str]], model: str) -> None:
        lines = []
        for text, english in pairs:
            h = self.key(text)
            self.data[h] = english
            lines.append(json.dumps({"h": h, "en": english, "m": model}, ensure_ascii=False))
        if lines:
            with self.path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")


# --- Models --------------------------------------------------------------------------------------

def pick_device():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


class IndicTrans2:
    name = "indictrans2"

    def __init__(self, device: str, num_beams: int):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        try:
            from IndicTransToolkit.processor import IndicProcessor
        except ImportError:
            from IndicTransToolkit import IndicProcessor
        model_id = MODELS[self.name]
        self.torch, self.device, self.num_beams = torch, device, num_beams
        self.use_cache = True
        self.ip = IndicProcessor(inference=True)
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_id, trust_remote_code=True,
            dtype=torch.float16 if device == "cuda" else torch.float32,
        ).to(device).eval()

    def count_tokens(self, text: str) -> int:
        prepared = self.ip.preprocess_batch([text], src_lang=SRC_LANG, tgt_lang=TGT_LANG)[0]
        return len(self.tokenizer(prepared).input_ids)

    def translate(self, sentences: List[str]) -> List[str]:
        batch = self.ip.preprocess_batch(sentences, src_lang=SRC_LANG, tgt_lang=TGT_LANG)
        inputs = self.tokenizer(batch, truncation=True, padding="longest", return_tensors="pt",
                                return_attention_mask=True).to(self.device)
        try:
            out = self._generate(inputs)
        except AttributeError as e:
            # The model's remote code indexes past_key_values as legacy tuples; newer transformers pass a
            # Cache object instead ('NoneType' object has no attribute 'shape'). Generate without it.
            if not self.use_cache:
                raise
            log.warning(f"IndicTrans2 can't use the generation cache with this transformers version ({e}); "
                        f"continuing without it (slower)")
            self.use_cache = False
            out = self._generate(inputs)
        decoded = self.tokenizer.batch_decode(out, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        return self.ip.postprocess_batch(decoded, lang=TGT_LANG)

    def _generate(self, inputs):
        with self.torch.inference_mode():
            return self.model.generate(**inputs, use_cache=self.use_cache, min_length=0,
                                       max_length=MAX_NEW_TOKENS, num_beams=self.num_beams,
                                       num_return_sequences=1)


class NLLB:
    name = "nllb"

    def __init__(self, device: str, num_beams: int):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        model_id = MODELS[self.name]
        self.torch, self.device, self.num_beams = torch, device, num_beams
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, src_lang=SRC_LANG)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_id, dtype=torch.float16 if device == "cuda" else torch.float32,
        ).to(device).eval()
        self.eng = self.tokenizer.convert_tokens_to_ids(TGT_LANG)

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer(text).input_ids)

    def translate(self, sentences: List[str]) -> List[str]:
        inputs = self.tokenizer(sentences, truncation=True, padding="longest", return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            out = self.model.generate(**inputs, forced_bos_token_id=self.eng, max_length=MAX_NEW_TOKENS,
                                      num_beams=self.num_beams)
        return self.tokenizer.batch_decode(out, skip_special_tokens=True)


def load_model(choice: str, device: str, num_beams: int):
    if choice in ("auto", "indictrans2"):
        try:
            return IndicTrans2(device, num_beams)
        except Exception as e:
            if choice == "indictrans2":
                raise
            log.warning(f"IndicTrans2 unavailable ({type(e).__name__}: {str(e).splitlines()[0][:200]}); "
                        f"falling back to NLLB")
    return NLLB(device, num_beams)


# --- Records -------------------------------------------------------------------------------------

def missing_fields(record: Dict) -> List[str]:
    """Base names of fields with Tamil text but no English yet."""
    return [k[:-3] for k in record
            if k.endswith("_ta") and f"{k[:-3]}_source_en" in record
            and isinstance(record[k], str) and record[k].strip() and not record.get(f"{k[:-3]}_en")]


class FieldTranslator:
    """Turns field texts into sentence pieces, translates the uncached ones in batches, reassembles."""

    def __init__(self, model, cache: Cache, glossary, batch_size: int):
        self.model, self.cache, self.glossary, self.batch_size = model, cache, glossary, batch_size
        self._token_counts: Dict[str, int] = {}

    def _count(self, text: str) -> int:
        if text not in self._token_counts:
            self._token_counts[text] = self.model.count_tokens(text)
        return self._token_counts[text]

    def plan(self, text: str) -> List[List[Optional[str]]]:
        """Per line: the Tamil pieces to translate, or [None, line] for a line with no Tamil to copy."""
        lines = []
        for line in text.split("\n"):
            if not TAMIL.search(line):
                lines.append([None, line.strip()])
                continue
            pieces = []
            for sentence in split_sentences(apply_pre(line, self.glossary)):
                pieces.extend(split_long(sentence, self._count))
            lines.append(pieces)
        return lines

    def translate_texts(self, texts: List[str], progress=None) -> List[str]:
        plans = [self.plan(t) for t in texts]
        todo = sorted({p for plan in plans for line in plan if line[0] is not None for p in line
                       if self.cache.get(p) is None}, key=len)  # similar lengths batch together
        for i in range(0, len(todo), self.batch_size):
            batch = todo[i:i + self.batch_size]
            self.cache.put_many(zip(batch, (t.strip() for t in self.model.translate(batch))), self.model.name)
            if progress:
                progress.update(len(batch))
        out = []
        for plan in plans:
            lines = [line[1] if line[0] is None else " ".join(self.cache.get(p) for p in line) for line in plan]
            out.append(apply_post(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip(), self.glossary))
        return out

    def count_pending(self, texts: List[str]) -> int:
        return len({p for t in texts for line in self.plan(t) if line[0] is not None for p in line
                    if self.cache.get(p) is None})


def read_records(path: Path) -> List[Dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def write_records(path: Path, records: List[Dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    os.replace(tmp, path)


def translate_records(records: List[Dict], targets: List[Dict], translator: FieldTranslator,
                      checkpoint_every: int, save) -> Dict[str, int]:
    from tqdm import tqdm
    stats = {"temples": 0, "fields": 0}
    total = translator.count_pending([r[f"{f}_ta"] for r in targets for f in missing_fields(r)])
    log.info(f"{len(targets)} temple(s) with missing English; {total:,} sentence piece(s) to translate "
             f"(the rest are cached)")
    with tqdm(total=total, desc="Translating", unit="piece") as bar:
        for start in range(0, len(targets), checkpoint_every):
            group = targets[start:start + checkpoint_every]
            jobs = [(r, f) for r in group for f in missing_fields(r)]
            english = translator.translate_texts([r[f"{f}_ta"] for r, f in jobs], bar)
            for (r, f), en in zip(jobs, english):
                r[f"{f}_en"], r[f"{f}_source_en"] = en, "machine"
            stats["temples"] += len(group)
            stats["fields"] += len(jobs)
            save(records)
    return stats


# --- CLI -----------------------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Translate missing English fields in temples.jsonl locally.")
    p.add_argument("--input", type=Path, default=HERE / "output" / "temples.jsonl")
    p.add_argument("--output", type=Path, help="Default: overwrite --input")
    p.add_argument("--model", choices=["auto", "indictrans2", "nllb"], default="auto")
    p.add_argument("--batch-size", type=int, help="Default: 32 on GPU, 4 on CPU")
    p.add_argument("--num-beams", type=int, help="Default: 4 on GPU, 2 on CPU")
    p.add_argument("--cache", type=Path, default=HERE / "data" / "cache" / "translations_local.jsonl")
    p.add_argument("--glossary", type=Path, default=HERE / "glossary.json")
    p.add_argument("--district", help="Only temples of this district id")
    p.add_argument("--limit", type=int, help="At most N temples")
    p.add_argument("--checkpoint-every", type=int, default=50, help="Save temples.jsonl every N temples")
    return p.parse_args(argv)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    if not args.input.exists():
        log.error(f"{args.input} not found")
        return 2
    output = args.output or args.input
    records = read_records(args.input)
    targets = [r for r in records if missing_fields(r) and (not args.district or r.get("district_id") == args.district)]
    if args.limit:
        targets = targets[:args.limit]
    if not targets:
        log.info("Nothing to translate: every field with Tamil text already has English.")
        if output != args.input:
            write_records(output, records)
        return 0

    device = pick_device()
    batch_size = args.batch_size or (32 if device == "cuda" else 4)
    num_beams = args.num_beams or (4 if device == "cuda" else 2)
    model = load_model(args.model, device, num_beams)
    log.info(f"Model: {MODELS[model.name]} on {device} (batch {batch_size}, beams {num_beams})")
    translator = FieldTranslator(model, Cache(args.cache), load_glossary(args.glossary), batch_size)
    stats = translate_records(records, targets, translator, args.checkpoint_every,
                              lambda recs: write_records(output, recs))
    log.info(f"Done: {stats['fields']:,} field(s) in {stats['temples']:,} temple(s) -> {output}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    sys.exit(main())
