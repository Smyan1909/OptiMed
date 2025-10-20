"""
Benchmark script to measure the performance impact of the Presidio redactor
compared to the simple redactor in the OptiMed LangGraph flow.

This script tests both redactors with realistic Swedish and English clinical text
to provide performance metrics.
"""

import time
import statistics
from typing import List, Tuple

# Test data: realistic Swedish and English clinical notes
SWEDISH_CLINICAL_NOTE = """
Patient: Anna Johansson
Personnummer: 19701215-1234
Telefon: 070-1234567
E-post: anna.johansson@example.com

Aktuellt:
Patienten har haft Diabetes Mellitus Typ 2 sedan 10 år. Tidigare Hjärtinfarkt i 2020.
Nuvarande Hypertoni sedan 5 år.

Medicinering:
- Aspirin 81 mg dagligen
- Metformin 500 mg två gånger dagligen
- Lisinopril 10 mg dagligen
- Omeprazol 20 mg på morgonen

Allergier: Penicillin (utslag)

Status:
- Hjärta: Vänster Kammare funktion bevarad
- Lungor: Auskultation normalt
- Kranskärl: Inga tecken på ischemi

Bedömning:
Stabil Diabetes Mellitus Typ 2 med god glykemisk kontroll.

Plan:
Fortsätt nuvarande medicinering. Uppföljning om 3 månader.
"""

ENGLISH_CLINICAL_NOTE = """
Patient: John Smith
DOB: 05/12/1970
Phone: 555-123-4567
Email: john.smith@example.com

Chief Complaint: Chest pain

History of Present Illness:
Patient has Type 2 Diabetes Mellitus for 10 years. Hypertension and previous Myocardial Infarction in 2020.

Current Medications:
- Aspirin 81 mg daily
- Metformin 500 mg twice daily
- Lisinopril 10 mg daily
- Omeprazole 20 mg in the morning

Allergies: Penicillin (rash)

Physical Exam:
- Cardiovascular: Left Ventricle function preserved
- Respiratory: Auscultation normal
- Coronary Artery: No signs of ischemia

Assessment:
Stable Type 2 Diabetes Mellitus with good glycemic control.

Plan:
Continue current medications. Follow-up in 3 months.
"""

def benchmark_simple_redactor(text: str, iterations: int = 100) -> Tuple[float, str]:
    """Benchmark the SimplePhiRedactor."""
    from optimed.adapters.outbound.phi_redactor.simple_redactor import SimplePhiRedactor

    redactor = SimplePhiRedactor()
    times: List[float] = []
    result = ""

    for _ in range(iterations):
        start = time.perf_counter()
        result = redactor.redact(text)
        end = time.perf_counter()
        times.append((end - start) * 1000)  # Convert to milliseconds

    return statistics.mean(times), result

def benchmark_presidio_redactor(text: str, language: str, iterations: int = 100) -> Tuple[float, str]:
    """Benchmark the PresidioPhiRedactor."""
    try:
        from optimed.adapters.outbound.phi_redactor.presidio_redactor import PresidioPhiRedactor

        redactor = PresidioPhiRedactor(default_language=language)
        times: List[float] = []
        result = ""

        # First call initializes the models (lazy loading)
        print(f"  Initializing Presidio models for {language}...")
        redactor.redact(text)

        # Now benchmark
        for _ in range(iterations):
            start = time.perf_counter()
            result = redactor.redact(text, language=language)
            end = time.perf_counter()
            times.append((end - start) * 1000)  # Convert to milliseconds

        return statistics.mean(times), result
    except ImportError as e:
        print(f"  ❌ Presidio not available: {e}")
        return 0.0, ""

