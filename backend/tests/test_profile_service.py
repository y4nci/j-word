import asyncio

from onboarding.profile_service import ProfileService
from tests.shared.llm_fakes import ScriptedLLM


def test_off_schema_llm_output_is_normalised_not_fatal():
    """Regression: kind="internship" from the LLM used to crash POST /profiles with a 500."""
    llm = ScriptedLLM({"into a structured profile": {
        "full_name": "Ada", "email": "ada@example.com", "phone": "null", "links": None,
        "skills": "Python, SQL ,  Docker",            # string instead of list
        "languages": ["German (C1)", None, ""],
        "experiences": [
            {"kind": "Internship", "title": "Data Intern", "organization": "Acme",
             "highlights": "Built a dashboard, used by 3 teams", "skills": ["Python", 3]},
            {"kind": "thesis", "title": "Bachelor thesis", "summary": None},
            {"kind": "hobby", "title": "Chess club"},
            {"kind": "job", "title": ""},               # no title -> dropped
            "not an object",                           # ignored
        ],
    }})
    profile = asyncio.run(ProfileService(llm).build_profile(cv_text="CV", proto_cover_letter="letter"))

    assert profile.phone is None and profile.links == {}
    assert profile.skills == ["Python", "SQL", "Docker"]
    assert profile.languages == ["German (C1)"]
    assert [(e.id, e.kind, e.title) for e in profile.experiences] == [
        ("exp-1", "job", "Data Intern"),
        ("exp-2", "project", "Bachelor thesis"),
        ("exp-3", "other", "Chess club"),
    ]
    assert profile.experiences[0].highlights == ["Built a dashboard, used by 3 teams"]
    assert profile.experiences[0].skills == ["Python", "3"]
