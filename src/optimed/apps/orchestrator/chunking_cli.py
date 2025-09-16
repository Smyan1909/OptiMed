from __future__ import annotations

import argparse
import json
from statistics import mean

from optimed.apps.orchestrator.chunking_config import STRATEGY_REGISTRY, POLICY_PRESETS
from optimed.apps.orchestrator.chunking_orchestrator import ChunkingOrchestrator
from optimed.adapters.outbound.tokenizer.whitespace_tokenizer import WhitespaceTokenizer
from optimed.adapters.outbound.phi_redactor.simple_redactor import SimplePhiRedactor
from optimed.core.domain import PatientContext


def summarize(chunks):
    print(f"Total chunks: {len(chunks)}")
    by_strategy: dict[str, int] = {}
    token_counts = []
    tok = WhitespaceTokenizer()
    for c in chunks:
        by_strategy[c.strategy_id] = by_strategy.get(c.strategy_id, 0) + 1
        token_counts.append(tok.token_count(c.text))
    print("Counts by strategy:")
    for k, v in by_strategy.items():
        print(f"  {k}: {v}")
    print(f"Avg tokens: {round(mean(token_counts), 2) if token_counts else 0}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Hybrid Clinical Chunking")
    parser.add_argument("mode", choices=["patient", "csv", "pdf"], help="Input type")
    parser.add_argument("--patient-json", help="Path to patient context JSON for demo")
    parser.add_argument("--csv-path", help="Path to CSV file")
    parser.add_argument("--pdf-text", help="Plain text extracted from PDF")
    args = parser.parse_args(argv)

    orchestrator = ChunkingOrchestrator(
        tokenizer=WhitespaceTokenizer(),
        redactor=SimplePhiRedactor(),
        strategy_registry=STRATEGY_REGISTRY,
        policies=POLICY_PRESETS,
    )

    if args.mode == "patient":
        if not args.patient_json:
            print("--patient-json is required")
            return 1
        with open(args.patient_json, "r", encoding="utf-8") as f:
            pdata = json.load(f)
        patient = PatientContext(**pdata)
        chunks = orchestrator.chunk_patient(patient, POLICY_PRESETS)
        summarize(chunks)
        return 0

    if args.mode == "csv":
        if not args.csv_path:
            print("--csv-path is required")
            return 1
        doc = {"type": "csv", "path": args.csv_path}
        chunks = orchestrator.chunk_document(doc, POLICY_PRESETS)
        summarize(chunks)
        return 0

    if args.mode == "pdf":
        if not args.pdf_text:
            print("--pdf-text is required")
            return 1
        doc = {"type": "pdf", "text": args.pdf_text}
        chunks = orchestrator.chunk_document(doc, POLICY_PRESETS)
        summarize(chunks)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


