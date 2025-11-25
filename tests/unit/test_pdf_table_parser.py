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
500
---->
Movicol
5 mg
Pulver
Rb
st
1
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
    # Values are now small numbers or arrows
    assert first_row.values["25-11-17 08:00"] == "500"
    assert first_row.values["25-11-18 09:00"] == "---->"

    second_row = table.rows[1]
    assert second_row.header == "Movicol"
    # Styrka includes the strength value, may include form text before Typ
    assert "5 mg" in second_row.attributes["Styrka"]
    assert second_row.attributes["Typ"] == "Rb"
