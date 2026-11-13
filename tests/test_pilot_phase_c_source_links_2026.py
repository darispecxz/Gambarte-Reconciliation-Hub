"""Pure offline tests for pilot source-to-projection integrity findings."""
from scripts.pilot_phase_c_source_links_2026 import assess


def test_equal_local_counts_are_not_certification():
    assert assess(25,25,0,0,0)=="LOCAL_LINK_COUNTS_MATCH_NOT_CERTIFIED"


def test_missing_projection_is_flagged_even_when_totals_happen_to_match():
    assert assess(25,25,1,0,0)=="LOCAL_LINK_INTEGRITY_REVIEW"


def test_missing_source_or_duplicates_are_flagged():
    assert assess(25,24,0,1,0)=="LOCAL_LINK_INTEGRITY_REVIEW"
    assert assess(25,25,0,0,1)=="LOCAL_LINK_INTEGRITY_REVIEW"
