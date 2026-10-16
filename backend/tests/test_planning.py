from onboarding.models import JobFilters
from onboarding.planning_service import apply_suggested_filters
from shared.enums import EmploymentType, WorkMode


def test_suggested_filters_only_fill_what_the_user_left_empty():
    filters = JobFilters(work_modes=[WorkMode.REMOTE])  # user chose this explicitly
    applied = apply_suggested_filters(filters, {
        "employment_types": ["working_student", "part_time", "Werkstudent", "unknown"],  # invalid values dropped
        "work_modes": ["hybrid"],                                                       # user's choice kept
        "locations": ["Berlin", " "],
    })
    assert filters.employment_types == [EmploymentType.WORKING_STUDENT, EmploymentType.PART_TIME]
    assert filters.work_modes == [WorkMode.REMOTE]
    assert filters.locations == ["Berlin"]
    assert applied == {"employment_types": ["working_student", "part_time"], "locations": ["Berlin"]}


def test_missing_or_malformed_suggestions_change_nothing():
    filters = JobFilters()
    assert apply_suggested_filters(filters, None) == {}
    assert apply_suggested_filters(filters, {"employment_types": "part_time"}) == {}
    assert filters == JobFilters()
