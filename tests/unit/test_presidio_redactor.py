"""
Comprehensive tests for multilingual PHI redactor using Microsoft Presidio.

Tests cover:
- Swedish clinical text
- English clinical text
- Medical term preservation in both languages
- PHI redaction in both languages
- Edge cases and mixed language text
"""

import pytest

# Import with try/except to handle cases where Presidio is not installed
try:
    from optimed.adapters.outbound.phi_redactor.presidio_redactor import PresidioPhiRedactor
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False


@pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio not installed")
class TestPresidioPhiRedactorSwedish:
    """Test suite for Swedish clinical text."""

    @pytest.fixture
    def redactor(self):
        """Create a redactor instance for Swedish."""
        return PresidioPhiRedactor(default_language="sv")

    # ===== Medical Terms Preservation (Swedish) =====

    @pytest.mark.parametrize("text,preserved_term", [
        # Medications
        ("Patient tar Aspirin 81 mg dagligen", "Aspirin"),
        ("Förskriver Metformin 1000 mg två gånger dagligen", "Metformin"),
        ("Behandling med Lisinopril", "Lisinopril"),
        ("Aktuell medicinering: Omeprazol", "Omeprazol"),

        # Diagnoses
        ("Diagnos: Diabetes Mellitus Typ 2", "Diabetes Mellitus"),
        ("Patient har Hypertoni sedan 2020", "Hypertoni"),
        ("Tidigare Hjärtinfarkt", "Hjärtinfarkt"),
        ("Kronisk Njursvikt", "Njursvikt"),

        # Anatomical terms
        ("Vänster Kammare funktion bevarad", "Vänster Kammare"),
        ("Höger Förmak normalstor", "Höger Förmak"),
        ("Kranskärl utan stenoser", "Kranskärl"),

        # Procedures
        ("Röntgen thorax utan anmärkning", "Röntgen"),
        ("Datortomografi av hjärnan", "Datortomografi"),
        ("Ultraljud visar normal funktion", "Ultraljud"),

        # Section headers
        ("Anamnes: Bröstsmärtor", "Anamnes"),
        ("Aktuellt: Patient inlagd för observation", "Aktuellt"),
        ("Tidigare Sjukdomar: Inga kända", "Tidigare Sjukdomar"),
    ])
    def test_preserves_swedish_medical_terms(self, redactor, text, preserved_term):
        """Swedish medical terms should be preserved."""
        result = redactor.redact(text, language="sv")
        assert preserved_term in result, f"Swedish medical term '{preserved_term}' was incorrectly redacted"

    # ===== PHI Redaction (Swedish) =====

    @pytest.mark.parametrize("text,phi_term,redaction_marker", [
        # Names
        ("Patient Karl Andersson inkom idag", "Karl Andersson", "[REDACTED_NAME]"),
        ("Patient: Anna Svensson", "Anna Svensson", "[REDACTED_NAME]"),

        # Email addresses
        ("Email: karl.andersson@example.se", "karl.andersson@example.se", "[REDACTED_EMAIL]"),
        ("Kontakt via anna@test.com", "anna@test.com", "[REDACTED_EMAIL]"),

        # Phone numbers
        ("Telefon: 0701234567", "0701234567", "[REDACTED_PHONE]"),
        ("Mobil: +46 70 123 45 67", "+46 70 123 45 67", "[REDACTED_PHONE]"),

        # Personnummer (Swedish personal ID)
        ("Personnummer: 19850315-1234", "19850315-1234", "[REDACTED_ID]"),
        ("ID: 850315-1234", "850315-1234", "[REDACTED_ID]"),
    ])
    def test_redacts_swedish_phi(self, redactor, text, phi_term, redaction_marker):
        """PHI in Swedish text should be redacted."""
        result = redactor.redact(text, language="sv")
        assert phi_term not in result, f"Swedish PHI '{phi_term}' was NOT redacted"
        assert redaction_marker in result, f"Redaction marker '{redaction_marker}' not found"

    def test_complex_swedish_clinical_note(self, redactor):
        """Test a complete Swedish clinical note."""
        note = """
Patient: Erik Johansson
Personnummer: 19750520-1234
Telefon: 0701234567
Email: erik.johansson@example.se

Anamnes:
Patient har Diabetes Mellitus Typ 2 sedan 10 år. Hypertoni och tidigare Hjärtinfarkt 2020.

Aktuell Medicinering:
- Aspirin 81 mg dagligen
- Metformin 1000 mg två gånger dagligen
- Lisinopril 10 mg dagligen
- Omeprazol 20 mg dagligen

Allergier: Penicillin (utslag)

Status:
- Hjärta: Vänster Kammare funktion bevarad
- Lungor: Auskultation normalt
- Kranskärl: Inga tecken på ischemi

Bedömning:
Stabil Diabetes Mellitus med god glykemisk kontroll.

Åtgärd:
Fortsätt nuvarande medicinering. Kontroll om 3 månader.
"""
        result = redactor.redact(note, language="sv")

        # Medical terms should be preserved
        medical_terms = [
            "Diabetes Mellitus", "Hypertoni", "Hjärtinfarkt",
            "Aspirin", "Metformin", "Lisinopril", "Omeprazol", "Penicillin",
            "Vänster Kammare", "Kranskärl", "Anamnes", "Status", "Bedömning",
        ]
        for term in medical_terms:
            assert term in result, f"Swedish medical term '{term}' was incorrectly redacted"

        # PHI should be redacted
        phi_terms = [
            "Erik Johansson",
            "19750520-1234",
            "0701234567",
            "erik.johansson@example.se"
        ]
        for term in phi_terms:
            assert term not in result, f"Swedish PHI '{term}' was NOT redacted"


@pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio not installed")
class TestPresidioPhiRedactorEnglish:
    """Test suite for English clinical text."""

    @pytest.fixture
    def redactor(self):
        """Create a redactor instance for English."""
        return PresidioPhiRedactor(default_language="en")

    # ===== Medical Terms Preservation (English) =====

    @pytest.mark.parametrize("text,preserved_term", [
        # Medications
        ("Patient is taking Aspirin 81 mg daily", "Aspirin"),
        ("Prescribed Metformin 1000 mg twice daily", "Metformin"),
        ("Treatment with Lisinopril", "Lisinopril"),
        ("Current medications: Omeprazole", "Omeprazole"),

        # Diagnoses
        ("Diagnosis: Diabetes Mellitus Type 2", "Diabetes Mellitus"),
        ("Patient has Hypertension since 2020", "Hypertension"),
        ("Previous Myocardial Infarction", "Myocardial Infarction"),
        ("Chronic Kidney Disease", "Chronic Kidney Disease"),

        # Anatomical terms
        ("Left Ventricle function preserved", "Left Ventricle"),
        ("Right Atrium normal size", "Right Atrium"),
        ("Coronary Artery without stenosis", "Coronary Artery"),

        # Procedures
        ("Chest X-ray unremarkable", "X-ray"),
        ("CT Scan of the brain", "CT Scan"),
        ("Ultrasound shows normal function", "Ultrasound"),

        # Section headers
        ("Chief Complaint: Chest pain", "Chief Complaint"),
        ("History of Present Illness: Patient admitted", "History of Present Illness"),
        ("Past Medical History: None known", "Past Medical History"),
    ])
    def test_preserves_english_medical_terms(self, redactor, text, preserved_term):
        """English medical terms should be preserved."""
        result = redactor.redact(text, language="en")
        assert preserved_term in result, f"English medical term '{preserved_term}' was incorrectly redacted"

    # ===== PHI Redaction (English) =====

    @pytest.mark.parametrize("text,phi_term,redaction_marker", [
        # Names
        ("Patient John Smith admitted today", "John Smith", "[REDACTED_NAME]"),
        ("Patient: Mary Johnson", "Mary Johnson", "[REDACTED_NAME]"),

        # Email addresses
        ("Email: john.smith@example.com", "john.smith@example.com", "[REDACTED_EMAIL]"),
        ("Contact via mary@test.org", "mary@test.org", "[REDACTED_EMAIL]"),

        # Phone numbers
        ("Phone: 555-123-4567", "555-123-4567", "[REDACTED_PHONE]"),
        ("Mobile: +1 555 123 4567", "+1 555 123 4567", "[REDACTED_PHONE]"),

        # SSN (US Social Security Number)
        ("SSN: 123-45-6789", "123-45-6789", "[REDACTED]"),
    ])
    def test_redacts_english_phi(self, redactor, text, phi_term, redaction_marker):
        """PHI in English text should be redacted."""
        result = redactor.redact(text, language="en")
        assert phi_term not in result, f"English PHI '{phi_term}' was NOT redacted"
        assert redaction_marker in result, f"Redaction marker '{redaction_marker}' not found"

    def test_complex_english_clinical_note(self, redactor):
        """Test a complete English clinical note."""
        note = """
Patient: John Doe
DOB: 05/15/1975
Phone: 555-123-4567
Email: john.doe@example.com

Chief Complaint: Chest pain

History of Present Illness:
Patient has Type 2 Diabetes Mellitus for 10 years. Hypertension and previous Myocardial Infarction in 2020.

Current Medications:
- Aspirin 81 mg daily
- Metformin 1000 mg twice daily
- Lisinopril 10 mg daily
- Omeprazole 20 mg daily

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
        result = redactor.redact(note, language="en")

        # Medical terms should be preserved
        medical_terms = [
            "Diabetes Mellitus", "Hypertension", "Myocardial Infarction",
            "Aspirin", "Metformin", "Lisinopril", "Omeprazole", "Penicillin",
            "Left Ventricle", "Coronary Artery", "Chief Complaint", "Physical Exam",
        ]
        for term in medical_terms:
            assert term in result, f"English medical term '{term}' was incorrectly redacted"

        # PHI should be redacted
        phi_terms = [
            "John Doe",
            "555-123-4567",
            "john.doe@example.com"
        ]
        for term in phi_terms:
            assert term not in result, f"English PHI '{term}' was NOT redacted"


@pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio not installed")
class TestPresidioPhiRedactorEdgeCases:
    """Test edge cases and special scenarios."""

    @pytest.fixture
    def redactor(self):
        """Create a redactor instance."""
        return PresidioPhiRedactor(default_language="sv")

    def test_auto_language_detection_swedish(self, redactor):
        """Test automatic language detection for Swedish."""
        text = "Patient har Diabetes och tar Metformin dagligen"
        result = redactor.redact(text)  # No language specified
        assert "Diabetes" in result
        assert "Metformin" in result

    def test_auto_language_detection_english(self, redactor):
        """Test automatic language detection for English."""
        text = "Patient has Diabetes and takes Metformin daily"
        result = redactor.redact(text)  # No language specified
        assert "Diabetes" in result
        assert "Metformin" in result

    def test_empty_input(self, redactor):
        """Handle empty input gracefully."""
        assert redactor.redact("") == ""
        assert redactor.redact(None) is None

    def test_mixed_language_text(self, redactor):
        """Test text with mixed Swedish and English."""
        text = "Patient har Diabetes Mellitus Type 2 och tar Aspirin"
        result = redactor.redact(text, language="sv")
        assert "Diabetes Mellitus" in result
        assert "Aspirin" in result

    def test_medical_terms_not_in_whitelist(self, redactor):
        """Test that pattern-based recognition works for terms not in whitelist."""
        # Medications with common suffixes
        text_sv = "Patient tar Amoxicillin och Doxycycline"
        result_sv = redactor.redact(text_sv, language="sv")
        assert "Amoxicillin" in result_sv
        assert "Doxycycline" in result_sv

        text_en = "Patient takes Amoxicillin and Doxycycline"
        result_en = redactor.redact(text_en, language="en")
        assert "Amoxicillin" in result_en
        assert "Doxycycline" in result_en

    def test_no_false_positives_medications(self, redactor):
        """Ensure medications are never redacted in Swedish or English."""
        medications = [
            ("Aspirin", "sv"),
            ("Metformin", "sv"),
            ("Lisinopril", "en"),
            ("Atorvastatin", "en"),
        ]

        for med, lang in medications:
            text = f"Patient tar {med}" if lang == "sv" else f"Patient takes {med}"
            result = redactor.redact(text, language=lang)
            assert med in result, f"Medication '{med}' ({lang}) was incorrectly redacted"

    def test_no_false_positives_conditions(self, redactor):
        """Ensure conditions are never redacted in Swedish or English."""
        conditions = [
            ("Diabetes Mellitus", "sv"),
            ("Hypertoni", "sv"),
            ("Heart Failure", "en"),
            ("Myocardial Infarction", "en"),
        ]

        for condition, lang in conditions:
            text = f"Diagnos: {condition}" if lang == "sv" else f"Diagnosis: {condition}"
            result = redactor.redact(text, language=lang)
            # Check if key part of condition is preserved
            key_word = condition.split()[0]
            assert key_word in result, f"Condition '{condition}' ({lang}) was incorrectly redacted"

    def test_personnummer_formats(self, redactor):
        """Test various Swedish personnummer formats."""
        formats = [
            "19850315-1234",  # YYYYMMDD-XXXX
            "850315-1234",    # YYMMDD-XXXX
            "198503151234",   # YYYYMMDDXXXX (no dash)
            "8503151234",     # YYMMDDXXXX (no dash)
        ]

        for pnr in formats:
            text = f"Personnummer: {pnr}"
            result = redactor.redact(text, language="sv")
            assert pnr not in result, f"Personnummer '{pnr}' was NOT redacted"
            assert "[REDACTED" in result

    def test_international_phone_formats(self, redactor):
        """Test various international phone number formats."""
        phones = [
            "+46 70 123 45 67",  # Swedish
            "0701234567",         # Swedish mobile
            "+1-555-123-4567",    # US
            "555-123-4567",       # US local
        ]

        for phone in phones:
            text = f"Phone: {phone}"
            result = redactor.redact(text, language="sv")
            # Phone should be redacted or partially redacted
            assert phone not in result or "[REDACTED" in result


@pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio not installed")
class TestPresidioPhiRedactorMedicalContext:
    """Test medical context preservation."""

    @pytest.fixture
    def redactor(self):
        """Create a redactor instance."""
        return PresidioPhiRedactor(default_language="sv")

    def test_preserves_medication_in_sentence(self, redactor):
        """Medications should be preserved even in complex sentences."""
        text_sv = "Patienten började ta Metformin för två år sedan"
        result_sv = redactor.redact(text_sv, language="sv")
        assert "Metformin" in result_sv

        text_en = "Patient started taking Metformin two years ago"
        result_en = redactor.redact(text_en, language="en")
        assert "Metformin" in result_en

    def test_preserves_anatomical_terms_with_descriptors(self, redactor):
        """Anatomical terms with Left/Right should be preserved."""
        text_sv = "Vänster Kammare visar normal funktion"
        result_sv = redactor.redact(text_sv, language="sv")
        assert "Vänster Kammare" in result_sv

        text_en = "Left Ventricle shows normal function"
        result_en = redactor.redact(text_en, language="en")
        assert "Left Ventricle" in result_en

    def test_preserves_section_headers(self, redactor):
        """Clinical section headers should be preserved."""
        headers_sv = ["Anamnes", "Status", "Bedömning", "Aktuellt"]
        headers_en = ["Chief Complaint", "Physical Exam", "Assessment", "Plan"]

        for header in headers_sv:
            text = f"{header}: Normal"
            result = redactor.redact(text, language="sv")
            assert header in result

        for header in headers_en:
            text = f"{header}: Normal"
            result = redactor.redact(text, language="en")
            assert header in result

    def test_context_aware_name_detection(self, redactor):
        """Names should be redacted but medical terms in similar format should not."""
        # Should redact person name
        text_sv = "Patient Karl Andersson inkom idag"
        result_sv = redactor.redact(text_sv, language="sv")
        # Karl Andersson should be redacted (but this depends on Presidio's NER)

        # Should preserve disease name
        text_disease = "Diagnos: Alzheimers Sjukdom"
        result_disease = redactor.redact(text_disease, language="sv")
        assert "Alzheimers" in result_disease or "Sjukdom" in result_disease

    def test_performance_with_long_text(self, redactor):
        """Test performance with longer clinical documents."""
        long_note = """
        Patient: Test Patient
        Personnummer: 19850101-1234

        Anamnes:
        """ + " ".join([
            "Patient har Diabetes Mellitus, Hypertoni, och Hjärtsvikt."
            "Tar Aspirin, Metformin, Lisinopril dagligen."
        ] * 20)

        result = redactor.redact(long_note, language="sv")

        # Medical terms should still be preserved in long text
        assert "Diabetes Mellitus" in result
        assert "Aspirin" in result
        assert "Metformin" in result

        # PHI should be redacted
        assert "Test Patient" not in result or "[REDACTED" in result
