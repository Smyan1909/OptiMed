from __future__ import annotations

from typing import Sequence

from optimed.core.domain import Chunk, Record, ChunkPolicy
from optimed.core.ports import ChunkingStrategy, TokenizerPort
from optimed.core.services.hash_utils import stable_hash


class NarrativeV1(ChunkingStrategy):
    """Sentence-aware splitting with overlap windows."""

    @property
    def strategy_id(self) -> str:
        return "NarrativeV1"

    @property
    def strategy_version(self) -> str:
        return "1.0"

    def apply(self, records: Sequence[Record], policy: ChunkPolicy, tokenizer: TokenizerPort) -> list[Chunk]:
        chunks: list[Chunk] = []
        target = max(1, policy.max_tokens)
        overlap_ratio = max(0.0, min(0.5, policy.overlap))
        overlap_tokens = int(target * overlap_ratio)

        for r in records:
            text = (r.text or r.value or "").strip()
            if not text:
                continue

            sentences = tokenizer.split_sentences(text)
            # Greedy pack sentences into token-limited windows with overlap
            window: list[str] = []
            window_tokens = 0
            sentence_tokens: list[int] = [tokenizer.token_count(s) for s in sentences]

            start_idx = 0
            i = 0
            while i < len(sentences):
                s = sentences[i]
                t = sentence_tokens[i]
                if window_tokens + t <= target or not window:
                    window.append(s)
                    window_tokens += t
                    i += 1
                else:
                    # emit current window
                    chunk_text = " ".join(window).strip()
                    span_start = start_idx
                    span_end = i - 1
                    chunks.append(self._build_chunk(r, chunk_text, span_start, span_end, policy))
                    # prepare next window with overlap
                    if overlap_tokens > 0:
                        # take sentences from end until overlap token budget reached
                        new_window: list[str] = []
                        new_tokens = 0
                        j = len(window) - 1
                        while j >= 0 and new_tokens + sentence_tokens[start_idx + j] < overlap_tokens:
                            new_window.insert(0, window[j])
                            new_tokens += sentence_tokens[start_idx + j]
                            j -= 1
                        window = new_window
                        window_tokens = new_tokens
                        start_idx = i - len(window)
                    else:
                        window = []
                        window_tokens = 0
                        start_idx = i
            if window:
                chunk_text = " ".join(window).strip()
                span_start = start_idx
                span_end = start_idx + len(window) - 1
                chunks.append(self._build_chunk(r, chunk_text, span_start, span_end, policy))

        return chunks

    def _build_chunk(self, r: Record, text: str, span_start: int, span_end: int, policy: ChunkPolicy) -> Chunk:
        chunk_id = stable_hash(
            {
                "patient_ref": r.patient_ref,
                "encounter_ref": r.encounter_ref,
                "resource_type": r.resource_type,
                "key": r.key,
                "span": [span_start, span_end],
                "text": text,
                "ts": r.timestamp.isoformat() if r.timestamp else None,
            },
            namespace=f"chunk:{self.strategy_id}:{self.strategy_version}",
        )
        return Chunk(
            id=chunk_id,
            patient_ref=r.patient_ref,
            text=text,
            resource_type=r.resource_type,
            key=r.key,
            code=r.code,
            system=r.system,
            units=r.units,
            value_type=r.value_type,
            timestamp=r.timestamp,
            encounter_ref=r.encounter_ref,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            span=(span_start, span_end),
            meta={"policy": policy.name},
        )


