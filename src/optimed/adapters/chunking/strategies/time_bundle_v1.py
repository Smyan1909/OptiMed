from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Sequence

from optimed.core.domain import Chunk, Record, ChunkPolicy
from optimed.core.ports import ChunkingStrategy, TokenizerPort
from optimed.core.services.hash_utils import stable_hash


class TimeBundleV1(ChunkingStrategy):
    """Group input records (representing prior chunks) by encounter or time bucket and window with overlap."""

    @property
    def strategy_id(self) -> str:
        return "TimeBundleV1"

    @property
    def strategy_version(self) -> str:
        return "1.0"

    def apply(self, records: Sequence[Record], policy: ChunkPolicy, tokenizer: TokenizerPort) -> list[Chunk]:
        # Group by encounter_ref else by month (YYYY-MM)
        groups: dict[str, list[Record]] = defaultdict(list)
        for r in records:
            if r.encounter_ref:
                key = f"enc:{r.encounter_ref}"
            else:
                month = None
                if r.timestamp:
                    month = r.timestamp.strftime("%Y-%m")
                else:
                    month = r.extra.get("time_bucket") if r.extra else None
                key = f"tb:{month or 'unknown'}"
            groups[key].append(r)

        chunks: list[Chunk] = []
        target = max(1, policy.max_tokens)
        overlap_ratio = max(0.0, min(0.5, policy.overlap))
        overlap_tokens = int(target * overlap_ratio)

        for group_key, rs in groups.items():
            # sort by timestamp
            rs_sorted = sorted(rs, key=lambda x: x.timestamp or datetime.min)
            texts = [(r, (r.text or r.value or "").strip()) for r in rs_sorted]
            # slide over concatenated records, but respect record boundaries
            window: list[tuple[Record, str]] = []
            window_tokens = 0
            i = 0
            while i < len(texts):
                r, t = texts[i]
                tt = tokenizer.token_count(t)
                if window_tokens + tt <= target or not window:
                    window.append((r, t))
                    window_tokens += tt
                    i += 1
                else:
                    chunk_text = "\n".join([wt for _, wt in window]).strip()
                    span = (0, len(window) - 1)
                    chunks.append(self._build_chunk(window, chunk_text, span, policy))
                    # prepare overlap by keeping trailing records until overlap token count
                    if overlap_tokens > 0:
                        new_window: list[tuple[Record, str]] = []
                        new_tokens = 0
                        j = len(window) - 1
                        while j >= 0:
                            rj, tj = window[j]
                            tj_tok = tokenizer.token_count(tj)
                            if new_tokens + tj_tok > overlap_tokens:
                                break
                            new_window.insert(0, (rj, tj))
                            new_tokens += tj_tok
                            j -= 1
                        window = new_window
                        window_tokens = new_tokens
                    else:
                        window = []
                        window_tokens = 0

            if window:
                chunk_text = "\n".join([wt for _, wt in window]).strip()
                span = (0, len(window) - 1)
                chunks.append(self._build_chunk(window, chunk_text, span, policy))

        return chunks

    def _build_chunk(
        self,
        window: list[tuple[Record, str]],
        text: str,
        span: tuple[int, int],
        policy: ChunkPolicy,
    ) -> Chunk:
        # adopt patient/encounter from first record if present
        r0 = window[0][0]
        chunk_id = stable_hash(
            {
                "patient_ref": r0.patient_ref,
                "encounter_ref": r0.encounter_ref,
                "span": list(span),
                "text": text,
                "ts_first": r0.timestamp.isoformat() if r0.timestamp else None,
                "ts_last": window[-1][0].timestamp.isoformat() if window[-1][0].timestamp else None,
            },
            namespace=f"chunk:{self.strategy_id}:{self.strategy_version}",
        )
        time_bucket = None
        if r0.timestamp:
            time_bucket = r0.timestamp.strftime("%Y-%m")
        return Chunk(
            id=chunk_id,
            patient_ref=r0.patient_ref,
            text=text,
            resource_type="bundle",
            key=None,
            code=None,
            system=None,
            units=None,
            value_type=None,
            timestamp=r0.timestamp,
            time_bucket=time_bucket,
            encounter_ref=r0.encounter_ref,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            span=span,
            meta={"policy": policy.name, "members": [r.key for r, _ in window if r.key]},
        )


