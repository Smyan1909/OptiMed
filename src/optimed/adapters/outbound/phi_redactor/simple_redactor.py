from __future__ import annotations

import re

from optimed.core.ports import PhiRedactorPort


class SimplePhiRedactor(PhiRedactorPort):
    """Conservative PII redactor using regex heuristics.

    This is a baseline; in production, swap with a stronger implementation.
    """

    # Basic patterns for emails, phones, MRNs/IDs, dates (DOB), and names-like tokens
    EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    PHONE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{4}\b")
    IDNUM = re.compile(r"\b(?:MRN|ID|SSN|PERSONNUMMER|PERSONNUM|NATIONAL\s?ID)[\s:]*[A-Za-z0-9-]{3,}\b", re.IGNORECASE)
    DOB = re.compile(r"\b(?:DOB|BIRTH\s?DATE|DATE\s?OF\s?BIRTH)[\s:]*\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}\b", re.IGNORECASE)
    DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
    ADDRESS = re.compile(r"\b\d+\s+[A-Za-z0-9 .'-]{3,}(?:Street|St\.|Avenue|Ave\.|Road|Rd\.|Lane|Ln\.|Drive|Dr\.)\b", re.IGNORECASE)
    NAME_HINT = re.compile(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b")

    def redact(self, text: str) -> str:
        if not text:
            return text
        redacted = text
        redacted = self.EMAIL.sub("[REDACTED_EMAIL]", redacted)
        redacted = self.PHONE.sub("[REDACTED_PHONE]", redacted)
        redacted = self.IDNUM.sub("[REDACTED_ID]", redacted)
        redacted = self.DOB.sub("[REDACTED_DOB]", redacted)
        redacted = self.ADDRESS.sub("[REDACTED_ADDRESS]", redacted)
        # Conservative removal of capitalized first+last names
        redacted = self.NAME_HINT.sub("[REDACTED_NAME]", redacted)
        return redacted


