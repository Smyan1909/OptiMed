from __future__ import annotations

import re

from optimed.core.ports import TokenizerPort


class WhitespaceTokenizer(TokenizerPort):
    """Simple fallback tokenizer: counts whitespace-separated tokens and splits sentences by punctuation.

    Replace later with tiktoken-backed implementation.
    """

    _sentence_re = re.compile(r"(?<=[.!?])\s+")

    def token_count(self, text: str) -> int:
        if not text:
            return 0
        return len([t for t in text.split() if t])

    def split_sentences(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []
        # naive split; keep it deterministic
        parts = re.split(self._sentence_re, text)
        # fallback: if regex fails, return whole text
        return [p.strip() for p in parts if p and p.strip()]


