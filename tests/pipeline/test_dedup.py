from __future__ import annotations

import json

import pytest

from job_radar.pipeline.dedup import canonical_key, is_duplicate


def test_canonical_key_ignores_case_spacing_punctuation_and_accents(matching_offer):
    variant = matching_offer.model_copy(
        update={
            "title": "  PRODUCT-OPERATIONS specialist ",
            "company": "Northstar, Works",
            "location": "NORTH district",
        }
    )

    assert canonical_key(variant) == canonical_key(matching_offer)


def test_duplicate_requires_company_title_and_location_above_threshold(matching_offer):
    other_location = matching_offer.model_copy(update={"location": "South District"})

    assert is_duplicate(matching_offer, matching_offer, threshold=90)
    assert not is_duplicate(matching_offer, other_location, threshold=90)


def test_near_matches_can_merge_only_when_every_component_clears_threshold(
    matching_offer,
):
    near_match = matching_offer.model_copy(
        update={
            "company": "Northstar Work",
            "title": "Product Operations Specialist II",
            "location": "North District Centre",
        }
    )

    assert is_duplicate(matching_offer, near_match, threshold=70)
    assert not is_duplicate(matching_offer, near_match, threshold=95)


def test_canonical_key_uses_nfkc_and_casefold_without_ascii_transliteration(matching_offer):
    fullwidth = matching_offer.model_copy(
        update={
            "company": "ＮＯＲＴＨＳＴＡＲ ＷＯＲＫＳ",
            "title": "ＰＲＯＤＵＣＴ ＯＰＥＲＡＴＩＯＮＳ ＳＰＥＣＩＡＬＩＳＴ",
            "location": "ＮＯＲＴＨ ＤＩＳＴＲＩＣＴ",
        }
    )

    assert canonical_key(fullwidth) == canonical_key(matching_offer)


@pytest.mark.parametrize(
    ("company", "title", "location", "expected_fragment"),
    [
        ("星河公司", "数据工程师", "北京", "星河公司"),
        ("青空会社", "設計者", "東京", "青空会社"),
        ("КОМПАНИЯ", "ИНЖЕНЕР", "МОСКВА", "компания"),
    ],
)
def test_canonical_key_preserves_non_latin_writing_systems(
    matching_offer, company: str, title: str, location: str, expected_fragment: str
):
    offer = matching_offer.model_copy(
        update={"company": company, "title": title, "location": location}
    )

    key = canonical_key(offer)

    assert expected_fragment in key
    assert key != "||"


def test_unrelated_chinese_and_japanese_offers_do_not_merge(matching_offer):
    chinese = matching_offer.model_copy(
        update={"company": "星河公司", "title": "数据工程师", "location": "北京"}
    )
    japanese = matching_offer.model_copy(
        update={"company": "青空会社", "title": "設計者", "location": "東京"}
    )

    assert canonical_key(chinese) != canonical_key(japanese)
    assert not is_duplicate(chinese, japanese, threshold=90)


def test_emoji_only_components_remain_distinct(matching_offer):
    first = matching_offer.model_copy(
        update={"company": "🏢", "title": "🧑‍💻", "location": "🌍"}
    )
    second = matching_offer.model_copy(
        update={"company": "🏭", "title": "🎨", "location": "🌙"}
    )

    assert canonical_key(first) == '["🏢","🧑‍💻","🌍"]'
    assert not is_duplicate(first, second, threshold=90)


def test_empty_canonical_component_is_rejected(matching_offer):
    invalid = matching_offer.model_copy(update={"company": "---"})

    with pytest.raises(ValueError, match="company.+empty"):
        canonical_key(invalid)
    with pytest.raises(ValueError, match="company.+empty"):
        is_duplicate(invalid, matching_offer)


def test_canonical_key_structurally_encodes_separator_bearing_components(
    matching_offer,
):
    first = matching_offer.model_copy(
        update={"company": "alpha|beta", "title": "gamma", "location": "delta"}
    )
    second = matching_offer.model_copy(
        update={"company": "alpha", "title": "beta", "location": "gamma|delta"}
    )

    first_key = canonical_key(first)
    second_key = canonical_key(second)

    assert first_key != second_key
    assert json.loads(first_key) == ["alpha|beta", "gamma", "delta"]
    assert json.loads(second_key) == ["alpha", "beta", "gamma|delta"]
