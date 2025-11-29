from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple
import unicodedata

if TYPE_CHECKING:
    from optimed.adapters.pdf.pdf_processor import PageTextWithCoords, TextSpan

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
DATE_ONLY_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{2}$")
DATE_TIME_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{2}\s+\d{1,2}:\d{2}$")
TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")
PAGE_MARKER_PATTERN = re.compile(r"Sida\s+\d+\s*\(\d+\)")

# Noise line patterns - structural patterns that indicate non-table content
# These are generalizable patterns, not PDF-specific keywords
NOISE_LINE_PATTERNS = [
    # Postal codes: "141 86 Stockholm", "125 56 Älvsjö"
    re.compile(r"^\d{2,3}\s+\d{2}\s+\w+"),
    # Phone numbers: "08-123 800 00"
    re.compile(r"^\d{2}-\d{3}\s+\d{3}\s+\d{2}"),
    # Swedish personal numbers: "060606-0606"
    re.compile(r"^\d{6}-\d{4}$"),
    # Personal number with age prefix: "18 060606-0606"
    re.compile(r"^\d{2}\s+\d{6}-\d{4}$"),
    # Page markers (Swedish "Sida X" or could be extended for other languages)
    re.compile(r"^Sida\s+\d+"),
    # Print timestamp marker (Swedish "Utskriven")
    re.compile(r"^Utskriven"),
    # Time overview section (Swedish "Tidsöversikt")
    re.compile(r"^Tidsöversikt"),
    # Date ranges: "2025-11-17 -- 2025-11-24"
    re.compile(r"^\d{4}-\d{2}-\d{2}\s+--"),
    # Ward/department codes: "K45 Akutmottagning"
    re.compile(r"^K\d+\s+\w+"),
]

NOISE_KEYWORDS = {
    # Only truly generalizable keywords that appear in PDF headers/footers
    "kommentarer",  # Comments section marker
}

ITEM_LABEL_KEYWORDS = {"preparatnamn", "samtliga"}
TRAILING_ATTR_KEYWORDS = {"ref.intervall", "refintervall", "enhet"}
VALUE_HEADER_KEYWORDS = {"idag"}
MED_ATTR_KEYWORDS = {"styrka", "läkemedelsform", "lakemedelsform", "typ", "enh", "orm"}
TYPE_TOKENS = {"rb", "tf", "vb", "hp", "vf", "wp", "tb", "iv", "im", "sc", "po", "ab"}

