from __future__ import annotations

import csv
from typing import Any

from optimed.core.domain import Record, PolicySet
from optimed.core.ports import ChunkerPort, PhiRedactorPort


class DocumentChunkerAdapter(ChunkerPort):
    """Convert CSV/PDF documents into Records. Heavy parsing is minimal here.

    This adapter focuses on extraction and PHI redaction; strategy selection
    and chunking are handled by the orchestrator.
    """

    def __init__(self, redactor: PhiRedactorPort):
        self._redactor = redactor

    def chunk_from_patient(self, patient_context, policy_set: PolicySet) -> list:
        raise NotImplementedError("Not supported in Document adapter")

    def chunk_from_document(self, document_ref: dict[str, Any], policy_set: PolicySet) -> list:
        raise NotImplementedError("Use orchestrator.chunk_document which calls this adapter to produce Records")

    # --- helpers ---
    def csv_to_records(self, path: str, resource_type: str = "csv_row") -> list[Record]:
        records: list[Record] = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Concatenate columns into a text line, redact each value
                parts: list[str] = []
                for k, v in row.items():
                    vv = self._redactor.redact(str(v)) if v is not None else ""
                    parts.append(f"{k}: {vv}")
                text = " | ".join(parts)
                records.append(Record(resource_type=resource_type, text=text))
        return records

    def pdf_to_records(self, text: str, resource_type: str = "pdf") -> list[Record]:
        # Assume text already extracted by caller; redact here
        redacted = self._redactor.redact(text)
        return [Record(resource_type=resource_type, text=redacted)]


