from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
import unicodedata


DATE_ONLY_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{2}$|^\d{4}-\d{2}-\d{2}$")
DATE_TIME_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{2}\s+\d{1,2}:\d{2}$|^\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}$")
TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")
STOPWORDS = {
    "samtliga",
    "ref.intervall",
    "ref intervall",
    "enhet",
    "tidsöversikt",
    "tidsoversikt",
    "utsrkriven",
    "utsriven",
    "karolinska",
    "universitetssjukhuset",
    "blickagången",
    "akutmottagning",
    "preparatnamn",
    "styrka",
    "typ",
    "enh",
    "läkemedelsf.",
    "lakemedelsf",
}
HEADER_NOISE_KEYWORDS = {
    "sida",
    "tidsöversikt",
    "utsriven",
    "utskriven",
    "patient",
    "adress",
}
PREFERRED_ATTRIBUTE_SETS = [
    ["preparatnamn", "styrka", "lakemedelsform", "typ", "enh"],
    ["refintervall", "enhet"],
]
ITEM_LABEL_KEYWORDS = {
    "preparatnamn",
    "samtliga",
}
VALUE_HEADER_KEYWORDS = {
    "idag",
}
TYPE_TOKENS = {
    "rb", "tf", "vb", "hp", "vf", "wp", "tb", "iv", "im", "sc", "po", "ab", "tf",
}


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _is_date_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(DATE_ONLY_PATTERN.match(stripped) or DATE_TIME_PATTERN.match(stripped))


def _is_time_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(TIME_PATTERN.match(stripped))


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
    first_alpha = next((ch for ch in stripped if ch.isalpha()), None)
    if not first_alpha or not first_alpha.isupper():
        return False
    if alpha_words >= 2 and alpha_chars >= 4:
        return True
    return alpha_chars >= 5 and len(stripped) >= 5


def _should_merge_value(prev: str, current: str) -> bool:
    if not prev or not current:
        return False
    prev = prev.strip()
    current = current.strip()
    if not prev or not current:
        return False

    prev_has_digit = any(ch.isdigit() for ch in prev)
    curr_has_digit = any(ch.isdigit() for ch in current)

    # Attach short unit fragments (mmHg, %, in.)
    if not curr_has_digit and len(current) <= 4:
        return True

    # Avoid merging when new token starts with digits (new measurement)
    if curr_has_digit:
        return False

    if prev_has_digit and not curr_has_digit:
        return False

    if len(current) <= 3:
        return True

    if prev.endswith(('-', '/')):
        return True

    return False


def _distribute_value_tokens(tokens: List[str], value_count: int) -> List[str]:
    if not tokens:
        return [""] * value_count

    values: List[str] = []
    total = len(tokens)
    idx = 0

    for remaining in range(value_count, 0, -1):
        if idx >= total:
            values.append("")
            continue

        chunks: List[str] = []
        digits_seen = False

        while idx < total:
            token = tokens[idx]

            if token == "---->":
                chunks.append(token)
                idx += 1
                break

            chunks.append(token)
            idx += 1

            if any(ch.isdigit() for ch in token):
                digits_seen = True
                # Attach short unit fragments (mmHg, %, etc.)
                while idx < total:
                    peek = tokens[idx]
                    if not any(ch.isdigit() for ch in peek) and len(peek) <= 4:
                        chunks.append(peek)
                        idx += 1
                    else:
                        break
                break

        values.append(" ".join(chunks).strip())

    return values


def _consume_pre_attribute_value(tokens: List[str], attr_name: str) -> Tuple[str, List[str]]:
    if not tokens:
        return "", tokens

    attr_lower = attr_name.lower()
    chunk: List[str] = []
    remaining = tokens

    if "styrka" in attr_lower:
        while remaining:
            token = remaining[0]
            chunk.append(token)
            remaining = remaining[1:]
            if any(ch.isdigit() for ch in token):
                while remaining and len(remaining[0]) <= 4 and not any(ch.isdigit() for ch in remaining[0]):
                    chunk.append(remaining[0])
                    remaining = remaining[1:]
                break
        return " ".join(chunk).strip(), remaining

    if "l�kemedelsform" in attr_lower or "läkemedelsform" in attr_lower:
        while remaining:
            token = remaining[0]
            lowered = token.lower()
            if lowered in TYPE_TOKENS:
                break
            chunk.append(token)
            remaining = remaining[1:]
            if len(chunk) >= 2 and not any(ch.isdigit() for ch in token):
                break
        return " ".join(chunk).strip(), remaining

    if attr_lower == "typ":
        token = remaining[0]
        return token, remaining[1:]

    # Default: single token
    token = remaining[0]
    return token, remaining[1:]


