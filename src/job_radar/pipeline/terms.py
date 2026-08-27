"""Unicode-aware token and phrase matching primitives."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TermMatch:
    citation: str
    term_index: int


def _normalization_units(text: str) -> Iterable[tuple[int, int]]:
    if not text:
        return
    start = 0
    for index in range(1, len(text)):
        if unicodedata.combining(text[index]) == 0:
            yield start, index
            start = index
    yield start, len(text)


def _normalize_with_spans(text: str) -> tuple[str, list[tuple[int, int]]]:
    characters: list[str] = []
    spans: list[tuple[int, int]] = []
    for start, end in _normalization_units(text):
        normalized = unicodedata.normalize("NFKC", text[start:end]).casefold()
        for character in normalized:
            if character.isspace():
                if characters and characters[-1] == " ":
                    spans[-1] = (spans[-1][0], end)
                else:
                    characters.append(" ")
                    spans.append((start, end))
            else:
                characters.append(character)
                spans.append((start, end))
    return "".join(characters), spans


def normalize_term(value: str) -> str:
    """Return an NFKC/casefold comparison form without dropping punctuation."""

    normalized, _spans = _normalize_with_spans(value)
    return normalized.strip()


def _is_word_character(character: str) -> bool:
    return character == "_" or character.isalnum()


_TOKEN_PUNCTUATION = frozenset({"+", "#", "&"})


def _continues_token_on_left(text: str, start: int) -> bool:
    if start == 0:
        return False
    character = text[start - 1]
    return _is_word_character(character) or character in _TOKEN_PUNCTUATION or character == "."


def _continues_token_on_right(text: str, end: int) -> bool:
    if end == len(text):
        return False
    character = text[end]
    if _is_word_character(character) or character in _TOKEN_PUNCTUATION:
        return True
    return (
        character == "."
        and end + 1 < len(text)
        and _is_word_character(text[end + 1])
    )


def find_term(text: str, terms: Iterable[str]) -> TermMatch | None:
    """Find a complete token or phrase and preserve its exact source citation."""

    normalized_text, spans = _normalize_with_spans(text)
    for term_index, term in enumerate(terms):
        normalized_term = normalize_term(term)
        if not normalized_term:
            continue
        cursor = 0
        while True:
            start = normalized_text.find(normalized_term, cursor)
            if start < 0:
                break
            end = start + len(normalized_term)
            left_is_word = _continues_token_on_left(normalized_text, start)
            right_is_word = _continues_token_on_right(normalized_text, end)
            if not left_is_word and not right_is_word:
                source_start = spans[start][0]
                source_end = spans[end - 1][1]
                return TermMatch(
                    citation=text[source_start:source_end],
                    term_index=term_index,
                )
            cursor = start + 1
    return None


def contains_term(text: str, term: str) -> bool:
    return find_term(text, (term,)) is not None
