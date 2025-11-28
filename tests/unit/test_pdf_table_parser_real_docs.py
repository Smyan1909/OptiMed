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

    # Check Th Diben row
    th_diben = next(row for row in meds_table.rows if "Th Diben" in row.header)
    assert th_diben.attributes["Typ"] == "Hp"  # Hp is the type for this medication
    assert "500 + 500 + 500" in th_diben.values["25-11-17"]

    # Check Orlistat Stada row
    orlistat = next(row for row in meds_table.rows if "Orlistat Stada" in row.header)
    assert orlistat.attributes["Styrka"] == "120 mg"
    assert orlistat.attributes["Typ"] == "Rb"
    assert orlistat.values["25-11-17"] == "1"

    # Check Nystatin Abacus row
    nystatin = next(row for row in meds_table.rows if "Nystatin Abacus" in row.header)
    assert nystatin.attributes["Typ"] == "Rb"
    assert nystatin.attributes["Enh"] == "ml"
    assert "1 + 1 + 1 + 1" in nystatin.values["25-11-17"]


def test_vitals_table_preserves_timestamp_values():
    tables = parse_tables("test_vitals_extracted.txt").tables
    assert tables, "Expected tables to be detected in test_vitals_extracted.txt"

    vitals_table = next(
        table for table in tables if "25-11-14 12:36" in table.value_columns
    )

    # Check Hemblodtryck systoliskt medelvärde
    systolic_mean = next(
        row for row in vitals_table.rows
        if "Hemblodtryck systoliskt" in row.header and "medelvärde" in row.header
    )
    assert systolic_mean.values["25-11-14 12:36"] == "141"
    assert systolic_mean.attributes["Enhet"] == "mmHg"

    # Check Hemblodtryck systoliskt, dag 2 - morgon
    systolic_day2 = next(
        row for row in vitals_table.rows
        if "Hemblodtryck systoliskt" in row.header and "dag 2" in row.header and "morgon" in row.header
    )
    assert systolic_day2.values["25-11-14 12:36"] == "120"
    assert systolic_day2.attributes["Enhet"] == "mmHg"

    # Check Andningsfrekvens
    respiration = next(row for row in vitals_table.rows if row.header == "Andningsfrekvens")
    assert respiration.values["25-11-14 12:36"] == "12"
    assert respiration.attributes["Ref.intervall"] == "5-50"
    assert respiration.attributes["Enhet"] == "andetag/min."