def _clean_header_label(line: str) -> str:
    cleaned = re.sub(r"\([^)]*\)", "", line)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(":").rstrip(".").strip()
    return cleaned


def _is_noise_header(line: str) -> bool:
    lowered = line.lower()
    if not lowered:
        return True
    if any(keyword in lowered for keyword in HEADER_NOISE_KEYWORDS):
        return True
    if len(lowered) <= 2:
        return True
    return False


def _normalize_keyword(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[.\s:]+", "", normalized)
    return normalized


def _keyword_match(candidate: str, keyword: str) -> bool:
    return candidate.startswith(keyword) or keyword.startswith(candidate)


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

        item_label, pre_attributes = self._derive_attribute_columns(lines, first_date_idx)

        value_columns, header_consumed = self._build_value_columns(lines[first_date_idx:])
        if not value_columns:
            return None

        content_start = first_date_idx + header_consumed
        content_lines = lines[content_start:]
        trailing_attributes, content_lines = self._extract_trailing_attribute_columns(content_lines)

        attribute_columns = [item_label] + pre_attributes + trailing_attributes
        attrs_after_values = len(trailing_attributes) > 0
        pre_attr_count = len(pre_attributes)
        post_attr_count = len(trailing_attributes)

        rows = self._extract_rows(
            content_lines,
            attribute_columns,
            value_columns,
            pre_attr_count,
            post_attr_count,
            attrs_after_values
        )
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

    def _derive_attribute_columns(self, lines: Sequence[str], first_date_idx: int) -> Tuple[str, List[str]]:
        window_start = max(0, first_date_idx - 12)
        pre_window = lines[window_start:first_date_idx]
        post_window = lines[first_date_idx:first_date_idx + 6]
        candidates: List[Tuple[str, str]] = []
        normalized_seen: set[str] = set()
        item_label = "Item"
        pending_fragment: Optional[str] = None

        def save_candidate(text: str) -> None:
            cleaned_local = text.strip()
            if not cleaned_local:
                return
            normalized_local = _normalize_keyword(cleaned_local)
            if normalized_local in VALUE_HEADER_KEYWORDS:
                return
            nonlocal item_label
            if normalized_local in ITEM_LABEL_KEYWORDS and item_label == "Item":
                item_label = cleaned_local
                return
            if normalized_local in normalized_seen:
                return
            normalized_seen.add(normalized_local)
            candidates.append((cleaned_local, normalized_local))

        for raw in pre_window + post_window:
            cleaned = _clean_header_label(raw)
            if not cleaned:
                continue
            normalized = _normalize_keyword(cleaned)
            if normalized in VALUE_HEADER_KEYWORDS:
                continue
            if pending_fragment:
                cleaned = f"{pending_fragment} {cleaned}".strip()
                pending_fragment = None
            if "(" in raw and ")" not in raw:
                pending_fragment = cleaned
                continue
            if _is_noise_header(cleaned):
                continue
            if _is_date_line(cleaned) or _is_time_line(cleaned):
                continue
            if any(char.isdigit() for char in cleaned) and normalized not in ITEM_LABEL_KEYWORDS:
                continue
            if len(cleaned) <= 3 and cleaned.islower() and candidates:
                prev_text, _ = candidates[-1]
                combined_text = f"{prev_text}{cleaned}"
                candidates[-1] = (combined_text.strip(), _normalize_keyword(combined_text))
                continue
            save_candidate(cleaned)

        for preferred in PREFERRED_ATTRIBUTE_SETS:
            if all(any(_keyword_match(norm, keyword) for _, norm in candidates) for keyword in preferred):
                ordered: List[str] = []
                for keyword in preferred:
                    for original, norm in candidates:
                        if _keyword_match(norm, keyword):
                            ordered.append(original)
                            break
                return item_label, ordered

        fallback = [original for original, _ in candidates if not _is_noise_header(original)]
        fallback = fallback[-4:] if len(fallback) > 4 else fallback
        return item_label, fallback

    def _build_value_columns(self, lines: Sequence[str]) -> Tuple[List[str], int]:
        columns: List[str] = []
        i = 0
        consumed = 0
        while i < len(lines):
            line = lines[i]
            normalized = _normalize_keyword(line)
            if _is_date_line(line):
                header = line
                consumed = i + 1
                next_line = lines[i + 1] if i + 1 < len(lines) else ""
                if _is_time_line(next_line):
                    header = f"{header} {next_line}"
                    i += 1
                    consumed = i + 1
                columns.append(header)
                i += 1
                continue
            if normalized in VALUE_HEADER_KEYWORDS:
                columns.append(line.strip())
                i += 1
                consumed = i
                continue
            if columns:
                break
            i += 1
        return columns, consumed

    def _extract_rows(
        self,
        lines: Sequence[str],
        attribute_columns: Sequence[str],
        value_columns: Sequence[str],
        pre_attr_count: int,
        post_attr_count: int,
        attrs_after_values: bool,
    ) -> List[ParsedTableRow]:
        rows: List[ParsedTableRow] = []
        i = 0

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

            # Consume value lines until next probable row header
            while i < len(lines):
                candidate = lines[i]
                if candidate in attribute_columns or candidate in value_columns:
                    i += 1
                    continue
                if _looks_like_row_header(candidate) and self._enough_values_captured(row_lines, pre_attr_count, len(value_columns)):
                    break
                row_lines.append(candidate)
                i += 1

            row = self._finalize_row(
                row_lines,
                attribute_columns,
                value_columns,
                pre_attr_count,
                post_attr_count,
                attrs_after_values
            )
            if row:
                rows.append(row)

        return rows

    def _enough_values_captured(
        self,
        row_lines: Sequence[str],
        pre_attr_count: int,
        value_columns_count: int
    ) -> bool:
        start_idx = 1 + pre_attr_count
        relevant = row_lines[start_idx:]
        values_seen = sum(1 for line in relevant if _looks_like_value(line))
        return values_seen >= max(1, value_columns_count // 2)

    def _finalize_row(
        self,
        lines: Sequence[str],
        attribute_columns: Sequence[str],
        value_columns: Sequence[str],
        pre_attr_count: int,
        post_attr_count: int,
        attrs_after_values: bool,
    ) -> Optional[ParsedTableRow]:
        if not lines:
            return None

        header_parts = [lines[0]]
        idx = 1

        # Merge header fragments that were split across lines (common for vitals rows)
        while idx < len(lines):
            candidate = lines[idx]
            if not candidate:
                idx += 1
                continue
            normalized = _normalize_keyword(candidate)
            if header_parts[-1].rstrip().endswith(('-', ',')):
                header_parts.append(candidate)
                idx += 1
                continue
            if pre_attr_count == 0 and not attrs_after_values and _looks_like_row_header(candidate):
                header_parts.append(candidate)
                idx += 1
                continue
            break

        header = " ".join(header_parts).strip()
        attr_values: Dict[str, str] = {}
        before_attrs = attribute_columns[1:1 + pre_attr_count]
        after_attrs = attribute_columns[1 + pre_attr_count:]

        remaining_tokens = [line.strip() for line in lines[idx:] if line and line.strip()]

        if before_attrs:
            new_remaining: List[str] = remaining_tokens
            for attr_name in before_attrs:
                value, new_remaining = _consume_pre_attribute_value(new_remaining, attr_name)
                attr_values[attr_name] = value
            remaining_tokens = new_remaining

        merged_tokens: List[str] = []
        for token in remaining_tokens:
            if merged_tokens and _should_merge_value(merged_tokens[-1], token):
                merged_tokens[-1] = f"{merged_tokens[-1]} {token}".strip()
            else:
                merged_tokens.append(token)

        # Split tokens into pre-allocated segments
        token_idx = 0
        remaining_tokens = merged_tokens

        value_tokens: List[str] = []
        tail_tokens: List[str] = []

        if after_attrs and len(merged_tokens) >= len(after_attrs):
            tail_tokens = merged_tokens[-len(after_attrs):]
            value_tokens = merged_tokens[:-len(after_attrs)]
        else:
            value_tokens = merged_tokens
            tail_tokens = []

        values_by_column = _distribute_value_tokens(value_tokens, len(value_columns))

        for attr_name, token in zip(after_attrs, tail_tokens):
            attr_values[attr_name] = token
        if len(tail_tokens) < len(after_attrs):
            for attr_name in after_attrs[len(tail_tokens):]:
                attr_values[attr_name] = ""

        return ParsedTableRow(
            row_id=str(uuid.uuid4()),
            header=header,
            attributes=attr_values,
            values={col: values_by_column[i] if i < len(values_by_column) else "" for i, col in enumerate(value_columns)},
            raw_lines=list(lines),
        )

    def _extract_trailing_attribute_columns(self, lines: List[str]) -> Tuple[List[str], List[str]]:
        trailing_attrs: List[str] = []
        idx = 0
        while idx < len(lines):
            candidate = _clean_header_label(lines[idx])
            normalized = _normalize_keyword(candidate)
            if not candidate:
                idx += 1
                continue
            if normalized in {"refintervall", "enhet"}:
                trailing_attrs.append(candidate)
                idx += 1
            else:
                break
        return trailing_attrs, lines[idx:]

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