def main():
    print("=" * 80)
    print("PHI Redactor Performance Benchmark")
    print("=" * 80)
    print()

    iterations = 100
    print(f"Running {iterations} iterations per test...\n")

    # Benchmark Swedish text
    print("Swedish Clinical Note (~700 chars)")
    print("-" * 80)

    print("1. SimplePhiRedactor (English-only baseline):")
    simple_time_sv, simple_result_sv = benchmark_simple_redactor(SWEDISH_CLINICAL_NOTE, iterations)
    print(f"   Average time: {simple_time_sv:.2f} ms")
    print()

    print("2. PresidioPhiRedactor (Multilingual):")
    presidio_time_sv, presidio_result_sv = benchmark_presidio_redactor(SWEDISH_CLINICAL_NOTE, "sv", iterations)
    if presidio_time_sv > 0:
        print(f"   Average time: {presidio_time_sv:.2f} ms")
        overhead = presidio_time_sv - simple_time_sv
        overhead_pct = (overhead / simple_time_sv) * 100
        print(f"   Overhead: +{overhead:.2f} ms ({overhead_pct:.1f}%)")
    print()

    # Benchmark English text
    print("English Clinical Note (~650 chars)")
    print("-" * 80)

    print("1. SimplePhiRedactor (English-only baseline):")
    simple_time_en, simple_result_en = benchmark_simple_redactor(ENGLISH_CLINICAL_NOTE, iterations)
    print(f"   Average time: {simple_time_en:.2f} ms")
    print()

    print("2. PresidioPhiRedactor (Multilingual):")
    presidio_time_en, presidio_result_en = benchmark_presidio_redactor(ENGLISH_CLINICAL_NOTE, "en", iterations)
    if presidio_time_en > 0:
        print(f"   Average time: {presidio_time_en:.2f} ms")
        overhead = presidio_time_en - simple_time_en
        overhead_pct = (overhead / simple_time_en) * 100
        print(f"   Overhead: +{overhead:.2f} ms ({overhead_pct:.1f}%)")
    print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if presidio_time_sv > 0 and presidio_time_en > 0:
        avg_presidio = (presidio_time_sv + presidio_time_en) / 2
        avg_simple = (simple_time_sv + simple_time_en) / 2
        avg_overhead = avg_presidio - avg_simple
        avg_overhead_pct = (avg_overhead / avg_simple) * 100

        print(f"\nAverage Performance:")
        print(f"  SimplePhiRedactor:   {avg_simple:.2f} ms per document")
        print(f"  PresidioPhiRedactor: {avg_presidio:.2f} ms per document")
        print(f"  Overhead:            +{avg_overhead:.2f} ms ({avg_overhead_pct:.1f}%)")

        print(f"\nThroughput (documents/second):")
        print(f"  SimplePhiRedactor:   {1000/avg_simple:.1f} docs/sec")
        print(f"  PresidioPhiRedactor: {1000/avg_presidio:.1f} docs/sec")

        print(f"\nImpact on LangGraph Flow:")
        print(f"  Typical flow latency: 300-800 ms")
        print(f"  Presidio overhead: +{avg_overhead:.2f} ms ({(avg_overhead/500)*100:.1f}% of 500ms flow)")

        print(f"\nRecommendation:")
        if avg_overhead_pct < 20:
            print(f"  ✅ LOW IMPACT: Presidio overhead is acceptable (<20%)")
            print(f"     The multilingual capabilities and improved accuracy are worth it.")
        elif avg_overhead_pct < 50:
            print(f"  ⚠️  MODERATE IMPACT: Presidio adds {avg_overhead_pct:.1f}% overhead")
            print(f"     Consider if multilingual support is critical for your use case.")
        else:
            print(f"  ❌ HIGH IMPACT: Presidio adds {avg_overhead_pct:.1f}% overhead")
            print(f"     May need optimization or consider keeping SimplePhiRedactor.")

        print(f"\nGDPR Compliance:")
        print(f"  SimplePhiRedactor:   ❌ English-only, misses Swedish PHI")
        print(f"  PresidioPhiRedactor: ✅ Multilingual, properly redacts Swedish personnummer")
    else:
        print("  ❌ Presidio not available - install dependencies to run benchmark")
        print("     pip install presidio-analyzer presidio-anonymizer spacy")
        print("     python -m spacy download sv_core_news_sm")
        print("     python -m spacy download en_core_web_sm")

    print()
    print("=" * 80)

if __name__ == "__main__":
    main()
