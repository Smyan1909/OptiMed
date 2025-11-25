from optimed.utils.pdf_table_parser import PDFTableParser


SAMPLE_TEXT = """
Sida 1 (1)
Preparatnamn
Styrka
Läkemedelsform
Typ
Enh
25-11-17
08:00
25-11-18
09:00
Th Diben 1,5 Kcal
1.3
Oral
Rb
ml
500 ml
---->
Movicol
5 mg
Pulver
Rb
st
1 dos
0
"""


def test_pdf_table_parser_extracts_rows():
    parser = PDFTableParser()
    output = parser.extract_tables(SAMPLE_TEXT, document_id="doc-1")

    assert output.tables, "Expected at least one parsed table"

    table = output.tables[0]
    assert "Preparatnamn" in table.attribute_columns
    assert table.value_columns == ["25-11-17 08:00", "25-11-18 09:00"]
    assert len(table.rows) == 2

    first_row = table.rows[0]
    assert first_row.header == "Th Diben 1,5 Kcal"
    assert first_row.values["25-11-17 08:00"] == "500 ml"
    assert first_row.values["25-11-18 09:00"] == "---->"


