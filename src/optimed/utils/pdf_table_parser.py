from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


DATE_PATTERN = re.compile(r"\b\d{2}-\d{2}-\d{2}\b|\b\d{4}-\d{2}-\d{2}\b")
TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}\b")
STOPWORDS = {
    "samtliga",
    "ref.intervall",
    "ref intervall",
    "enhet",
    "tidsöversikt",
    "utsrkriven",
    "utsriven",
    "utsriven",
    "utsrkriven",
    "utsriven",
    "utsriven",
    "utsriven",
    "utsriven",
    "tidsoversikt",
    "tidsöversikt",
    "tidsoversikt",
    "tidsoversikt",
    "preparatnamn",
    "styrka",
    "typ",
    "enh",
    "läkemedelsf.",
    "lakemedelsf",
}


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _is_date_line(line: str) -> bool:
    return bool(DATE_PATTERN.search(line))


def _is_time_line(line: str) -> bool:
    return bool(TIME_PATTERN.search(line))


def _looks_like_value(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    if stripped in {"---->", "---", "->"}:
        return True

    if any(ch.isalpha() for ch in stripped):
        # Accept short alpha tokens like "Alert" or "Nej" as values
        return len(stripped.split()) <= 3 and not stripped.lower() in STOPWORDS

    return bool(re.match(r"^[\d\?\+\-\/\.,:% ]+$", stripped))


def _looks_like_row_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _is_date_line(stripped):
        return False
    if stripped.lower() in STOPWORDS:
        return False
    alpha_chars = sum(1 for ch in stripped if ch.isalpha())
    alpha_words = sum(1 for word in stripped.split() if any(ch.isalpha() for ch in word))
    if alpha_words >= 2 and alpha_chars >= 4:
        return True
    return alpha_chars >= 5 and len(stripped) >= 5


@dataclass
class ParsedTableRow:
    row_id: str
    header: str
    attributes: Dict[str, str]
    values: Dict[str, str]
    raw_lines: List[str] = field(default_factory=list)

    def to_json(self, table_id: str, page_number: int, document_id: str) -> str:
        payload = {
            "table_id": table_id,
            "row_id": self.row_id,
            "page_number": page_number,
            "document_id": document_id,
            "item": self.header,
            "attributes": self.attributes,
            "values": self.values,
            "raw_lines": self.raw_lines,
        }
        return json.dumps(payload, ensure_ascii=False)


@dataclass
class ParsedTable:
    table_id: str
    page_number: int
    attribute_columns: List[str]
    value_columns: List[str]
    rows: List[ParsedTableRow]
    raw_text: str

    def to_json(self, document_id: str) -> str:
        payload = {
            "table_id": self.table_id,
            "page_number": self.page_number,
            "document_id": document_id,
            "attribute_columns": self.attribute_columns,
            "value_columns": self.value_columns,
            "rows": [
                {
                    "row_id": row.row_id,
                    "item": row.header,
                    "attributes": row.attributes,
                    "values": row.values,
                }
                for row in self.rows
            ],
        }
        return json.dumps(payload, ensure_ascii=False)


@dataclass
class TableParseOutput:
    tables: List[ParsedTable]
    cleaned_text: str


class PDFTableParser:
    """
    Heuristic parser that reconstructs common clinical PDF tables where columns are rendered
    vertically (date/time headers + item rows).
    """

    def extract_tables(self, text: Optional[str], document_id: str) -> TableParseOutput:
        if not text:
            return TableParseOutput(tables=[], cleaned_text="")

        pages = self._split_into_pages(text)
        tables: List[ParsedTable] = []
        spans: List[Tuple[int, int, ParsedTable]] = []

        for page_number, start, end in pages:
            page_text = text[start:end]
            table = self._parse_table_page(page_text, page_number)
            if table and table.rows:
                tables.append(table)
                spans.append((start, end, table))

        cleaned_text = self._remove_spans(text, spans)
        return TableParseOutput(tables=tables, cleaned_text=cleaned_text)

    def _split_into_pages(self, text: str) -> List[Tuple[int, int, int]]:
        """
        Returns list of tuples: (page_number, start_idx, end_idx).
        Uses 'Sida X (Y)' markers when available; otherwise falls back to full text.
        """
        matches = list(re.finditer(r"Sida\s+\d+\s*\(\d+\)", text))
        spans: List[Tuple[int, int, int]] = []

        if not matches:
            spans.append((1, 0, len(text)))
            return spans

        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            page_number = idx + 1
            spans.append((page_number, start, end))

        return spans

    def _parse_table_page(self, page_text: str, page_number: int) -> Optional[ParsedTable]:
        lines = [_normalize_line(line) for line in page_text.splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            return None

        first_date_idx = next((i for i, line in enumerate(lines) if _is_date_line(line)), None)
        if first_date_idx is None or first_date_idx == 0:
            return None

        attribute_candidates = lines[max(0, first_date_idx - 8):first_date_idx]
        attribute_columns = [
            cand for cand in attribute_candidates if 1 <= len(cand.split()) <= 4 and any(ch.isalpha() for ch in cand)
        ]
        attribute_columns = attribute_columns[-5:] if attribute_columns else ["Item"]

        value_columns = self._build_value_columns(lines[first_date_idx:])
        if not value_columns:
            return None

        content_lines = lines[first_date_idx + len(value_columns) * 2 :]
        rows = self._extract_rows(content_lines, attribute_columns, value_columns)
        if not rows:
            return None

        return ParsedTable(
            table_id=str(uuid.uuid4()),
            page_number=page_number,
            attribute_columns=attribute_columns,
            value_columns=value_columns,
            rows=rows,
            raw_text=page_text,
        )

    def _build_value_columns(self, lines: Sequence[str]) -> List[str]:
        columns: List[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if _is_date_line(line):
                header = line
                next_line = lines[i + 1] if i + 1 < len(lines) else ""
                if _is_time_line(next_line):
                    header = f"{header} {next_line}"
                    i += 1
                columns.append(header)
            else:
                # Stop when we encounter non-date text to avoid consuming table body
                if len(columns) >= 3:
                    break
            i += 1
        return columns

    def _extract_rows(
        self,
        lines: Sequence[str],
        attribute_columns: Sequence[str],
        value_columns: Sequence[str],
    ) -> List[ParsedTableRow]:
        rows: List[ParsedTableRow] = []
        i = 0
        attr_slots = max(0, len(attribute_columns) - 1)

        while i < len(lines):
            line = lines[i]
            if not line or line in attribute_columns or line in value_columns:
                i += 1
                continue

            if not _looks_like_row_header(line):
                i += 1
                continue

            header = line
            i += 1

            row_lines = [header]

            # Consume attribute slot lines
            for _ in range(attr_slots):
                if i >= len(lines):
                    break
                row_lines.append(lines[i])
                i += 1

            # Consume value lines until next probable row header
            while i < len(lines):
                candidate = lines[i]
                if candidate in attribute_columns or candidate in value_columns:
                    i += 1
                    continue
                if _looks_like_row_header(candidate) and self._enough_values_captured(row_lines, len(value_columns)):
                    break
                row_lines.append(candidate)
                i += 1

            row = self._finalize_row(row_lines, attribute_columns, value_columns)
            if row:
                rows.append(row)

        return rows

    def _enough_values_captured(self, row_lines: Sequence[str], value_columns_count: int) -> bool:
        values_seen = sum(1 for line in row_lines if _looks_like_value(line))
        return values_seen >= max(1, value_columns_count // 2)

    def _finalize_row(
        self,
        lines: Sequence[str],
        attribute_columns: Sequence[str],
        value_columns: Sequence[str],
    ) -> Optional[ParsedTableRow]:
        if not lines:
            return None

        header = lines[0]
        attr_values: Dict[str, str] = {}
        attr_slots = len(attribute_columns) - 1
        idx = 1

        for attr_idx in range(attr_slots):
            if idx >= len(lines):
                break
            attr_values[attribute_columns[attr_idx + 1]] = lines[idx]
            idx += 1

        value_lines = list(lines[idx:])
        cell_values = self._consume_values(value_lines, len(value_columns))

        return ParsedTableRow(
            row_id=str(uuid.uuid4()),
            header=header,
            attributes=attr_values,
            values={col: cell_values[i] if i < len(cell_values) else "" for i, col in enumerate(value_columns)},
            raw_lines=list(lines),
        )

    def _consume_values(self, lines: Sequence[str], expected: int) -> List[str]:
        values: List[str] = []
        buffer = ""

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("----"):
                if buffer:
                    values.append(buffer.strip())
                    buffer = ""
                values.append("---->")
                if len(values) >= expected:
                    break
                continue

            if not buffer:
                buffer = stripped
            else:
                if buffer.endswith(("+", "/")) or not _looks_like_row_header(line):
                    buffer = f"{buffer} {stripped}".strip()
                else:
                    values.append(buffer.strip())
                    buffer = stripped

            if len(values) >= expected:
                break

        if buffer and len(values) < expected:
            values.append(buffer.strip())

        return values[:expected]

    def _remove_spans(self, text: str, spans: List[Tuple[int, int, ParsedTable]]) -> str:
        if not spans:
            return text

        spans = sorted(spans, key=lambda s: s[0])
        result_parts: List[str] = []
        cursor = 0

        for start, end, table in spans:
            if cursor < start:
                result_parts.append(text[cursor:start])
            placeholder = f"\n\n[TABLE {table.table_id} REMOVED]\n\n"
            result_parts.append(placeholder)
            cursor = end

        if cursor < len(text):
            result_parts.append(text[cursor:])

        return "".join(result_parts).strip()


