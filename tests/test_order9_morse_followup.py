"""Order-9 Morse follow-up must never reinterpret historical rows silently."""

from audits.resolve_order9_timeouts import (
    EXPECTED,
    encode,
    historical_rows,
    latex,
)


def test_type_encoding_and_display():
    assert encode({}) == "0"
    assert encode({3: 2, 2: 1}) == "2:1;3:2"
    assert latex("0") == "Contractible"
    assert latex("2:1;3:2") == r"\(S^{2}\vee \bigvee_{2}S^{3}\)"


def test_historical_timeout_rows_have_the_expected_original_graph6():
    summary, rows = historical_rows()
    assert summary["orders"][0]["counts"]["graphs"] == 261080
    assert set(rows) == set(EXPECTED)
    for index, row in rows.items():
        assert row["graph6"] == EXPECTED[index]
        assert row["status_g"] == "EXACT"
        assert row["status_kg"] == "LIMITED"
        assert row["htype_kg"] == "UNKNOWN"
        assert row["comparison"] == "UNRESOLVED"
