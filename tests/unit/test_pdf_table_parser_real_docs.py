from pathlib import Path

from optimed.utils.pdf_table_parser import PDFTableParser


ROOT = Path(__file__).resolve().parents[2]
TEXT_FIXTURES = ROOT / "tests" / "fixtures" / "pdf_text"


def parse_tables(fixture_name: str):
    text = (TEXT_FIXTURES / fixture_name).read_text(encoding="utf-8")
    parser = PDFTableParser()
    return parser.extract_tables(text, document_id=fixture_name)


def test_medication_table_parsing_produces_expected_rows():
    tables = parse_tables("lm_lista_extracted.txt").tables
    assert tables, "Expected tables to be detected in lm_lista_extracted.txt"

    meds_table = next(
        table for table in tables if "25-11-24" in table.value_columns
    )

    th_diben = next(row for row in meds_table.rows if "Th Diben" in row.header)
    assert th_diben.attributes["Typ"] == "Rb"
    assert th_diben.attributes["Enh"] == "ml"
    assert th_diben.values["25-11-17"] == "500 + 500 +"

    nystatin = next(row for row in meds_table.rows if "Nystatin Abacus" in row.header)
    assert nystatin.attributes["Typ"] == "Oral"
    assert nystatin.attributes["Enh"] == "suspension"
    assert nystatin.values["25-11-17"] == "Rb ml 1 + 1 + 1 + 1"


def test_vitals_table_preserves_timestamp_values():
    tables = parse_tables("test_vitals_extracted.txt").tables
    assert tables, "Expected tables to be detected in test_vitals_extracted.txt"

    vitals_table = next(
        table for table in tables if "25-11-14 12:36" in table.value_columns
    )

    systolic_morning = next(
        row for row in vitals_table.rows
        if "Hemblodtryck systoliskt" in row.header
        and row.attributes.get("Utskriven") == "dag 2 - morgon"
    )
    assert systolic_morning.values["25-11-14 12:36"] == "120 mmHg"

    diastolic_evening = next(
        row for row in vitals_table.rows
        if "Hemblodtryck" in row.header
        and row.attributes.get("Utskriven", "").startswith("diastoliskt, dag 2 -")
        and "kv" in row.attributes.get("Utskriven", "")
    )
    assert diastolic_evening.values["25-11-14 12:36"] == "90 mmHg"

    respiration = next(row for row in vitals_table.rows if row.header == "Andningsfrekvens")
    assert respiration.values["25-11-14 12:36"] == "12"
    assert respiration.attributes["Ref.intervall"] == "5-50"
    assert respiration.attributes["Enhet"] == "andetag/min."

