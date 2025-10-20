"""
Test script to reproduce the exact bugs reported in the PHI redactor.

This script tests the specific issues:
1. Over-redaction: dates, durations, frequencies, dosages being incorrectly redacted
2. Under-redaction: personnummer not being redacted at all
"""

import sys
import os
import io

# Force UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from optimed.adapters.outbound.phi_redactor.presidio_redactor import PresidioPhiRedactor
    PRESIDIO_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  Presidio not available: {e}")
    PRESIDIO_AVAILABLE = False
    sys.exit(1)


def test_over_redaction_issues():
    """Test cases showing over-redaction problems."""
    print("\n" + "="*70)
    print("BUG TEST 1: OVER-REDACTION ISSUES")
    print("="*70)

    redactor = PresidioPhiRedactor(default_language="en")

    test_cases = [
        # Format: (input, expected_output, description)
        ("Patient has diabetes for 10 years", "for 10 years", "Duration should be preserved"),
        ("Diagnosed in 2019", "in 2019", "Year only should be preserved"),
        ("Aspirin 81 mg daily", "81 mg daily", "Dosage and frequency should be preserved"),
        ("Metformin 500 mg twice daily", "500 mg twice daily", "Dosage and frequency should be preserved"),
        ("Follow-up in 3 months", "in 3 months", "Relative time should be preserved"),
        ("Started treatment 2 weeks ago", "2 weeks ago", "Relative time should be preserved"),
        ("Takes medication twice daily", "twice daily", "Frequency should be preserved"),
    ]

    print("\n❌ Current bugs (should preserve but currently over-redacting):")
    print("-" * 70)

    for input_text, expected_fragment, description in test_cases:
        result = redactor.redact(input_text, language="en")
        is_preserved = expected_fragment in result
        status = "✓" if is_preserved else "✗ BUG"
        print(f"{status} {description}")
        print(f"    Input:    {input_text}")
        print(f"    Output:   {result}")
        print(f"    Expected: Should contain '{expected_fragment}'")
        print()


def test_under_redaction_issues():
    """Test cases showing under-redaction problems (personnummer)."""
    print("\n" + "="*70)
    print("BUG TEST 2: UNDER-REDACTION ISSUES (Personnummer)")
    print("="*70)

    redactor = PresidioPhiRedactor(default_language="sv")

    test_cases = [
        ("Personnummer: 19850315-1234", "19850315-1234", "YYYYMMDD-XXXX"),
        ("Patient ID: 850315-1234", "850315-1234", "YYMMDD-XXXX"),
        ("ID number: 198503151234", "198503151234", "YYYYMMDDXXXX"),
        ("National ID: 8503151234", "8503151234", "YYMMDDXXXX"),
    ]

    print("\n❌ Current bugs (should redact but currently NOT redacting):")
    print("-" * 70)

    for input_text, personnummer, format_name in test_cases:
        result = redactor.redact(input_text, language="sv")
        is_redacted = personnummer not in result and "[REDACTED" in result
        status = "✓" if is_redacted else "✗ BUG"
        print(f"{status} {format_name}: {personnummer}")
        print(f"    Input:  {input_text}")
        print(f"    Output: {result}")
        print(f"    Expected: Should redact '{personnummer}' to [REDACTED_ID]")
        print()


def test_dosage_vs_phone_confusion():
    """Test that dosages aren't confused with phone numbers."""
    print("\n" + "="*70)
    print("BUG TEST 3: DOSAGE vs PHONE NUMBER CONFUSION")
    print("="*70)

    redactor = PresidioPhiRedactor(default_language="en")

    test_cases = [
        # Dosages - should NOT be redacted
        ("Metformin 500 mg twice daily", "500 mg", "Dosage", False),
        ("Aspirin 81 mg daily", "81 mg", "Dosage", False),
        ("Insulin 100 units", "100 units", "Dosage", False),

        # Phone numbers - SHOULD be redacted
        ("Phone: 555-1234", "555-1234", "Phone number", True),
        ("Call 070-1234567", "070-1234567", "Phone number", True),
    ]

    print("\n❌ Current bugs:")
    print("-" * 70)

    for input_text, fragment, description, should_redact in test_cases:
        result = redactor.redact(input_text, language="en")
        is_redacted = fragment not in result

        if should_redact:
            status = "✓" if is_redacted else "✗ BUG"
            expectation = "should be redacted"
        else:
            status = "✓" if not is_redacted else "✗ BUG"
            expectation = "should be preserved"

        print(f"{status} {description} ({expectation})")
        print(f"    Input:  {input_text}")
        print(f"    Output: {result}")
        print()


def test_dob_vs_clinical_dates():
    """Test that DOB is redacted but clinical dates are preserved."""
    print("\n" + "="*70)
    print("BUG TEST 4: DOB vs CLINICAL DATES")
    print("="*70)

    redactor = PresidioPhiRedactor(default_language="en")

    test_cases = [
        # DOB - SHOULD be redacted
        ("DOB: 05/12/1970", "05/12/1970", "DOB", True),
        ("Date of Birth: 1970-05-12", "1970-05-12", "DOB", True),
        ("Born on 05/12/1970", "05/12/1970", "DOB", True),

        # Clinical dates - should NOT be redacted (or only year preserved)
        ("Diagnosed in 2019", "2019", "Year only", False),
        ("Started treatment in 2015", "2015", "Year only", False),
        ("Follow-up in 3 months", "3 months", "Relative time", False),
        ("Last visit 2 weeks ago", "2 weeks ago", "Relative time", False),
    ]

    print("\n❌ Current bugs:")
    print("-" * 70)

    for input_text, fragment, description, should_redact in test_cases:
        result = redactor.redact(input_text, language="en")
        is_redacted = fragment not in result

        if should_redact:
            status = "✓" if is_redacted else "✗ BUG"
            expectation = "should be redacted"
        else:
            status = "✓" if not is_redacted else "✗ BUG"
            expectation = "should be preserved"

        print(f"{status} {description} ({expectation})")
        print(f"    Input:  {input_text}")
        print(f"    Output: {result}")
        print()


def main():
    """Run all bug tests."""
    print("\n" + "="*70)
    print("PHI REDACTOR BUG REPRODUCTION TEST SUITE")
    print("="*70)
    print("\nTesting the exact bugs reported:")
    print("1. Over-redaction: dates, durations, frequencies being incorrectly redacted")
    print("2. Under-redaction: personnummer not being redacted at all")

    try:
        test_over_redaction_issues()
        test_under_redaction_issues()
        test_dosage_vs_phone_confusion()
        test_dob_vs_clinical_dates()

        print("\n" + "="*70)
        print("BUG TEST SUITE COMPLETED")
        print("="*70)
        print("\nSee results above to identify which bugs are present.")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
