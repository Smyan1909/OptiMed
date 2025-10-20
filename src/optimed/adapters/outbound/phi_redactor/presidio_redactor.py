"""
Multilingual PHI redactor using Microsoft Presidio.

This redactor supports Swedish, English, and other languages while preserving
medical terminology (medications, diagnoses, anatomical terms) in all languages.

Key Features:
- Language-agnostic PHI detection (names, phone numbers, addresses, etc.)
- Swedish personnummer detection
- Medical term preservation using custom allow lists
- GDPR compliant
- High performance suitable for RAM-only processing
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set
from functools import lru_cache

try:
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern, RecognizerResult
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False

from optimed.core.ports import PhiRedactorPort
from optimed.core.logging_utils import get_logger

logger = get_logger(__name__)


class PresidioPhiRedactor(PhiRedactorPort):
    """
    Multilingual PHI redactor using Microsoft Presidio with medical term awareness.

    Supports:
    - Swedish, English, and other languages
    - Swedish personnummer (YYYYMMDD-XXXX format)
    - International phone formats
    - Medical term preservation in multiple languages
    - GDPR compliant redaction
    """

    def __init__(self, default_language: str = "sv"):
        """
        Initialize the Presidio redactor.

        Args:
            default_language: Default language code (ISO 639-1), e.g., 'sv' for Swedish, 'en' for English
        """
        if not PRESIDIO_AVAILABLE:
            raise ImportError(
                "Presidio is not installed. Install with: pip install presidio-analyzer presidio-anonymizer"
            )

        self.default_language = default_language

        # Initialize Presidio analyzer and anonymizer
        self._analyzer: Optional[AnalyzerEngine] = None
        self._anonymizer: Optional[AnonymizerEngine] = None

        # Medical terminology whitelists (multilingual)
        self.medical_terms = self._build_medical_whitelist()

        # Compile regex patterns for medical terms
        self.medical_patterns = self._compile_medical_patterns()

        logger.info(f"Initialized PresidioPhiRedactor with default language: {default_language}")

    @property
    def analyzer(self) -> AnalyzerEngine:
        """Lazy initialization of Presidio analyzer."""
        if self._analyzer is None:
            self._analyzer = self._create_analyzer()
        return self._analyzer

    @property
    def anonymizer(self) -> AnonymizerEngine:
        """Lazy initialization of Presidio anonymizer."""
        if self._anonymizer is None:
            self._anonymizer = AnonymizerEngine()
        return self._anonymizer

    def _create_analyzer(self) -> AnalyzerEngine:
        """Create and configure Presidio analyzer with custom recognizers."""
        # Configure NLP engine for multiple languages
        # Swedish (sv) and English (en) support via spaCy
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": "sv", "model_name": "sv_core_news_sm"},
                {"lang_code": "en", "model_name": "en_core_web_sm"},
            ],
        }

        try:
            provider = NlpEngineProvider(nlp_configuration=configuration)
            nlp_engine = provider.create_engine()
        except Exception as e:
            logger.warning(f"Could not initialize spaCy models: {e}. Using default configuration.")
            # Fallback to default configuration
            nlp_engine = None

        # Create analyzer with or without NLP engine
        if nlp_engine:
            analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        else:
            analyzer = AnalyzerEngine()

        # Add custom recognizers
        analyzer.registry.add_recognizer(self._create_personnummer_recognizer())
        analyzer.registry.add_recognizer(self._create_phone_recognizer())

        return analyzer

    def _create_personnummer_recognizer(self) -> PatternRecognizer:
        """Create recognizer for Swedish personnummer (personal identity numbers)."""
        # Swedish personnummer formats:
        # YYYYMMDD-XXXX or YYYYMMDDXXXX (8 digits + 4 digits)
        # YYMMDD-XXXX or YYMMDDXXXX (6 digits + 4 digits)
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
            supported_language="sv",  # CRITICAL: Must specify supported language!
        )

        # Also support English contexts (e.g., "Patient ID: 850315-1234")
        recognizer.supported_languages = ["sv", "en"]

        return recognizer

    def _create_phone_recognizer(self) -> PatternRecognizer:
        """
        Create enhanced phone number recognizer for international formats.

        Note: This recognizer is more conservative to avoid false positives with
        medication dosages (e.g., "500 mg" should not be detected as phone number).
        We support both Swedish and English.
        """
        phone_patterns = [
            # International format with + prefix
            Pattern(
                name="international_phone_with_plus",
                regex=r"\+\d{1,3}[\s-]?\(?\d{1,4}\)?[\s-]?\d{1,4}[\s-]?\d{1,9}",
                score=0.85,
            ),
            # Full phone numbers with multiple segments: "555-123-4567"
            Pattern(
                name="phone_full_with_separators",
                regex=r"\b\d{3}[-\s]\d{3}[-\s]\d{4}\b",
                score=0.9,
            ),
            # Short phone numbers with separator: "555-1234" (7 digits total)
            # Must have context words to avoid false positives
            Pattern(
                name="phone_short_with_separator",
                regex=r"\b\d{3,4}[-\s]\d{4}\b",
                score=0.75,
            ),
            # Swedish format: 070-1234567 or 0701234567
            Pattern(
                name="swedish_phone",
                regex=r"\b0\d{1,3}[-\s]?\d{6,8}\b",
                score=0.8,
            ),
        ]

        # Support both Swedish and English by setting supported_languages (plural)
        recognizer = PatternRecognizer(
            supported_entity="PHONE_NUMBER",
            patterns=phone_patterns,
            context=["phone", "tel", "telefon", "mobile", "mobil", "contact", "call"],
            supported_language="sv",
        )

        # Also add support for English
        recognizer.supported_languages = ["sv", "en"]

        return recognizer

    def _build_medical_whitelist(self) -> Dict[str, Set[str]]:
        """
        Build comprehensive medical terminology whitelist for multiple languages.

        Returns:
            Dictionary mapping language codes to sets of medical terms
        """
        return {
            # Swedish medical terms
            "sv": {
                # Medications (Swedish)
                "Aspirin", "Metformin", "Lisinopril", "Atorvastatin", "Amlodipine",
                "Metoprolol", "Omeprazol", "Simvastatin", "Losartan", "Gabapentin",
                "Furosemid", "Warfarin", "Insulin", "Penicillin", "Amoxicillin",
                "Paracetamol", "Ibuprofen", "Morfin", "Heparin", "Dopamin",

                # Conditions/Diagnoses (Swedish)
                "Diabetes Mellitus", "Typ 2 Diabetes", "Hypertoni", "Hjärtsvikt",
                "Hjärtinfarkt", "Förmaksflimmer", "Njursvikt", "Stroke",
                "Lunginflammation", "Astma", "KOL", "Cancer", "Leukemi",
                "Reumatoid Artrit", "Crohns Sjukdom", "Multipel Skleros",

                # Anatomical terms (Swedish)
                "Hjärta", "Vänster Kammare", "Höger Förmak", "Aorta",
                "Kranskärl", "Lungartär", "Njure", "Lever", "Mjälte",

                # Procedures (Swedish)
                "Röntgen", "Datortomografi", "Magnetkamera", "Ultraljud",
                "Biopsi", "Operation", "Blodprov", "EKG",

                # Section headers (Swedish)
                "Anamnes", "Status", "Bedömning", "Åtgärd", "Diagnos",
                "Medicinering", "Aktuellt", "Tidigare Sjukdomar", "Läkemedel",
                "Allergier", "Socialt", "Familjeanamnes",

                # Clinical field labels (Swedish) - NEVER redact these
                "Rum", "Alert", "Orienterad", "Neuro", "SpO2", "BP", "HR", "RR",
                "Temp", "GCS", "LOC", "Vitals", "Ögon", "Lungor", "Hjärta",
                "Buk", "MSK", "Hud", "Psyk", "Const",

                # Demographics (Swedish) - NOT PHI
                "Man", "Kvinna", "Latino", "Latinamerikansk", "Hispanisk",
                "Icke-Hispanisk", "Kaukasisk", "Afrikansk", "Asiatisk",
                "Vit", "Svart", "Amerikansk", "Europeisk",

                # Clinical descriptors (Swedish)
                "marknivå", "hög energi", "låg energi", "mekanisk", "trubbigt",
                "penetrerande", "fall", "trauma", "skada",
            },

            # English medical terms
            "en": {
                # Medications (English)
                "Aspirin", "Metformin", "Lisinopril", "Atorvastatin", "Amlodipine",
                "Metoprolol", "Omeprazole", "Simvastatin", "Losartan", "Gabapentin",
                "Hydrochlorothiazide", "Levothyroxine", "Warfarin", "Furosemide",
                "Albuterol", "Prednisone", "Insulin", "Penicillin", "Amoxicillin",
                "Ibuprofen", "Acetaminophen", "Morphine", "Heparin", "Dopamine",

                # Conditions/Diagnoses (English)
                "Diabetes Mellitus", "Type 2 Diabetes", "Hypertension", "Heart Failure",
                "Myocardial Infarction", "Atrial Fibrillation", "Chronic Kidney Disease",
                "Stroke", "Pneumonia", "Asthma", "COPD", "Cancer", "Leukemia",
                "Rheumatoid Arthritis", "Crohn's Disease", "Multiple Sclerosis",
                "Coronary Artery Disease", "Pulmonary Embolism", "Deep Vein Thrombosis",

                # Anatomical terms (English)
                "Heart", "Left Ventricle", "Right Atrium", "Aorta", "Aortic Valve",
                "Mitral Valve", "Coronary Artery", "Pulmonary Artery", "Carotid Artery",
                "Femoral Vein", "Kidney", "Liver", "Spleen", "Lung",

                # Procedures (English)
                "X-ray", "CT Scan", "MRI", "Ultrasound", "Biopsy",
                "Surgery", "Blood Test", "ECG", "EKG", "Echocardiogram",

                # Section headers (English)
                "Chief Complaint", "History of Present Illness", "Past Medical History",
                "Current Medications", "Allergies", "Social History", "Family History",
                "Physical Exam", "Assessment", "Plan", "Differential Diagnosis",

                # Clinical field labels (English) - NEVER redact these
                "Room", "Alert", "Oriented", "Neuro", "SpO2", "BP", "HR", "RR",
                "Temp", "Temperature", "GCS", "LOC", "Vitals", "Const", "Eyes",
                "Pulm", "Cards", "Abdomen", "MSK", "Skin", "Psych",

                # Demographics (English) - NOT PHI
                "Male", "Female", "Latino", "Latina", "Hispanic", "Non-Hispanic",
                "Not Hispanic", "Caucasian", "African", "Asian", "White", "Black",
                "American", "European", "Pacific Islander",

                # Clinical descriptors (English)
                "ground level", "high energy", "low energy", "mechanical", "blunt",
                "penetrating", "fall", "trauma", "injury", "assault",
            },

            # Common terms across all languages (typically Latin-based medical terms)
            "common": {
                "COVID-19", "HIV", "AIDS", "SARS-CoV-2", "HPV", "HBV", "HCV",
                "DNA", "RNA", "BMI", "BP", "HR", "RR", "SpO2", "mmHg",
                # Clinical notation
                "x1", "x2", "x3", "x4", "x5", "x6",
            },
        }

    def _compile_medical_patterns(self) -> List[re.Pattern]:
        """
        Compile regex patterns for medical terminology recognition.

        These patterns work across multiple languages by focusing on
        structural features of medical terms.
        """
        patterns = [
            # Medication suffixes (language-independent)
            re.compile(r"\b[A-Z][a-z]+(?:cillin|mycin|dipine|pril|sartan|statin|zole|cycline|oxin|olol|azole|afil|rin)\b"),

            # Disease patterns with descriptors
            re.compile(r"\b[A-Z][a-z]+\s+(?:Mellitus|Disease|Syndrome|Disorder|Failure|Attack|Stroke|Sjukdom|Syndrom)\b"),

            # Type/Stage descriptors (works in Swedish and English)
            re.compile(r"\b(?:Type|Typ|Stage)\s+[A-Z0-9]+\s+[A-Z][a-z]+\b"),

            # Anatomical structures
            re.compile(r"\b(?:Left|Right|Vänster|Höger)\s+(?:Ventricle|Atrium|Kammare|Förmak|Lung|Kidney|Njure)\b"),

            # Imaging with body part
            re.compile(r"\b(?:CT|MRI|X-ray|Röntgen|Ultrasound|Ultraljud)\s+[A-Z][a-z]+\b"),

            # Procedures
            re.compile(r"\b[A-Z][a-z]+\s+(?:Scan|Biopsy|Surgery|Operation|Test|Prov)\b"),

            # Acute/Chronic conditions
            re.compile(r"\b(?:Acute|Chronic|Akut|Kronisk)\s+[A-Z][a-z]+\b"),

            # Vertebral levels: L1-L5 (lumbar), C1-C7 (cervical), T1-T12 (thoracic), S1-S5 (sacral)
            re.compile(r"\b[LCTS]\d{1,2}\b"),
        ]

        return patterns

    @lru_cache(maxsize=1000)
    def _is_medical_term(self, text: str, language: str = "sv") -> bool:
        """
        Check if text is a medical term that should be preserved.

        Args:
            text: Text to check
            language: Language code

        Returns:
            True if text is a medical term, False otherwise
        """
        # Check for vertebral levels (L3, C5, T12, etc.) - ALWAYS preserve
        if re.match(r"^[LCTS]\d{1,2}$", text):
            return True

        # Check against whitelists (exact match)
        if text in self.medical_terms.get(language, set()):
            return True

        if text in self.medical_terms.get("common", set()):
            return True

        # Check all language whitelists if not found in primary language
        for lang_terms in self.medical_terms.values():
            if text in lang_terms:
                return True

        # Case-insensitive check for single words (clinical field labels)
        # This helps catch "oriented" when whitelist has "Oriented"
        if " " not in text.strip():
            text_lower = text.lower()
            for lang_terms in self.medical_terms.values():
                for term in lang_terms:
                    if term.lower() == text_lower:
                        return True

        # For multi-word entities, check if ANY word is a whitelisted medical term
        # This handles cases like "Oriented x3" where "Oriented" is whitelisted
        words = text.split()
        if len(words) > 1:
            for word in words:
                # Strip punctuation
                word_clean = word.strip(".,;:!?()[]{}\"'")
                if word_clean and self._is_medical_term(word_clean, language):
                    return True

        # Check against regex patterns
        for pattern in self.medical_patterns:
            if pattern.search(text):
                return True

        # Check for medication suffixes in words
        if len(words) == 1:
            word = words[0]
            med_suffixes = [
                "cillin", "mycin", "dipine", "pril", "sartan", "statin",
                "zole", "cycline", "oxin", "olol", "azole", "afil", "rin"
            ]
            if any(word.lower().endswith(suffix) for suffix in med_suffixes):
                return True

        return False

    def _detect_language(self, text: str) -> str:
        """
        Simple language detection based on common Swedish words.

        Args:
            text: Text to analyze

        Returns:
            Language code ('sv' or 'en')
        """
        swedish_words = {
            "är", "och", "att", "det", "som", "för", "på", "med", "av", "till",
            "har", "kan", "från", "vid", "den", "eller", "inte", "om", "ett",
            "patient", "diagnos", "läkemedel", "behandling", "sjukdom", "anamnes"
        }

        words = set(text.lower().split())
        swedish_count = len(words & swedish_words)

        # If more than 5% of words are Swedish, assume Swedish
        if len(words) > 0 and swedish_count / len(words) > 0.05:
            return "sv"

        return "en"

    def _is_date_of_birth(self, text: str, start: int, end: int) -> bool:
        """
        Determine if a detected date is likely a date of birth (DOB).

        Args:
            text: Full text
            start: Start position of date
            end: End position of date

        Returns:
            True if date appears to be DOB, False otherwise
        """
        # Extract surrounding context (30 chars before and after)
        context_start = max(0, start - 30)
        context_end = min(len(text), end + 30)
        context = text[context_start:context_end].lower()

        # DOB indicators
        dob_indicators = [
            "dob", "date of birth", "born", "född", "födelsedatum",
            "birthday", "födelsedag", "birth date"
        ]

        # Check if any DOB indicator is in context
        if any(indicator in context for indicator in dob_indicators):
            return True

        # Extract the date string itself
        date_str = text[start:end]

        # Full dates (DD/MM/YYYY or YYYY-MM-DD) are more likely to be DOB
        # if they're in a specific format
        full_date_patterns = [
            r"\d{1,2}/\d{1,2}/\d{4}",  # DD/MM/YYYY or MM/DD/YYYY
            r"\d{4}-\d{1,2}-\d{1,2}",  # YYYY-MM-DD
            r"\d{1,2}\.\d{1,2}\.\d{4}", # DD.MM.YYYY
        ]

        import re
        for pattern in full_date_patterns:
            if re.match(pattern, date_str):
                # Check if it's NOT in a clinical context
                clinical_context = [
                    "since", "sedan", "for", "in", "på", "ago", "follow-up",
                    "kontroll", "visit", "besök", "months", "månader", "years",
                    "år", "weeks", "veckor", "days", "dagar"
                ]
                if not any(word in context for word in clinical_context):
                    # Likely DOB
                    return True

        return False

    def _is_clinical_temporal_reference(self, text: str, start: int, end: int) -> bool:
        """
        Determine if a detected date/time is a clinical temporal reference
        that should be preserved (durations, relative times, years only, frequencies).

        Args:
            text: Full text
            start: Start position of date
            end: End position of date

        Returns:
            True if it's a clinical temporal reference to preserve, False otherwise
        """
        # Extract surrounding context
        context_start = max(0, start - 30)
        context_end = min(len(text), end + 30)
        context_before = text[context_start:start].lower()
        context_after = text[end:context_end].lower()

        # Extract the matched text
        matched_text = text[start:end].lower()

        # Duration indicators (should preserve)
        duration_indicators = [
            "for", "sedan", "ago", "since", "över"
        ]
        if any(indicator in context_before for indicator in duration_indicators):
            return True

        # Relative time indicators (should preserve)
        relative_time_words = [
            "months", "månader", "weeks", "veckor", "days", "dagar",
            "years", "år", "month", "månad", "week", "vecka", "day", "dag"
        ]
        if any(word in matched_text or word in context_after for word in relative_time_words):
            return True

        # Frequency/schedule indicators (should preserve)
        frequency_indicators = [
            "daily", "dagligen", "twice", "två gånger", "once", "en gång",
            "every", "varje", "per", "weekly", "veckovis", "monthly", "månadsvis"
        ]
        if any(indicator in context_before or indicator in context_after for indicator in frequency_indicators):
            return True

        # Year-only references (4 digits only, should preserve)
        import re
        if re.match(r"^\d{4}$", matched_text):
            # Check if it's in a clinical context (not a DOB)
            clinical_year_context = [
                "in", "since", "sedan", "från", "during", "under"
            ]
            if any(word in context_before for word in clinical_year_context):
                return True

        # Timeline references (should preserve)
        timeline_indicators = [
            "next", "nästa", "last", "senaste", "previous", "förra",
            "upcoming", "kommande", "follow-up", "kontroll"
        ]
        if any(indicator in context_before for indicator in timeline_indicators):
            return True

        return False

    def _is_medication_dosage(self, text: str, start: int, end: int) -> bool:
        """
        Determine if a detected number is actually a medication dosage.

        Args:
            text: Full text
            start: Start position of number
            end: End position of number

        Returns:
            True if it's a medication dosage, False otherwise
        """
        # Extract context after the number
        context_after_start = end
        context_after_end = min(len(text), end + 20)
        context_after = text[context_after_start:context_after_end].strip().lower()

        # Dosage unit indicators
        dosage_units = [
            "mg", "mcg", "g", "ml", "units", "iu", "cc", "mmol", "meq",
            "milligram", "microgram", "gram", "milliliter", "liter",
        ]

        # Check if immediately followed by a dosage unit
        for unit in dosage_units:
            if context_after.startswith(unit):
                return True

        return False

    def _is_explicit_phi_context(self, text: str, start: int, end: int) -> bool:
        """
        Check if PERSON entity is in explicit PHI context (like 'Patient: John Doe').

        This method is ULTRA-CONSERVATIVE: only returns True for explicit patient name contexts.
        Clinical terms, demographics, and single-word terms should NOT trigger this.

        Args:
            text: Full text
            start: Start position of entity
            end: End position of entity

        Returns:
            True if entity is in explicit PHI context, False otherwise
        """
        # Extract surrounding context (50 chars before)
        context_start = max(0, start - 50)
        context_before = text[context_start:start].lower()

        # Extract the entity text itself
        entity_text = text[start:end]

        # Single-word entities are almost never patient names (they're usually clinical terms)
        if " " not in entity_text.strip():
            return False

        # Explicit PHI indicators - ONLY these should trigger PERSON redaction
        phi_indicators = [
            "patient:", "patient is", "patient's name", "pt:", "pt is", "pt.",
            "name:", "named", "mr.", "mrs.", "ms.", "dr.", "called",
            "föddes", "heter", "namnet", "patienten heter", "patienten:",
            "patient name", "full name", "name of", "identified as"
        ]

        # Check if any PHI indicator is in the immediately preceding context
        for indicator in phi_indicators:
            if indicator in context_before[-50:]:
                return True

        return False

    def _post_process_results(
        self,
        text: str,
        results: List[RecognizerResult],
        language: str
    ) -> List[RecognizerResult]:
        """
        Post-process Presidio results to remove false positives (medical terms).

        CRITICAL: This method is ULTRA-CONSERVATIVE with PERSON entities.
        Only redact PERSON entities in EXPLICIT PHI context (e.g., "Patient: John Doe").

        Args:
            text: Original text
            results: Presidio recognition results
            language: Language code

        Returns:
            Filtered results with medical terms and clinical temporal references removed
        """
        filtered_results = []

        for result in results:
            # Extract the identified text
            entity_text = text[result.start:result.end]

            # Skip if it's a medical term (checks whitelists + patterns)
            if self._is_medical_term(entity_text, language):
                logger.debug(f"Preserving medical term: {entity_text}")
                continue

            # For PHONE_NUMBER entities, check if it's actually a medication dosage
            if result.entity_type == "PHONE_NUMBER":
                if self._is_medication_dosage(text, result.start, result.end):
                    logger.debug(f"Preserving medication dosage (not phone): {entity_text}")
                    continue

            # For DATE_TIME entities, apply context-aware filtering
            if result.entity_type == "DATE_TIME":
                # Preserve if it's a clinical temporal reference (duration, relative time, year, frequency)
                if self._is_clinical_temporal_reference(text, result.start, result.end):
                    logger.debug(f"Preserving clinical temporal reference: {entity_text}")
                    continue

                # Only redact if it's clearly a DOB
                if not self._is_date_of_birth(text, result.start, result.end):
                    logger.debug(f"Preserving non-DOB date: {entity_text}")
                    continue

            # For PERSON entities, ULTRA-CONSERVATIVE approach
            # Only redact if in EXPLICIT PHI context (like "Patient: John Doe")
            if result.entity_type == "PERSON":
                # Check if in explicit PHI context
                if not self._is_explicit_phi_context(text, result.start, result.end):
                    logger.debug(f"Preserving PERSON entity not in explicit PHI context: {entity_text}")
                    continue
                else:
                    logger.debug(f"Redacting PERSON entity in explicit PHI context: {entity_text}")

            # For LOCATION entities, be conservative about clinical terms
            # SpaCy sometimes misclassifies clinical terms as locations
            if result.entity_type == "LOCATION":
                # Check if it's actually a clinical term in the whitelist
                if self._is_medical_term(entity_text, language):
                    logger.debug(f"Preserving LOCATION entity that is a clinical term: {entity_text}")
                    continue

            filtered_results.append(result)

        return filtered_results

    def redact(self, text: str, language: Optional[str] = None) -> str:
        """
        Redact PHI from text while preserving medical terminology.

        Args:
            text: Text to redact
            language: Language code (ISO 639-1). If None, auto-detect.

        Returns:
            Redacted text with PHI removed and medical terms preserved
        """
        if not text:
            return text

        # Detect or use provided language
        if language is None:
            language = self._detect_language(text)

        logger.debug(f"Redacting text in language: {language}")

        try:
            # Analyze text for PII/PHI
            results = self.analyzer.analyze(
                text=text,
                language=language,
                entities=[
                    "PERSON",
                    "EMAIL_ADDRESS",
                    "PHONE_NUMBER",
                    "PERSONNUMMER",
                    "LOCATION",
                    "DATE_TIME",
                    "URL",
                    "IBAN_CODE",
                    "CREDIT_CARD",
                    "CRYPTO",
                    "UK_NHS",
                    "US_SSN",
                    "US_DRIVER_LICENSE",
                    "US_PASSPORT",
                ],
            )

            # Filter out medical terms
            filtered_results = self._post_process_results(text, results, language)

            # Anonymize with custom operators
            operators = {
                "PERSON": OperatorConfig("replace", {"new_value": "[REDACTED_NAME]"}),
                "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[REDACTED_EMAIL]"}),
                "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[REDACTED_PHONE]"}),
                "PERSONNUMMER": OperatorConfig("replace", {"new_value": "[REDACTED_ID]"}),
                "LOCATION": OperatorConfig("replace", {"new_value": "[REDACTED_LOCATION]"}),
                "DATE_TIME": OperatorConfig("replace", {"new_value": "[REDACTED_DATE]"}),
                "URL": OperatorConfig("replace", {"new_value": "[REDACTED_URL]"}),
                "DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
            }

            result = self.anonymizer.anonymize(
                text=text,
                analyzer_results=filtered_results,
                operators=operators,
            )

            return result.text

        except Exception as e:
            logger.error(f"Error during redaction: {e}", exc_info=True)
            # Fallback to simple regex-based redaction
            return self._fallback_redact(text)

    def _fallback_redact(self, text: str) -> str:
        """
        Fallback redaction using simple regex patterns.
        Used when Presidio fails.

        Args:
            text: Text to redact

        Returns:
            Redacted text
        """
        logger.warning("Using fallback redaction method")

        # Basic patterns for common PHI
        EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        PHONE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{4}\b")
        PERSONNUMMER = re.compile(r"\b\d{6,8}[-\s]?\d{4}\b")

        redacted = text
        redacted = EMAIL.sub("[REDACTED_EMAIL]", redacted)
        redacted = PHONE.sub("[REDACTED_PHONE]", redacted)
        redacted = PERSONNUMMER.sub("[REDACTED_ID]", redacted)

        return redacted
