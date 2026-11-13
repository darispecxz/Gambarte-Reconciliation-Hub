"""Synthetic metadata inventory guards."""
from scripts.pilot_reversal_metadata_2026 import parse_metadata, QUERIES
from app.integrations.source import validate_read_query

def test_queries_are_bounded_read_only_metadata():
    assert len(QUERIES)==3
    for sql in QUERIES:
        validate_read_query(sql)
        assert "information_schema." in sql
        assert "LIMIT 200" in sql

def test_metadata_marks_candidates_not_certified():
    rows=parse_metadata("CHILE",
        [{"TABLE_NAME":"pago_history","TABLE_TYPE":"BASE TABLE"}],
        [{"TABLE_NAME":"pago","COLUMN_NAME":"estado","DATA_TYPE":"int"}],
        [{"TABLE_NAME":"pago","INDEX_NAME":"PRIMARY","SEQ_IN_INDEX":1,
          "COLUMN_NAME":"id_pago","NON_UNIQUE":0}])
    assert len(rows)==3
    assert rows[0][1]=="CANDIDATE_TABLE"
    assert "no prueba" in rows[0][-1]
    assert rows[2][1]=="SOURCE_INDEX"
