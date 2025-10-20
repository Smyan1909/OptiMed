"""
Debug script to understand why personnummer is not being detected.
"""

import sys
import os
import re

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    from optimed.adapters.outbound.phi_redactor.presidio_redactor import PresidioPhiRedactor
    PRESIDIO_AVAILABLE = True
except ImportError as e:
    print(f"Presidio not available: {e}")
    PRESIDIO_AVAILABLE = False
    sys.exit(1)


def test_regex_patterns():
    """Test if the regex patterns themselves work."""
    print("\n" + "="*70)
    print("Testing Regex Patterns Directly")
    print("="*70)

    patterns = [
        (r"\b\d{8}[-\s]?\d{4}\b", "12-digit personnummer"),
        (r"\b\d{6}[-\s]?\d{4}\b", "10-digit personnummer"),
    ]

    test_cases = [
        "19850315-1234",  # YYYYMMDD-XXXX
        "850315-1234",    # YYMMDD-XXXX
        "198503151234",   # YYYYMMDDXXXX
        "8503151234",     # YYMMDDXXXX
    ]

    for pattern_str, description in patterns:
        print(f"\nPattern: {pattern_str} ({description})")
        pattern = re.compile(pattern_str)
        for test in test_cases:
            match = pattern.search(test)
            print(f"  {test}: {'MATCH' if match else 'NO MATCH'}")


def test_presidio_recognizer():
    """Test Presidio recognizer directly."""
    print("\n" + "="*70)
    print("Testing Presidio PatternRecognizer")
    print("="*70)

    personnummer_patterns = [
        Pattern(
            name="personnummer_12_digit",
            regex=r"\b\d{8}[-\s]?\d{4}\b",
            score=0.9,
        ),
        Pattern(
            name="personnummer_10_digit",
            regex=r"\b\d{6}[-\s]?\d{4}\b",
            score=0.85,
        ),
    ]

    recognizer = PatternRecognizer(
        supported_entity="PERSONNUMMER",
        patterns=personnummer_patterns,
        context=["personnummer", "personnum", "person nummer", "national id", "id number"],
    )

    test_texts = [
        "Personnummer: 19850315-1234",
        "Patient ID: 850315-1234",
        "ID number: 198503151234",
        "National ID: 8503151234",
    ]

    for text in test_texts:
        results = recognizer.analyze(text, entities=["PERSONNUMMER"])
        print(f"\nText: {text}")
        if results:
            for result in results:
                print(f"  FOUND: {text[result.start:result.end]} (score: {result.score})")
        else:
            print(f"  NO MATCH")


def test_analyzer_engine():
    """Test full AnalyzerEngine with custom recognizer."""
    print("\n" + "="*70)
    print("Testing Full AnalyzerEngine")
    print("="*70)

    # Create analyzer
    analyzer = AnalyzerEngine()

    # Create personnummer recognizer
    personnummer_patterns = [
        Pattern(
            name="personnummer_12_digit",
            regex=r"\b\d{8}[-\s]?\d{4}\b",
            score=0.9,
        ),
        Pattern(
            name="personnummer_10_digit",
            regex=r"\b\d{6}[-\s]?\d{4}\b",
            score=0.85,
        ),
    ]

    personnummer_recognizer = PatternRecognizer(
        supported_entity="PERSONNUMMER",
        patterns=personnummer_patterns,
        context=["personnummer", "personnum", "person nummer", "national id", "id number"],
    )

    # Add to analyzer
    analyzer.registry.add_recognizer(personnummer_recognizer)

    # Test
    test_texts = [
        "Personnummer: 19850315-1234",
        "Patient ID: 850315-1234",
        "ID number: 198503151234",
        "National ID: 8503151234",
    ]

    for text in test_texts:
        print(f"\nText: {text}")
        results = analyzer.analyze(text=text, language="sv", entities=["PERSONNUMMER"])
        if results:
            for result in results:
                print(f"  FOUND: {text[result.start:result.end]} (score: {result.score}, entity: {result.entity_type})")
        else:
            print(f"  NO MATCH")


def test_redactor_analyzer():
    """Test the actual redactor's analyzer."""
    print("\n" + "="*70)
    print("Testing PresidioPhiRedactor's Analyzer")
    print("="*70)

    redactor = PresidioPhiRedactor(default_language="sv")

    # Check if recognizer is registered
    print("\nRegistered recognizers:")
    for recognizer in redactor.analyzer.registry.recognizers:
        print(f"  - {recognizer.name}: {recognizer.supported_entities}")

    test_texts = [
        "Personnummer: 19850315-1234",
        "Patient ID: 850315-1234",
        "ID number: 198503151234",
        "National ID: 8503151234",
    ]

    for text in test_texts:
        print(f"\nText: {text}")
        results = redactor.analyzer.analyze(text=text, language="sv", entities=["PERSONNUMMER"])
        if results:
            for result in results:
                print(f"  FOUND: {text[result.start:result.end]} (score: {result.score}, entity: {result.entity_type})")
        else:
            print(f"  NO MATCH")


def main():
    """Run all debug tests."""
    print("\n" + "="*70)
    print("PERSONNUMMER DETECTION DEBUG")
    print("="*70)

    try:
        test_regex_patterns()
        test_presidio_recognizer()
        test_analyzer_engine()
        test_redactor_analyzer()

        print("\n" + "="*70)
        print("DEBUG COMPLETED")
        print("="*70)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
