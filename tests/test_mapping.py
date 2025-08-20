#tests/test_mapping.py
import pytest
from utils.mapping import record_mapping


def test_record_mapping_with_ids_and_slugs():
    id_map = {}
    slug_map = {}

    record_mapping(
        old_id=42,
        new_id=314,
        old_slug="welcome-old",
        new_slug="welcome",
        id_map=id_map,
        slug_map=slug_map,
    )

    assert id_map == {42: 314}
    assert slug_map == {"welcome-old": "welcome"}


def test_record_mapping_with_slug_only():
    id_map = {}
    slug_map = {}

    record_mapping(
        old_id=None,
        new_id=None,
        old_slug="faq-old",
        new_slug="faq",
        id_map=id_map,
        slug_map=slug_map,
    )

    assert id_map == {}
    assert slug_map == {"faq-old": "faq"}


def test_record_mapping_with_id_only():
    id_map = {}
    slug_map = {}

    record_mapping(
        old_id=7,
        new_id=99,
        old_slug=None,
        new_slug=None,
        id_map=id_map,
        slug_map=slug_map,
    )

    assert id_map == {7: 99}
    assert slug_map == {}


def test_record_mapping_ignores_none_values():
    id_map = {}
    slug_map = {}

    record_mapping(
        old_id=None,
        new_id=None,
        old_slug=None,
        new_slug=None,
        id_map=id_map,
        slug_map=slug_map,
    )

    assert id_map == {}
    assert slug_map == {}
