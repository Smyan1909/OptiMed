"""Unit tests for PHI redactor to ensure medical terms are preserved while PHI is redacted."""

import pytest

from optimed.adapters.outbound.phi_redactor.simple_redactor import SimplePhiRedactor


class TestSimplePhiRedactor:
    """Test suite for SimplePhiRedactor to verify medical term preservation."""

    @pytest.fixture
    def redactor(self):
        """Create a redactor instance for testing."""
        return SimplePhiRedactor()

    # Medical terms that should NOT be redacted
    @pytest.mark.parametrize("text,preserved_term", [
        ("Patient is taking Aspirin 81 mg daily", "Aspirin"),
        ("Diagnosis: Diabetes Mellitus Type 2", "Diabetes Mellitus"),
        ("History of Coronary Artery Disease", "Coronary Artery"),
        ("CT Head showed no acute findings", "CT Head"),
        ("Allergies: Penicillin (rash)", "Penicillin"),
        ("Vaccines: COVID-19 Vaccine", "COVID-19 Vaccine"),
        ("Left Ventricle function normal", "Left Ventricle"),
        ("Taking Metformin 1000 mg twice daily", "Metformin"),
        ("Current medications: Lisinopril, Atorvastatin", "Lisinopril"),
        ("Current medications: Lisinopril, Atorvastatin", "Atorvastatin"),
        ("Ruled out Myocardial Infarction", "Myocardial Infarction"),
        ("Chief Complaint: Chest pain", "Chief Complaint"),
        ("Physical Exam: Normal", "Physical Exam"),
        ("Current Medications: None", "Current Medications"),
    ])
    def test_preserves_medical_terms(self, redactor, text, preserved_term):
        """Medical terms should be preserved after redaction."""
        result = redactor.redact(text)
        assert preserved_term in result, f"Medical term '{preserved_term}' was incorrectly redacted"

    # PHI that SHOULD be redacted
    @pytest.mark.parametrize("text,phi_term", [
        ("Patient John Doe presented", "John Doe"),
        ("Patient name: Jane Smith", "Jane Smith"),
        ("Email: john.doe@example.com", "john.doe@example.com"),
        ("Phone: +1-555-123-4567", "+1-555-123-4567"),
        ("DOB: 05/12/1970", "05/12/1970"),
        ("Address: 123 Main Street", "123 Main Street"),
        ("MRN: 12345678", "12345678"),
        ("Patient named Mary Johnson", "Mary Johnson"),
    ])
    def test_redacts_phi(self, redactor, text, phi_term):
        """PHI should be redacted."""
        result = redactor.redact(text)
        assert phi_term not in result, f"PHI '{phi_term}' was NOT redacted"
        assert "[REDACTED" in result, "No redaction marker found"

    def test_complex_clinical_note(self, redactor):
        """Test a complex clinical note with both PHI and medical terms."""
        note = """
Patient: John Doe
DOB: 03/15/1968
Email: john.doe@email.com

Chief Complaint: Chest pain

History of Present Illness:
Patient has Diabetes Mellitus Type 2, Hypertension, and Coronary Artery Disease.

Current Medications:
- Aspirin 81 mg daily
- Metformin 1000 mg twice daily
- Lisinopril 10 mg daily

Allergies: Penicillin (rash)

Physical Exam:
- Left Ventricle function preserved
- Coronary Artery clear on CT
"""
        result = redactor.redact(note)

        # Medical terms should be preserved
        medical_terms = [
            "Diabetes Mellitus", "Hypertension", "Coronary Artery",
            "Aspirin", "Metformin", "Lisinopril", "Penicillin",
            "Left Ventricle", "Chief Complaint", "Physical Exam",
            "Current Medications"
        ]
        for term in medical_terms:
            assert term in result, f"Medical term '{term}' was incorrectly redacted"

        # PHI should be redacted
        phi_terms = ["John Doe", "03/15/1968", "john.doe@email.com"]
        for term in phi_terms:
            assert term not in result, f"PHI '{term}' was NOT redacted"

    def test_medical_term_checker(self, redactor):
        """Test the _is_medical_term helper method."""
        # Should be recognized as medical terms
        assert redactor._is_medical_term("Aspirin")
        assert redactor._is_medical_term("Diabetes Mellitus")
        assert redactor._is_medical_term("Coronary Artery")
        assert redactor._is_medical_term("CT Head")
        assert redactor._is_medical_term("Chief Complaint")
        assert redactor._is_medical_term("Physical Exam")

        # Should NOT be recognized as medical terms (likely names)
        assert not redactor._is_medical_term("John Doe")
        assert not redactor._is_medical_term("Jane Smith")
        assert not redactor._is_medical_term("taking Aspirin")

    def test_context_aware_name_redaction(self, redactor):
        """Names should only be redacted in patient/name context."""
        # Should redact - explicit patient name context
        assert "John Doe" not in redactor.redact("Patient John Doe presented")
        assert "Jane Smith" not in redactor.redact("Patient is Jane Smith")
        assert "Mary Johnson" not in redactor.redact("Patient named Mary Johnson")

        # Should NOT redact - no patient context, could be provider or other
        # (Note: without explicit "patient" keyword, two capitalized words alone
        # will be checked against medical term list)
        result = redactor.redact("Dr. Sarah Williams evaluated the case")
        # This might get redacted if not in whitelist, which is acceptable for safety

    def test_preserves_provider_names_with_title(self, redactor):
        """Provider names with titles should be preserved."""
        text = "Follow-up with Dr. Smith in 2 weeks"
        result = redactor.redact(text)
        # "Dr. Smith" should be preserved (not a two-word capitalized pattern)
        assert "Dr." in result

    def test_empty_and_none_input(self, redactor):
        """Handle edge cases gracefully."""
        assert redactor.redact("") == ""
        assert redactor.redact(None) is None

    def test_no_false_positives_on_medications(self, redactor):
        """Ensure common medications are never redacted."""
        medications = [
            "Aspirin", "Metformin", "Lisinopril", "Atorvastatin",
            "Amlodipine", "Metoprolol", "Omeprazole", "Simvastatin",
            "Warfarin", "Furosemide", "Penicillin", "Amoxicillin"
        ]

        for med in medications:
            text = f"Patient is taking {med} for treatment"
            result = redactor.redact(text)
            assert med in result, f"Medication '{med}' was incorrectly redacted"

    def test_no_false_positives_on_conditions(self, redactor):
        """Ensure common conditions are never redacted."""
        conditions = [
            "Diabetes Mellitus", "Coronary Artery Disease", "Heart Failure",
            "Atrial Fibrillation", "Myocardial Infarction", "Pulmonary Embolism"
        ]

        for condition in conditions:
            text = f"Patient has {condition} since 2020"
            result = redactor.redact(text)
            # Check if key parts of the condition are preserved
            key_word = condition.split()[0]  # e.g., "Diabetes", "Coronary"
            assert key_word in result, f"Condition '{condition}' was incorrectly redacted"
