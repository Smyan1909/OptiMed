from __future__ import annotations

import re

from optimed.core.ports import PhiRedactorPort


class SimplePhiRedactor(PhiRedactorPort):
    """Conservative PII redactor using regex heuristics with medical term awareness.

    This redactor preserves medical terminology while removing PHI.
    """

    # Basic patterns for emails, phones, MRNs/IDs, dates (DOB), and addresses
    EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    PHONE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{4}\b")
    IDNUM = re.compile(r"\b(?:MRN|ID|SSN|PERSONNUMMER|PERSONNUM|NATIONAL\s?ID)[\s:]*[A-Za-z0-9-]{3,}\b", re.IGNORECASE)
    DOB = re.compile(r"\b(?:DOB|BIRTH\s?DATE|DATE\s?OF\s?BIRTH)[\s:]*\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}\b", re.IGNORECASE)
    DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
    ADDRESS = re.compile(r"\b\d+\s+[A-Za-z0-9 .'-]{3,}(?:Street|St\.|Avenue|Ave\.|Road|Rd\.|Lane|Ln\.|Drive|Dr\.)\b", re.IGNORECASE)

    # Context-aware name patterns - only match when in patient/name context
    # Note: Use (?i:...) for case-insensitive context keywords, but require proper capitalization for names
    NAME_WITH_CONTEXT = re.compile(
        r"\b(?i:patient|pt|name|named|mr|mrs|ms|dr|doctor)\s+(?i:is\s+)?([A-Z][a-z]+\s+[A-Z][a-z]+)\b"
    )

    # Common medical term patterns that should NEVER be redacted
    # This includes disease names, medication patterns, anatomical terms, etc.
    MEDICAL_TERMS = {
        # Common disease patterns (disease name + descriptor)
        r"\b[A-Z][a-z]+\s+(?:Mellitus|Disease|Syndrome|Disorder|Failure|Attack|Stroke)\b",
        r"\b(?:Type|Stage)\s+[A-Z0-9]+\s+[A-Z][a-z]+\b",

        # Anatomical terms (two-word capitalized anatomical structures)
        r"\b(?:Coronary|Carotid|Femoral|Pulmonary|Hepatic|Renal)\s+(?:Artery|Vein|Nerve|Disease)\b",
        r"\b(?:Left|Right)\s+(?:Ventricle|Atrium|Lung|Kidney|Lobe)\b",

        # Common medication patterns (often end with specific suffixes)
        r"\b[A-Z][a-z]+(?:cillin|mycin|dipine|pril|sartan|statin|zole|cycline|oxin)\b",
        r"\b[A-Z][a-z]+\s+(?:Sodium|Potassium|Hydrochloride|Sulfate|Citrate)\b",

        # Imaging and procedure terms
        r"\b(?:CT|MRI|X-ray|Ultrasound|PET)\s+[A-Z][a-z]+\b",
        r"\b[A-Z][a-z]+\s+(?:Scan|Biopsy|Resection|Repair)\b",

        # Vaccine names
        r"\b[A-Z][a-z]+-?\d*\s+Vaccine\b",

        # Common conditions with two capitalized words
        r"\b(?:Acute|Chronic)\s+[A-Z][a-z]+\b",
    }

    # Compile medical term patterns
    MEDICAL_PATTERNS = [re.compile(pattern) for pattern in MEDICAL_TERMS]

    # Extensive list of common medical terms (medications, diseases, anatomical terms)
    # to whitelist from name redaction
    MEDICAL_WHITELIST = {
        # Common medications
        "Aspirin", "Metformin", "Lisinopril", "Atorvastatin", "Amlodipine",
        "Metoprolol", "Omeprazole", "Simvastatin", "Losartan", "Gabapentin",
        "Hydrochlorothiazide", "Levothyroxine", "Warfarin", "Furosemide",
        "Albuterol", "Prednisone", "Insulin", "Penicillin", "Amoxicillin",
        "Ibuprofen", "Acetaminophen", "Morphine", "Heparin", "Dopamine",

        # Common diseases and conditions
        "Diabetes Mellitus", "Coronary Artery", "Heart Failure", "Myocardial Infarction",
        "Atrial Fibrillation", "Chronic Kidney", "Acute Respiratory", "Pulmonary Embolism",
        "Deep Vein", "Cerebrovascular Accident", "Rheumatoid Arthritis", "Crohn Disease",
        "Multiple Sclerosis", "Parkinson Disease", "Alzheimer Disease", "Lung Cancer",

        # Anatomical terms
        "Left Ventricle", "Right Atrium", "Coronary Sinus", "Aortic Valve",
        "Mitral Valve", "Pulmonary Artery", "Carotid Artery", "Femoral Vein",

        # Common procedures and imaging
        "Chest X-ray", "CT Head", "CT Chest", "MRI Brain", "Cardiac Catheterization",

        # Vaccines
        "COVID-19 Vaccine", "Influenza Vaccine", "Hepatitis B",
    }

    def _is_medical_term(self, candidate: str) -> bool:
        """Check if a candidate name is actually a medical term."""
        # Direct whitelist match
        if candidate in self.MEDICAL_WHITELIST:
            return True

        # Check against medical term patterns
        for pattern in self.MEDICAL_PATTERNS:
            if pattern.search(candidate):
                return True

        # Check for common medical word endings/patterns
        words = candidate.split()

        # Single word checks (for single medications)
        if len(words) == 1:
            word = words[0]
            # Check for medication suffixes (single-word medications)
            med_suffixes = [
                "cillin", "mycin", "dipine", "pril", "sartan", "statin",
                "zole", "cycline", "oxin", "olol", "azole", "afil", "rin"
            ]
            if any(word.lower().endswith(suffix) for suffix in med_suffixes):
                return True

        if len(words) == 2:
            # Common clinical section headers (should not be redacted)
            section_headers = {
                "Chief Complaint", "History of", "Present Illness", "Past Medical",
                "Physical Exam", "Current Medications", "Social History", "Family History",
                "Review of", "Assessment and", "Differential Diagnosis", "Hospital Course",
                "Discharge Instructions", "Follow up", "Vital Signs", "Laboratory Results",
                "Imaging Studies", "Progress Note", "Admission Note", "Discharge Summary"
            }
            if candidate in section_headers:
                return True

            # Check second word for medical indicators
            second_word = words[1]
            medical_indicators = {
                "Disease", "Syndrome", "Disorder", "Failure", "Attack", "Stroke",
                "Artery", "Vein", "Nerve", "Ventricle", "Atrium", "Lung", "Kidney",
                "Vaccine", "Scan", "Biopsy", "Mellitus", "Sodium", "Potassium",
                "Hydrochloride", "Sulfate", "Citrate", "Complaint", "Illness",
                "Exam", "Medications", "History", "Note", "Summary"
            }
            if second_word in medical_indicators:
                return True

            # Check for medication suffixes
            med_suffixes = [
                "cillin", "mycin", "dipine", "pril", "sartan", "statin",
                "zole", "cycline", "oxin", "olol", "azole", "afil"
            ]
            if any(second_word.lower().endswith(suffix) for suffix in med_suffixes):
                return True

        return False

    def redact(self, text: str) -> str:
        if not text:
            return text

        redacted = text

        # First, redact obvious PHI patterns
        redacted = self.EMAIL.sub("[REDACTED_EMAIL]", redacted)
        redacted = self.PHONE.sub("[REDACTED_PHONE]", redacted)
        redacted = self.IDNUM.sub("[REDACTED_ID]", redacted)
        redacted = self.DOB.sub("[REDACTED_DOB]", redacted)
        redacted = self.ADDRESS.sub("[REDACTED_ADDRESS]", redacted)

        # Context-aware name redaction (only when explicitly mentioned as patient/person)
        redacted = self.NAME_WITH_CONTEXT.sub(
            lambda m: m.group(0).replace(m.group(1), "[REDACTED_NAME]"),
            redacted
        )

        # More conservative approach: only redact two-word capitalized patterns
        # if they are NOT medical terms
        def replace_if_not_medical(match: re.Match) -> str:
            candidate = match.group(1)

            # Check if the first word is a common non-name word (verbs, etc.)
            # These are often sentence starters, not names
            first_word = candidate.split()[0]
            common_non_names = {
                "Taking", "Using", "Given", "Started", "Stopped", "Continued",
                "Showing", "Presenting", "Exhibiting", "Demonstrating",
                "After", "Before", "During", "Following", "Concerning"
            }
            if first_word in common_non_names:
                # Check if second word is a known medication
                second_word = candidate.split()[1]
                if self._is_medical_term(second_word):
                    return candidate  # Keep patterns like "Taking Metformin"

            if self._is_medical_term(candidate):
                return candidate  # Keep medical terms
            else:
                return "[REDACTED_NAME]"  # Redact likely names

        # Only apply this to remaining text, being very conservative
        # Pattern: two capitalized words that appear in isolation (not part of medical context)
        # We use negative lookahead/lookbehind to avoid medical contexts
        cautious_name_pattern = re.compile(
            r"(?<!Dr\. )(?<!Dr )(?<!diagnosis of )(?<!diagnosed with )(?<!medication )(?<!condition )"
            r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b"
            r"(?! disease)(?! syndrome)(?! disorder)(?! vaccine)(?! artery)(?! vein)"
        )

        redacted = cautious_name_pattern.sub(replace_if_not_medical, redacted)

        return redacted


