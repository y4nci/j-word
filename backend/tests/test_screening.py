from screening.screening_service import _to_summary


def test_summary_parsing_drops_placeholders_and_bad_types():
    summary = _to_summary({
        "short_description": "  Analyse sales data.  ",
        "pay": "Not stated", "hours": "", "employment": None, "work_mode": {"x": 1},
        "location": "Berlin", "languages": "German", "key_requirements": ["SQL", None, " ", "Excel"],
    })
    assert summary.short_description == "Analyse sales data."
    assert summary.pay is None and summary.hours is None and summary.work_mode is None
    assert summary.location == "Berlin"
    assert summary.languages == ["German"]
    assert summary.key_requirements == ["SQL", "Excel"]


def test_empty_or_invalid_summary_is_none():
    assert _to_summary(None) is None
    assert _to_summary("text") is None
    assert _to_summary({"pay": "null", "languages": []}) is None
