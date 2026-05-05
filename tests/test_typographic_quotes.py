from __future__ import annotations

import pytest

from utils.typographic_quotes import LDQUO, LSQUO, RDQUO, RSQUO, apply_smart_quotes


def q(html: str) -> str:
    """Return just the transformed HTML string, discarding the count."""
    result, _ = apply_smart_quotes(html)
    return result


def count(html: str) -> int:
    _, n = apply_smart_quotes(html)
    return n


# ---------------------------------------------------------------------------
# Double quotes
# ---------------------------------------------------------------------------

def test_double_quote_opening_after_space():
    assert q('<p>She said "hello".</p>') == f"<p>She said {LDQUO}hello{RDQUO}.</p>"


def test_double_quote_at_start_of_text_node():
    assert q('"Hello"') == f"{LDQUO}Hello{RDQUO}"


def test_double_quote_opening_after_open_paren():
    assert q('<p>("word")</p>') == f"<p>({LDQUO}word{RDQUO})</p>"


def test_double_quote_opening_after_bracket():
    assert q('<p>["item"]</p>') == f"<p>[{LDQUO}item{RDQUO}]</p>"


# ---------------------------------------------------------------------------
# Single quotes / apostrophes
# ---------------------------------------------------------------------------

def test_apostrophe_in_contraction():
    result = q("<p>don't stop</p>")
    assert f"don{RSQUO}t" in result


def test_apostrophe_possessive():
    result = q("<p>James's book</p>")
    assert f"James{RSQUO}s" in result


def test_single_quote_opening_after_space():
    result = q("<p>She said 'hello'.</p>")
    assert f" {LSQUO}hello{RSQUO}" in result


def test_single_quote_at_start_of_text_node():
    assert q("'Hello'") == f"{LSQUO}Hello{RSQUO}"


# ---------------------------------------------------------------------------
# Decade apostrophe edge case (direction doesn't matter, must be curly)
# ---------------------------------------------------------------------------

def test_decade_abbreviation_is_curly():
    result = q("<p>the '60s</p>")
    assert "'" not in result, "straight apostrophe should be gone"
    # Either direction of curly quote is acceptable
    assert LSQUO in result or RSQUO in result


# ---------------------------------------------------------------------------
# HTML attributes must never be touched
# ---------------------------------------------------------------------------

def test_href_attribute_unchanged():
    html = '<a href="/courses/1/pages/don\'t-touch">link</a>'
    assert q(html) == html


def test_data_attribute_unchanged():
    html = '<span data-value=\'he said "yes"\'>text</span>'
    result = q(html)
    assert 'data-value=\'he said "yes"\'' in result


# ---------------------------------------------------------------------------
# Code / pre blocks must not be touched
# ---------------------------------------------------------------------------

def test_code_block_untouched():
    html = '<code>print("hello")</code>'
    assert q(html) == html
    assert count(html) == 0


def test_pre_block_untouched():
    html = "<pre>x = 'value'</pre>"
    assert q(html) == html
    assert count(html) == 0


def test_inline_code_inside_paragraph_untouched():
    html = "<p>Use <code>'--flag'</code> to enable.</p>"
    result = q(html)
    assert "<code>'--flag'</code>" in result


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------

def test_empty_string_returns_empty():
    assert q("") == ""
    assert count("") == 0


def test_no_quotes_returns_unchanged():
    html = "<p>No quotes here at all.</p>"
    assert q(html) == html
    assert count(html) == 0


def test_already_curly_unchanged():
    html = f"<p>{LDQUO}already curly{RDQUO}</p>"
    assert q(html) == html
    assert count(html) == 0


# ---------------------------------------------------------------------------
# Replacement count
# ---------------------------------------------------------------------------

def test_count_tracks_replacements():
    # Two double quotes (open + close) = 2
    assert count("<p>She said \"hello\".</p>") == 2


def test_count_mixed():
    # "hello" (2) + don't (1) = 3
    assert count('<p>"hello" and don\'t</p>') == 3