UNIT_PATTERNS = [
    re.compile(r"^(mmHg|%|°C|cm|kg|ml|g|mg|kcal|slag|andetag|ggr)(/.*)?\.?$", re.IGNORECASE),
    re.compile(r"^(andetag/min|andetag/m|slag/min|kcal/dygn)\.?$", re.IGNORECASE),
    re.compile(r"^in\.$", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _normalize_keyword(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[.\s:()]+", "", normalized)
    return normalized


def _is_date_line(line: str) -> bool:
    stripped = line.strip()
    return bool(DATE_ONLY_PATTERN.match(stripped) or DATE_TIME_PATTERN.match(stripped))


def _is_time_line(line: str) -> bool:
    stripped = line.strip()
    return bool(TIME_PATTERN.match(stripped))


def _is_noise_line(line: str) -> bool:
    """Check if line is structural noise (page markers, phone numbers, etc.)."""
    stripped = line.strip()
    if not stripped:
        return True
    for pattern in NOISE_LINE_PATTERNS:
        if pattern.match(stripped):
            return True
    lowered = stripped.lower()
    for keyword in NOISE_KEYWORDS:
        if keyword in lowered:
            return True
    return False


def _is_page_header_content(line: str) -> bool:
    """
    Check if line looks like page header content (hospital name, address, etc.)
    that appears between pages but isn't a table row.
    
    We're conservative here - only mark clear patterns as header content.
    """
    stripped = line.strip()
    if not stripped:
        return False
    
    # Already handled by noise patterns
    if _is_noise_line(stripped):
        return True
    
    lowered = stripped.lower()
    
    # Institutional patterns (hospitals, universities, etc.)
    # These are generic patterns that identify institution names
    institution_patterns = [
        r"universitetssjukhuset",  # University hospital (Swedish)
        r"sjukhuset",  # Hospital (Swedish)
        r"university\s+hospital",  # University hospital (English)
        r"hospital\s*$",  # Hospital at end
        r"klinik",  # Clinic
        r"vårdcentral",  # Healthcare center
        r"akutmottagning",  # Emergency department
    ]
    for pattern in institution_patterns:
        if re.search(pattern, lowered):
            return True
    
    # Street address patterns (without comma requirement)
    # e.g., "Fiktiva Gatan 12", "Main Street 123"
    if re.search(r"(gatan|vägen|street|road|avenue)\s+\d+", lowered):
        return True
    
    # Address pattern: contains comma AND looks like "Street X, City" format
    # But NOT medication forms like "Kapsel, hård" or medication names like "Th Diben 1,5 Kcal"
    if "," in stripped:
        # Medication forms contain specific keywords
        form_indicators = {"kapsel", "tablett", "pulver", "lösning", "kräm", "gel", "salva", "hård"}
        if any(ind in lowered for ind in form_indicators):
            return False
        # Medication names often have numbers (dosages) like "1,5 Kcal"
        # But addresses have numbers too like "9C" - check for dosage patterns
        if re.search(r"\d+[,\.]\d+", stripped):  # Decimal numbers like 1,5 or 1.5
            return False
        # Address pattern: "Something XY, Something" where XY is alphanumeric (street number)
        # e.g., "Blickagången 9C, Huddinge"
        if re.search(r"\d+[A-Za-z]?,", stripped):
            return True
        # Name pattern: "Lastname, Firstname" - two capitalized words with comma
        # e.g., "Fiktiv, Äldrekvinna"
        words = stripped.split(",")
        if len(words) == 2:
            w1, w2 = words[0].strip(), words[1].strip()
            if w1 and w2 and w1[0].isupper() and w2[0].isupper():
                # Likely a name, not a medication
                if not any(ch.isdigit() for ch in stripped):
                    return True
    
    return False


def _is_unit(line: str) -> bool:
    stripped = line.strip()
    for pattern in UNIT_PATTERNS:
        if pattern.match(stripped):
            return True
    return False


def _is_ref_interval(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^\d+\s*-\s*\d+$", stripped))


def _is_type_token(line: str) -> bool:
    return line.strip().lower() in TYPE_TOKENS


def _is_med_value_token(line: str) -> bool:
    """Check if a token is a medication value (dosage number, arrow, ?)."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped == "---->":
        return True
    if stripped == "?":
        return True
    # Single digit or small number (dosage) - max 3 digits for single values
    # This covers values like "1", "10", "500"
    if re.match(r"^\d{1,3}$", stripped):
        return True
    # Patterns like "1 + 1 + 1", "500 + 500 + 500" (with + sign)
    if "+" in stripped and re.match(r"^[\d\+\s]+$", stripped):
        return True
    return False


def _is_vitals_value_token(line: str) -> bool:
    """Check if a token is a vitals value."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped in {"---->", "---", "->", "?"}:
        return True
    if re.match(r"^-?\d+[\d\.\,]*$", stripped):
        return True
    if re.match(r"^[\d\?\+\- ]+$", stripped):
        return True
    if stripped.lower() in {"alert", "nej", "ja", "in", "mellan", "ggr"}:
        return True
    return False


def _looks_like_row_header_start(line: str, table_type: str) -> bool:
    """Check if a line looks like the START of a new table row header."""
    stripped = line.strip()
    if not stripped:
        return False
    if not stripped[0].isupper():
        return False
    if _is_date_line(stripped):
        return False
    if _is_noise_line(stripped):
        return False
    
    alpha_chars = sum(1 for ch in stripped if ch.isalpha())
    if alpha_chars < 3:
        return False
    
    normalized = _normalize_keyword(stripped)
    if normalized in ITEM_LABEL_KEYWORDS or normalized in TRAILING_ATTR_KEYWORDS:
        return False
    if normalized in MED_ATTR_KEYWORDS:
        return False
    
    if table_type == "medication":
        # For medication, be very strict - only accept clear medication names
        if _is_type_token(stripped):
            return False
        if _is_med_value_token(stripped):
            return False
        # Must have at least 4 alpha chars to be a medication name
        if alpha_chars < 4:
            return False
        # Exclude pharmaceutical form descriptions
        lowered = stripped.lower()
        form_keywords = {
            "kapsel", "tablett", "pulver", "lösning", "suspension", "injektion",
            "infusion", "oral", "kräm", "salva", "gel", "depot", "enterotablett",
            "filmdragerad", "koncentrat", "nebulisator", "spädning", "sterilt",
            "vatten", "natriumklorid",
        }
        for kw in form_keywords:
            if kw in lowered:
                return False
        # Exclude if contains comma (like "Kapsel, hård")
        if "," in stripped and not any(ch.isdigit() for ch in stripped):
            return False
        return True
    else:
        if _is_type_token(stripped):
            return False
        if _is_vitals_value_token(stripped):
            return False
        return True


def _is_header_continuation(line: str, prev_line: str) -> bool:
    """Check if line is a continuation of a multi-line row header."""
    stripped = line.strip()
    prev_stripped = prev_line.strip() if prev_line else ""
    if not stripped or not prev_stripped:
        return False
    if prev_stripped.endswith(('-', ',')):
        return True
    if stripped[0].islower():
        return True
    if re.match(r"^dag\s+\d+", stripped.lower()):
        return True
    if stripped.lower() in {"morgon", "kväll", "medelvärde", "övre", "nedre", "in."}:
        return True
    if len(stripped) <= 6 and prev_stripped.endswith(','):
        return True
    return False


def _merge_header_lines(lines: List[str]) -> str:
    if not lines:
        return ""
    result = lines[0]
    for line in lines[1:]:
        stripped = line.strip()
        if result.rstrip().endswith('-'):
            result = result.rstrip()[:-1] + stripped
        elif result.rstrip().endswith(','):
            result = result.rstrip() + " " + stripped
        else:
            result = result + " " + stripped
    return _normalize_line(result)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ParsedTableRow:
    row_id: str
    header: str
    attributes: Dict[str, str]
    values: Dict[str, str]
    raw_lines: List[str] = field(default_factory=list)

    def to_json(self, table_id: str, page_number: int, document_id: str) -> str:
        return json.dumps({
            "table_id": table_id,
            "row_id": self.row_id,
            "page_number": page_number,
            "document_id": document_id,
            "item": self.header,
            "attributes": self.attributes,
            "values": self.values,
        }, ensure_ascii=False)


@dataclass
class ParsedTable:
    table_id: str
    page_number: int
    attribute_columns: List[str]
    value_columns: List[str]
    rows: List[ParsedTableRow]
    raw_text: str

    def to_json(self, document_id: str) -> str:
        return json.dumps({
            "table_id": self.table_id,
            "page_number": self.page_number,
            "document_id": document_id,
            "attribute_columns": self.attribute_columns,
            "value_columns": self.value_columns,
            "rows": [
                {"row_id": row.row_id, "item": row.header, "attributes": row.attributes, "values": row.values}
                for row in self.rows
            ],
        }, ensure_ascii=False)


@dataclass
class TableParseOutput:
    tables: List[ParsedTable]
    cleaned_text: str


# ---------------------------------------------------------------------------
# Main parser class
# ---------------------------------------------------------------------------
class PDFTableParser:

    def extract_tables_with_coords(
        self, 
        pages_data: List["PageTextWithCoords"], 
        document_id: str
    ) -> TableParseOutput:
        """
        Extract tables using coordinate information for accurate column alignment.
        
        This method uses x-coordinates to properly align values with their columns,
        which is essential for tables with sparse data (empty cells).
        
        Args:
            pages_data: List of PageTextWithCoords from PDF processor
            document_id: Document identifier
            
        Returns:
            TableParseOutput with parsed tables
        """
        if not pages_data:
            return TableParseOutput(tables=[], cleaned_text="")
        
        tables: List[ParsedTable] = []
        non_table_text_parts: List[str] = []
        
        for page_data in pages_data:
            table = self._parse_table_page_with_coords(page_data)
            if table and table.rows:
                tables.append(table)
                # Page was parsed as a table - don't include in cleaned_text
            else:
                # Page wasn't a table - include in cleaned_text for semantic chunking
                non_table_text_parts.append(page_data.raw_text)
        
        # cleaned_text only contains pages that weren't parsed as tables
        # This prevents duplicate chunking of table content
        cleaned_text = "\n\n".join(non_table_text_parts) if non_table_text_parts else ""
        
        return TableParseOutput(tables=tables, cleaned_text=cleaned_text)

    def _parse_table_page_with_coords(
        self, 
        page_data: "PageTextWithCoords"
    ) -> Optional[ParsedTable]:
        """Parse a single page using coordinate information."""
        spans = page_data.spans
        if not spans:
            return None
        
        # Group spans by y-coordinate (rows)
        y_tolerance = 5.0
        rows_by_y: Dict[float, List["TextSpan"]] = {}
        
        for span in spans:
            matched_y = None
            for existing_y in rows_by_y.keys():
                if abs(span.y0 - existing_y) < y_tolerance:
                    matched_y = existing_y
                    break
            
            if matched_y is not None:
                rows_by_y[matched_y].append(span)
            else:
                rows_by_y[span.y0] = [span]
        
        sorted_y = sorted(rows_by_y.keys())
        
        # Detect table type first by looking for keywords
        table_type = "vitals"
        for y in sorted_y[:15]:
            row_spans = rows_by_y[y]
            row_text = " ".join(s.text for s in row_spans).lower()
            if "preparatnamn" in row_text or "styrka" in row_text:
                table_type = "medication"
                break
        
        # Find header rows
        date_row_y = None
        time_row_y = None
        attr_header_row_y = None
        med_attr_row_y = None  # For medication attribute headers
        
        for y in sorted_y:
            row_spans = rows_by_y[y]
            date_count = sum(1 for s in row_spans if _is_date_line(s.text))
            time_count = sum(1 for s in row_spans if _is_time_line(s.text))
            
            if date_count >= 3:
                date_row_y = y
            elif time_count >= 3:
                time_row_y = y
            
            # Check for vitals attribute headers (Ref.intervall, Enhet)
            # Be strict: only match exact header words, not substrings like "enheter"
            row_words_lower = [s.text.lower() for s in row_spans]
            if "ref.intervall" in row_words_lower or "enhet" in row_words_lower:
                attr_header_row_y = y
            # Check for medication attribute headers (Styrka, Typ)
            if "styrka" in row_words_lower or "typ" in row_words_lower:
                med_attr_row_y = y
        
        if date_row_y is None:
            return None
        
        # Build value columns from date row
        date_spans = sorted(rows_by_y[date_row_y], key=lambda s: s.x0)
        time_spans = sorted(rows_by_y.get(time_row_y, []), key=lambda s: s.x0) if time_row_y else []
        
        value_columns: List[str] = []
        value_col_positions: List[Tuple[float, float]] = []
        
        for date_span in date_spans:
            text = date_span.text
            # Check for date pattern or "Idag"
            if not (_is_date_line(text) or _normalize_keyword(text) in VALUE_HEADER_KEYWORDS):
                continue
            
            # Find matching time span for vitals
            matching_time = None
            if table_type == "vitals":
                for time_span in time_spans:
                    if abs(time_span.x0 - date_span.x0) < 20:
                        matching_time = time_span.text
                        break
            
            col_name = f"{text} {matching_time}" if matching_time else text
            value_columns.append(col_name)
            col_center = (date_span.x0 + date_span.x1) / 2
            value_col_positions.append((col_center, date_span.x1))
        
        if not value_columns:
            return None
        
        min_value_x = min(pos[0] for pos in value_col_positions)
        
        # Build attribute columns based on table type
        attr_columns: List[str] = []
        attr_col_positions: List[Tuple[float, float]] = []
        
        if table_type == "medication":
            # Medication table: Styrka, Läkemedelsform, Typ, Enh
            # These may be spread across multiple header rows
            # Scan all rows before data starts for attribute headers
            med_attr_x_positions: Dict[str, Tuple[float, float, float]] = {}  # name -> (x_start, center, x_end)
            
            for y in sorted_y[:15]:  # Check first 15 rows for headers
                for span in rows_by_y[y]:
                    normalized = _normalize_keyword(span.text)
                    if normalized in MED_ATTR_KEYWORDS:
                        col_center = (span.x0 + span.x1) / 2
                        # Map to standard names
                        if normalized == "styrka":
                            med_attr_x_positions["Styrka"] = (span.x0, col_center, span.x1)
                        elif normalized in {"lakemedelsform", "läkemedelsform", "orm"}:
                            med_attr_x_positions["Läkemedelsform"] = (span.x0, col_center, span.x1)
                        elif normalized == "typ":
                            med_attr_x_positions["Typ"] = (span.x0, col_center, span.x1)
                        elif normalized == "enh":
                            med_attr_x_positions["Enh"] = (span.x0, col_center, span.x1)
            
            # Sort by x position and add to columns
            # Store (center, x_end) for column matching, but track x_start for boundary
            first_attr_x_start = float('inf')
            for name in ["Styrka", "Läkemedelsform", "Typ", "Enh"]:
                if name in med_attr_x_positions:
                    x_start, center, x_end = med_attr_x_positions[name]
                    attr_columns.append(name)
                    attr_col_positions.append((center, x_end))
                    if x_start < first_attr_x_start:
                        first_attr_x_start = x_start
        elif attr_header_row_y:
            # Vitals table: Ref.intervall, Enhet
            attr_spans = sorted(rows_by_y[attr_header_row_y], key=lambda s: s.x0)
            for span in attr_spans:
                normalized = _normalize_keyword(span.text)
                if normalized == "samtliga":
                    continue
                if normalized in TRAILING_ATTR_KEYWORDS:
                    attr_columns.append(span.text)
                    col_center = (span.x0 + span.x1) / 2
                    attr_col_positions.append((col_center, span.x1))
        
        # Determine data start row
        # Find the first row that looks like actual data (not header continuation)
        header_y_max = date_row_y
        if time_row_y and time_row_y > header_y_max:
            header_y_max = time_row_y
        if attr_header_row_y and attr_header_row_y > header_y_max:
            header_y_max = attr_header_row_y
        if med_attr_row_y and med_attr_row_y > header_y_max:
            header_y_max = med_attr_row_y
        
        # Determine the boundary for the "item name" column (for data start detection)
        # Use the x_start of the first attribute column (e.g., Styrka at x=112.3)
        if table_type == "medication" and first_attr_x_start < float('inf'):
            item_col_boundary = first_attr_x_start - 5  # Small buffer
        elif attr_col_positions:
            item_col_boundary = min(pos[0] for pos in attr_col_positions) - 10
        else:
            item_col_boundary = min_value_x - 30
        
        data_start_idx = 0
        for idx, y in enumerate(sorted_y):
            if y <= header_y_max:
                continue
            # Check if this row looks like actual data (starts with a row header)
            row_spans = sorted(rows_by_y[y], key=lambda s: s.x0)
            if not row_spans:
                continue
            first_span = row_spans[0]
            if first_span.x0 < item_col_boundary:
                leftmost_spans = [s for s in row_spans if s.x0 < item_col_boundary]
                combined_header = " ".join(s.text for s in leftmost_spans)
                if _looks_like_row_header_start(combined_header, table_type):
                    data_start_idx = idx
                    break
        
        # Initialize attributes dict based on table type
        if table_type == "medication":
            init_attrs = {"Styrka": "", "Läkemedelsform": "", "Typ": "", "Enh": ""}
        else:
            init_attrs = {"Ref.intervall": "", "Enhet": ""}
        
        # Parse data rows
        data_rows: List[ParsedTableRow] = []
        current_row_header = ""
        current_row_values: Dict[str, str] = {col: "" for col in value_columns}
        current_row_attrs: Dict[str, str] = init_attrs.copy()
        
        for y in sorted_y[data_start_idx:]:
            row_spans = sorted(rows_by_y[y], key=lambda s: s.x0)
            
            if not row_spans:
                continue
            
            first_span = row_spans[0]
            first_text = first_span.text
            
            if _is_noise_line(first_text) or _is_page_header_content(first_text):
                continue
            
            # Determine if this is a new row
            # For medication: new row starts with medication name in leftmost column
            # For vitals: new row starts with measurement name in leftmost column
            is_new_row = False
            
            # Note: item_col_boundary was already calculated above
            if first_span.x0 < item_col_boundary:
                # Combine all spans in the item name column to get full row header
                leftmost_spans = [s for s in row_spans if s.x0 < item_col_boundary]
                combined_header = " ".join(s.text for s in leftmost_spans)
                if _looks_like_row_header_start(combined_header, table_type):
                    is_new_row = True
            
            if is_new_row and current_row_header:
                data_rows.append(ParsedTableRow(
                    row_id=str(uuid.uuid4()),
                    header=current_row_header,
                    attributes=current_row_attrs.copy(),
                    values=current_row_values.copy(),
                    raw_lines=[]
                ))
                current_row_values = {col: "" for col in value_columns}
                current_row_attrs = init_attrs.copy()
            
            header_parts: List[str] = []
            
            for span in row_spans:
                span_center = (span.x0 + span.x1) / 2
                assigned = False
                
                # Find the closest column (value or attribute) within tolerance
                best_col_type = None  # 'value' or 'attr'
                best_col_idx = None
                best_col_diff = float('inf')
                
                # Check value columns
                for idx, (col_center, _) in enumerate(value_col_positions):
                    diff = abs(span_center - col_center)
                    if diff < 50 and diff < best_col_diff:
                        best_col_diff = diff
                        best_col_idx = idx
                        best_col_type = 'value'
                
                # Check attribute columns
                for idx, (col_center, _) in enumerate(attr_col_positions):
                    diff = abs(span_center - col_center)
                    if diff < 50 and diff < best_col_diff:
                        best_col_diff = diff
                        best_col_idx = idx
                        best_col_type = 'attr'
                
                if best_col_type == 'value':
                    col_name = value_columns[best_col_idx]
                    if current_row_values[col_name]:
                        current_row_values[col_name] += " " + span.text
                    else:
                        current_row_values[col_name] = span.text
                    assigned = True
                elif best_col_type == 'attr':
                    col_name = attr_columns[best_col_idx]
                    normalized_col = _normalize_keyword(col_name)
                    
                    # Map to standard attribute names
                    if normalized_col in {"refintervall", "ref.intervall"}:
                        key = "Ref.intervall"
                    elif normalized_col == "enhet":
                        key = "Enhet"
                    elif normalized_col == "styrka":
                        key = "Styrka"
                    elif normalized_col in {"lakemedelsform", "läkemedelsform", "orm"}:
                        key = "Läkemedelsform"
                    elif normalized_col == "typ":
                        key = "Typ"
                    elif normalized_col == "enh":
                        key = "Enh"
                    else:
                        key = col_name
                    
                    if key in current_row_attrs:
                        if current_row_attrs[key]:
                            current_row_attrs[key] += " " + span.text
                        else:
                            current_row_attrs[key] = span.text
                    assigned = True
                
                if not assigned and span.x0 < item_col_boundary:
                    header_parts.append(span.text)
            
            if header_parts:
                if is_new_row:
                    current_row_header = " ".join(header_parts)
                else:
                    current_row_header += " " + " ".join(header_parts)
                current_row_header = _normalize_line(current_row_header)
        
        if current_row_header:
            data_rows.append(ParsedTableRow(
                row_id=str(uuid.uuid4()),
                header=current_row_header,
                attributes=current_row_attrs.copy(),
                values=current_row_values.copy(),
                raw_lines=[]
            ))
        
        if not data_rows:
            return None
        
        return ParsedTable(
            table_id=str(uuid.uuid4()),
            page_number=page_data.page_number,
            attribute_columns=attr_columns,
            value_columns=value_columns,
            rows=data_rows,
            raw_text=page_data.raw_text
        )

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
        matches = list(PAGE_MARKER_PATTERN.finditer(text))
        if not matches:
            return [(1, 0, len(text))]
        spans = []
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            spans.append((idx + 1, start, end))
        return spans

    def _parse_table_page(self, page_text: str, page_number: int) -> Optional[ParsedTable]:
        raw_lines = [_normalize_line(line) for line in page_text.splitlines() if _normalize_line(line)]
        if not raw_lines:
            return None

        first_date_idx = next((i for i, line in enumerate(raw_lines) if _is_date_line(line)), None)
        if first_date_idx is None or first_date_idx == 0:
            return None

        table_type = self._detect_table_type(raw_lines[:first_date_idx])
        value_columns, header_consumed = self._extract_value_columns(raw_lines[first_date_idx:])
        if not value_columns:
            return None

        if table_type == "medication":
            item_label = "Preparatnamn"
            pre_attributes = ["Styrka", "Läkemedelsform", "Typ", "Enh"]
            trailing_attributes: List[str] = []
        else:
            item_label = "Samtliga"
            pre_attributes = []
            trailing_attributes = ["Ref.intervall", "Enhet"]

        content_start = first_date_idx + header_consumed
        content_lines = raw_lines[content_start:]
        
        # Skip trailing attr headers for vitals
        if trailing_attributes:
            skip = sum(1 for line in content_lines if _normalize_keyword(line) in TRAILING_ATTR_KEYWORDS)
            content_lines = content_lines[skip:]

        attribute_columns = [item_label] + pre_attributes + trailing_attributes
        rows = self._extract_rows(content_lines, value_columns, table_type)

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

    def _detect_table_type(self, pre_date_lines: List[str]) -> str:
        for line in pre_date_lines:
            normalized = _normalize_keyword(line)
            if "preparatnamn" in normalized or normalized in MED_ATTR_KEYWORDS:
                return "medication"
        return "vitals"

    def _extract_value_columns(self, lines: Sequence[str]) -> Tuple[List[str], int]:
        columns: List[str] = []
        i = 0
        consumed = 0
        while i < len(lines):
            line = lines[i]
            if _is_date_line(line):
                header = line
                consumed = i + 1
                if i + 1 < len(lines) and _is_time_line(lines[i + 1]):
                    header = f"{header} {lines[i + 1]}"
                    i += 1
                    consumed = i + 1
                columns.append(header)
                i += 1
                continue
            normalized = _normalize_keyword(line)
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
        value_columns: Sequence[str],
        table_type: str,
    ) -> List[ParsedTableRow]:
        rows: List[ParsedTableRow] = []
        n_values = len(value_columns)
        i = 0

        while i < len(lines):
            line = lines[i]
            
            if not line or _is_noise_line(line):
                i += 1
                continue
            
            # Check for page header content
            if _is_page_header_content(line):
                i += 1
                continue
            
            normalized = _normalize_keyword(line)
            if normalized in TRAILING_ATTR_KEYWORDS or normalized in MED_ATTR_KEYWORDS:
                i += 1
                continue
            
            if not _looks_like_row_header_start(line, table_type):
                i += 1
                continue

            # Found a potential row header
            header_lines = [line]
            i += 1
            
            # For vitals, collect header continuations
            if table_type != "medication":
                while i < len(lines):
                    next_line = lines[i]
                    if not next_line:
                        i += 1
                        continue
                    if _is_header_continuation(next_line, header_lines[-1]):
                        header_lines.append(next_line)
                        i += 1
                    else:
                        break
            
            header = _merge_header_lines(header_lines)
            
            # Collect tokens for this row
            if table_type == "medication":
                tokens, i = self._collect_med_row_tokens(lines, i, n_values)
            else:
                tokens, i = self._collect_vitals_row_tokens(lines, i, header_lines[-1])
            
            # Only create a row if we found meaningful content
            # (at least one value token or attribute)
            has_content = any(_is_med_value_token(t) or _is_type_token(t) for t in tokens)
            if table_type == "vitals":
                has_content = len(tokens) > 0 or True  # Vitals rows can be empty
            
            if has_content or table_type == "vitals":
                row = self._build_row(header, tokens, value_columns, table_type)
                if row:
                    rows.append(row)

        return rows

    def _collect_med_row_tokens(
        self, lines: Sequence[str], start_idx: int, n_values: int
    ) -> Tuple[List[str], int]:
        """Collect tokens for a medication row until we have n_values value tokens or hit next row."""
        tokens: List[str] = []
        value_count = 0
        i = start_idx
        found_first_value = False
        
        while i < len(lines) and value_count < n_values:
            line = lines[i]
            
            if not line or _is_noise_line(line):
                break
            
            # Check for page header content (addresses, names between pages)
            if _is_page_header_content(line):
                break
            
            normalized = _normalize_keyword(line)
            if normalized in TRAILING_ATTR_KEYWORDS or normalized in MED_ATTR_KEYWORDS:
                i += 1
                continue
            
            # After we've found at least one value, check for new row header
            if found_first_value and _looks_like_row_header_start(line, "medication"):
                break
            
            tokens.append(line)
            
            if _is_med_value_token(line):
                value_count += 1
                found_first_value = True
            
            i += 1
        
        return tokens, i

    def _collect_vitals_row_tokens(
        self, lines: Sequence[str], start_idx: int, last_header_line: str
    ) -> Tuple[List[str], int]:
        """Collect tokens for a vitals row until next row header."""
        tokens: List[str] = []
        i = start_idx
        
        while i < len(lines):
            line = lines[i]
            
            if not line or _is_noise_line(line):
                break
            
            normalized = _normalize_keyword(line)
            if normalized in TRAILING_ATTR_KEYWORDS:
                i += 1
                continue
            
            # Check for next row header
            if _looks_like_row_header_start(line, "vitals"):
                if not _is_header_continuation(line, tokens[-1] if tokens else last_header_line):
                    break
            
            tokens.append(line)
            i += 1
        
        return tokens, i

    def _build_row(
        self,
        header: str,
        tokens: List[str],
        value_columns: Sequence[str],
        table_type: str,
    ) -> Optional[ParsedTableRow]:
        if not header:
            return None

        attributes: Dict[str, str] = {}
        values: Dict[str, str] = {col: "" for col in value_columns}
        tokens = [t.strip() for t in tokens if t.strip()]

        if table_type == "medication":
            # Find where values start
            value_start_idx = len(tokens)
            for idx, tok in enumerate(tokens):
                if _is_med_value_token(tok):
                    value_start_idx = idx
                    break
            
            attr_tokens = tokens[:value_start_idx]
            value_tokens = tokens[value_start_idx:]
            
            # Parse attributes
            attributes = self._parse_med_attributes(attr_tokens)
            
            # Assign values
            self._assign_values(value_tokens, value_columns, values)
            
        else:  # vitals
            # Find unit and ref interval from the end
            # Work backwards to identify: [values...] [ref_interval] [unit]
            # Units can be split across lines (e.g., "andetag/m" + "in.")
            unit_val = ""
            ref_val = ""
            value_end = len(tokens)
            
            # Check for unit at the end (may be split across multiple tokens)
            if value_end >= 2:
                # First check if last two tokens form a complete unit
                combined = tokens[-2] + tokens[-1]
                if _is_unit(combined) or tokens[-1] in {"in.", "min.", "min"}:
                    unit_val = combined
                    value_end -= 2
            
            if not unit_val and value_end >= 1:
                # Check if last token alone is a unit
                if _is_unit(tokens[-1]):
                    unit_val = tokens[-1]
                    value_end -= 1
            
            # Check for ref interval before unit
            if value_end > 0 and _is_ref_interval(tokens[value_end - 1]):
                ref_val = tokens[value_end - 1]
                value_end -= 1
            
            attributes["Ref.intervall"] = ref_val
            attributes["Enhet"] = unit_val
            
            value_tokens = tokens[:value_end]
            self._assign_values(value_tokens, value_columns, values)

        return ParsedTableRow(
            row_id=str(uuid.uuid4()),
            header=header,
            attributes=attributes,
            values=values,
            raw_lines=[header] + tokens,
        )

    def _parse_med_attributes(self, tokens: List[str]) -> Dict[str, str]:
        """Parse medication attributes from tokens."""
        attributes = {"Styrka": "", "Läkemedelsform": "", "Typ": "", "Enh": ""}
        
        if not tokens:
            return attributes
        
        # Find Typ token (Rb, Tf, Vb, etc.)
        typ_idx = None
        for idx, tok in enumerate(tokens):
            if _is_type_token(tok):
                typ_idx = idx
                break
        
        if typ_idx is not None:
            pre_typ = tokens[:typ_idx]
            post_typ = tokens[typ_idx:]
            
            # Parse pre-Typ tokens as Styrka + Läkemedelsform
            styrka_parts: List[str] = []
            form_parts: List[str] = []
            
            for tok in pre_typ:
                # If we haven't found styrka yet and this has digits, it's styrka
                if not styrka_parts and any(ch.isdigit() for ch in tok):
                    styrka_parts.append(tok)
                elif styrka_parts and not form_parts and len(tok) <= 6 and not any(ch.isdigit() for ch in tok):
                    # Short unit suffix for styrka
                    styrka_parts.append(tok)
                else:
                    form_parts.append(tok)
            
            attributes["Styrka"] = " ".join(styrka_parts)
            attributes["Läkemedelsform"] = " ".join(form_parts)
            
            # Typ and Enh
            if post_typ:
                attributes["Typ"] = post_typ[0]
                if len(post_typ) > 1:
                    attributes["Enh"] = post_typ[1]
        else:
            # No Typ found - put everything in Läkemedelsform
            attributes["Läkemedelsform"] = " ".join(tokens)
        
        return attributes

    def _assign_values(
        self,
        tokens: List[str],
        value_columns: Sequence[str],
        values: Dict[str, str]
    ) -> None:
        if not tokens:
            return
        
        # Merge tokens that belong together
        merged: List[str] = []
        for token in tokens:
            if merged and self._should_merge(merged[-1], token):
                merged[-1] = f"{merged[-1]} {token}"
            else:
                merged.append(token)
        
        for i, col in enumerate(value_columns):
            if i < len(merged):
                values[col] = merged[i]

    def _should_merge(self, prev: str, current: str) -> bool:
        if not prev or not current:
            return False
        prev = prev.strip()
        current = current.strip()
        if prev.endswith('+') or current.startswith('+'):
            return True
        if any(ch.isdigit() for ch in prev) and len(current) <= 4 and not any(ch.isdigit() for ch in current):
            if current in {"---->", "?"}:
                return False
            return True
        return False

    def _remove_spans(self, text: str, spans: List[Tuple[int, int, ParsedTable]]) -> str:
        if not spans:
            return text
        spans = sorted(spans, key=lambda s: s[0])
        result_parts: List[str] = []
        cursor = 0
        for start, end, table in spans:
            if cursor < start:
                result_parts.append(text[cursor:start])
            result_parts.append(f"\n\n[TABLE {table.table_id} REMOVED]\n\n")
            cursor = end
        if cursor < len(text):
            result_parts.append(text[cursor:])
        return "".join(result_parts).strip()
