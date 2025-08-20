from utils.strings import sanitize_slug

def test_basic_spaces_to_dash_lower():
    assert sanitize_slug("Hello World") == "hello-world"

def test_collapse_and_trim():
    assert sanitize_slug("  --Hello__World!!  ") == "hello-world"

def test_colon_punctuation_removed():
    assert sanitize_slug("Unit 1: Week A") == "unit-1-week-a"

def test_unicode_accents_removed():
    assert sanitize_slug("école – résumé.pdf") == "ecole-resume-pdf"

def test_only_bad_chars_results_empty():
    assert sanitize_slug("$$$") == ""

def test_preserve_numbers_and_dashes():
    assert sanitize_slug("Lecture 12-3 — v2") == "lecture-12-3-v2"
