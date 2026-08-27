from __future__ import annotations

import pytest

from job_radar.pipeline.terms import contains_term, find_term


@pytest.mark.parametrize(
    ("term", "text"),
    [
        ("AI", "Paid Growth Manager"),
        ("Go", "Google Analytics"),
        ("intern", "international operations"),
    ],
)
def test_terms_do_not_match_inside_larger_unicode_words(term: str, text: str) -> None:
    assert not contains_term(text, term)
    assert find_term(text, (term,)) is None


@pytest.mark.parametrize(
    ("term", "text"),
    [
        ("R", "R&D analyst"),
        ("C", "C++ engineer"),
        ("C+", "C++ engineer"),
    ],
)
def test_short_terms_do_not_match_prefixes_of_punctuated_skills(
    term: str, text: str
) -> None:
    assert find_term(text, (term,)) is None


@pytest.mark.parametrize("term", ["C++", "C#", ".NET", "Node.js"])
def test_punctuated_skills_match_as_complete_tokens_with_exact_citations(term: str) -> None:
    text = f"Stack required: {term}; production experience."

    match = find_term(text, (term,))

    assert match is not None
    assert match.citation == term
    assert match.term_index == 0


def test_phrase_matching_is_casefolded_and_returns_original_source_text() -> None:
    text = "Nous cherchons une expertise Data Quality confirmée."

    match = find_term(text, ("data quality",))

    assert match is not None
    assert match.citation == "Data Quality"


def test_nfkc_equivalent_term_keeps_the_original_compatibility_citation() -> None:
    text = "Compétence: Ｎｏｄｅ．ｊｓ."

    match = find_term(text, ("Node.js",))

    assert match is not None
    assert match.citation == "Ｎｏｄｅ．ｊｓ"
