"""Tamil -> English machine translation (Claude API) for fields the site has no English for.

Text is translated in chunks of ~1000 characters, split on paragraph / sentence boundaries.
Every chunk's translation is cached on disk, keyed by the SHA-256 of its Tamil text, so reruns
(and identical text shared by many temples, e.g. accommodation lists) are never re-translated.
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from config.settings import settings

log = logging.getLogger("agentapp")


class TranslationError(Exception):
    pass


def split_chunks(text: str, max_chars: int) -> List[str]:
    """Split on paragraph, then sentence, then word boundaries so each chunk is <= max_chars."""
    def pieces(t: str, seps: List[str]) -> List[str]:
        if len(t) <= max_chars:
            return [t]
        if not seps:  # one unbroken run of characters: hard split
            return [t[i:i + max_chars] for i in range(0, len(t), max_chars)]
        sep, rest = seps[0], seps[1:]
        parts = [p for p in re.split(f"(?<={sep})", t) if p]
        out: List[str] = []
        for p in parts:
            out.extend(pieces(p, rest) if len(p) > max_chars else [p])
        return out

    chunks: List[str] = []
    for piece in pieces(text, [r"\n", r"[.!?।]\s", r" "]):
        if chunks and len(chunks[-1]) + len(piece) <= max_chars:
            chunks[-1] += piece
        else:
            chunks.append(piece)
    return [c for c in chunks if c.strip()]


def _system_prompt(glossary: Dict[str, str]) -> str:
    terms = "\n".join(f"- {ta} = {en}" for ta, en in glossary.items())
    return (
        "You translate Tamil text from a directory of Hindu temples into clear, natural English.\n"
        "Rules:\n"
        "- Output only the English translation: no preamble, notes, quotes or the Tamil original.\n"
        "- Transliterate proper nouns into Roman script instead of translating their meaning: "
        "temple, deity, saint and place names (e.g. கபாலீஸ்வரர் -> Kapaleeswarar, "
        "மயிலாப்பூர் -> Mylapore). Use the common English spelling when one exists.\n"
        "- Always use this glossary:\n" + terms + "\n"
        "- Keep numbers, phone numbers, times, PIN codes and line breaks as in the source.\n"
        "- The input may be a fragment of a longer text; translate it as it is."
    )


class TranslationCache:
    """Append-only JSONL file of {"h": sha256(tamil), "en": english}."""

    def __init__(self, path: Path):
        self.path = path
        self._data: Dict[str, str] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    self._data[row["h"]] = row["en"]
                except (ValueError, KeyError):
                    continue  # a line cut short by a crash

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, text: str) -> Optional[str]:
        return self._data.get(self.key(text))

    def put(self, text: str, english: str) -> None:
        h = self.key(text)
        self._data[h] = english
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"h": h, "en": english}, ensure_ascii=False) + "\n")

    def __len__(self) -> int:
        return len(self._data)


class Translator:
    def __init__(self, client=None, model: str = settings.translate_model,
                 chunk_chars: int = settings.translate_chunk_chars,
                 cache: Optional[TranslationCache] = None):
        if client is None:
            import anthropic
            # The SDK retries 429 / 5xx / connection errors with exponential backoff
            client = anthropic.AsyncAnthropic(max_retries=5)
        self.client = client
        self.model = model
        self.chunk_chars = chunk_chars
        self.cache = cache if cache is not None else TranslationCache(settings.cache_dir / "translations.jsonl")
        self.system = _system_prompt(settings.glossary)
        self.api_calls = 0

    async def translate(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        cached = self.cache.get(text)
        if cached is not None:
            return cached
        parts = [await self._translate_chunk(c) for c in split_chunks(text, self.chunk_chars)]
        english = "".join(parts).strip()
        self.cache.put(text, english)
        return english

    async def _translate_chunk(self, chunk: str) -> str:
        core = chunk.strip()
        if not core:
            return chunk
        cached = self.cache.get(core)
        if cached is None:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=0,
                system=self.system,
                messages=[{"role": "user", "content": core}],
            )
            self.api_calls += 1
            if response.stop_reason != "end_turn":
                raise TranslationError(f"translation stopped early ({response.stop_reason})")
            cached = "".join(b.text for b in response.content if b.type == "text").strip()
            self.cache.put(core, cached)
        # keep the whitespace / line break that separated this chunk from the next
        trailing = chunk[len(chunk.rstrip()):]
        return cached + ("\n" if "\n" in trailing else " " if trailing else "")
