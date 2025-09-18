from __future__ import annotations

from typing import Sequence

from optimed.core.domain import Chunk, Record, ChunkPolicy
from optimed.core.ports import ChunkingStrategy, TokenizerPort
from optimed.core.services.hash_utils import stable_hash


class AtomicFactV1(ChunkingStrategy):
    """One chunk per fact; short header; no overlap."""

    @property
    def strategy_id(self) -> str:
        return "AtomicFactV1"

    @property
    def strategy_version(self) -> str:
        return "1.0"

    def apply(self, records: Sequence[Record], policy: ChunkPolicy, tokenizer: TokenizerPort) -> list[Chunk]:
        chunks: list[Chunk] = []
        for r in records:
            header_parts: list[str] = []
            if r.resource_type:
                header_parts.append(r.resource_type.capitalize())
            if r.key:
                header_parts.append(r.key)
            # Use the text field if available (contains source information), otherwise fall back to value
            value_str = r.value or ""
            if r.text:
                content = r.text.strip()
            else:
                units_str = f" {r.units}" if r.units else ""
                code_str = f" [{r.system}:{r.code}]" if r.code and r.system else (f" [{r.code}]" if r.code else "")
                line = f"{' - '.join(header_parts)}: {value_str}{units_str}{code_str}"
                content = line.strip()
            chunk_id = stable_hash(
                {
                    "patient_ref": r.patient_ref,
                    "encounter_ref": r.encounter_ref,
                    "resource_type": r.resource_type,
                    "key": r.key,
                    "value": value_str,
                    "units": r.units,
                    "code": r.code,
                    "system": r.system,
                    "ts": r.timestamp.isoformat() if r.timestamp else None,
                },
                namespace=f"chunk:{self.strategy_id}:{self.strategy_version}",
            )
            chunks.append(
                Chunk(
                    id=chunk_id,
                    patient_ref=r.patient_ref,
                    text=content,
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
                    span=None,
                    meta={"policy": policy.name},
                )
            )
        return chunks


