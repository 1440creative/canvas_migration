# tests/importers/test_import_pages.py
import json
from pathlib import Path

# Adjust import path if your module name differs
from importers.import_pages import import_pages

def _seed_page(tmp_export, *, old_id: int, slug: str, title="FAQ", html="Hello",
               published=True, front_page=False, position=None):
    pages_dir = tmp_export / "pages" / str(old_id)
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "index.html").write_text(html, encoding="utf-8")
    meta = {
        "id": old_id,
        "title": title,
        "url": slug,
        "published": published,
        "front_page": front_page,
    }
    if position is not None:
        meta["position"] = position
    (pages_dir / "page_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return pages_dir

def test_import_pages_happy_path(tmp_export, id_map, requests_mock, dummy_canvas):
    """
    POST returns id+url in JSON. We expect:
      - id_map['pages'][old_id] == new_id
      - id_map['pages_url'][old_slug] == new_slug
    """
    _seed_page(tmp_export, old_id=42, slug="faq-old", front_page=False)

    # POST create returns JSON body with id and url
    requests_mock.post(
        "https://api.test/api/v1/courses/101/pages",
        json={"id": 314, "url": "faq"},
        status_code=201,
    )

    import_pages(
        target_course_id=101,
        export_root=tmp_export,
        canvas=dummy_canvas,
        id_map=id_map,
    )

    assert id_map["pages"][42] == 314
    assert id_map["pages_url"]["faq-old"] == "faq"

def test_import_pages_slug_only_response_follows_location(tmp_export, id_map, requests_mock, dummy_canvas):
    """
    POST returns only slug and Location header; importer must GET Location to learn id.
    """
    _seed_page(tmp_export, old_id=77, slug="about-old", front_page=False)

    # POST create -> slug only, Location header to follow
    requests_mock.post(
        "https://api.test/api/v1/courses/101/pages",
        json={"url": "about"},
        status_code=201,
        headers={"Location": "https://api.test/api/v1/courses/101/pages/about"},
    )
    # Followed GET returns full object with id+url
    requests_mock.get(
        "https://api.test/api/v1/courses/101/pages/about",
        json={"id": 888, "url": "about"},
        status_code=200,
    )

    import_pages(
        target_course_id=101,
        export_root=tmp_export,
        canvas=dummy_canvas,
        id_map=id_map,
    )

    assert id_map["pages"][77] == 888
    assert id_map["pages_url"]["about-old"] == "about"

def test_import_pages_slug_only_no_location_updates_slug_map_only(tmp_export, id_map, requests_mock, dummy_canvas):
    """
    POST returns slug but no Location; importer should at least update pages_url.
    """
    _seed_page(tmp_export, old_id=99, slug="welcome-old", front_page=False)

    requests_mock.post(
        "https://api.test/api/v1/courses/101/pages",
        json={"url": "welcome"},
        status_code=201,
    )
    # No GET stub → importer should not crash; it just won’t have a numeric id.

    import_pages(
        target_course_id=101,
        export_root=tmp_export,
        canvas=dummy_canvas,
        id_map=id_map,
    )

    assert id_map["pages_url"]["welcome-old"] == "welcome"
    # numeric id may be absent
    assert 99 not in id_map.get("pages", {})

def test_front_page_set_after_creation(tmp_export, id_map, requests_mock, dummy_canvas):
    """
    If metadata.front_page is True, importer should PUT to /courses/:id/front_page after create.
    """
    _seed_page(tmp_export, old_id=5, slug="home-old", front_page=True)

    requests_mock.post(
        "https://api.test/api/v1/courses/101/pages",
        json={"id": 500, "url": "home"},
        status_code=201,
    )
    # Canvas front-page endpoint; payload shape may vary—only assert it is called.
    requests_mock.put(
        "https://api.test/api/v1/courses/101/front_page",
        json={"url": "home"},
        status_code=200,
    )

    import_pages(
        target_course_id=101,
        export_root=tmp_export,
        canvas=dummy_canvas,
        id_map=id_map,
    )

    assert id_map["pages"][5] == 500
    assert id_map["pages_url"]["home-old"] == "home"
    assert requests_mock.called
    assert any(
        m.method == "PUT" and m.url == "https://api.test/api/v1/courses/101/front_page"
        for m in requests_mock.request_history
    )

def test_logs_position_warning_once(tmp_export, id_map, requests_mock, dummy_canvas, caplog):
    """
    If exporter saved a page 'position' and the server returns a different position,
    importer should log one 'position mismatch' warning (no network crashes).
    """
    caplog.set_level("INFO")

    # exported position=3
    _seed_page(tmp_export, old_id=12, slug="pos-old", front_page=False, position=3)

    # POST returns slug only + Location to follow
    requests_mock.post(
        "https://api.test/api/v1/courses/101/pages",
        json={"url": "pos"},
        status_code=201,
        headers={"Location": "https://api.test/api/v1/courses/101/pages/pos"},
    )
    # Followed GET returns id and a different position=8
    requests_mock.get(
        "https://api.test/api/v1/courses/101/pages/pos",
        json={"id": 1200, "url": "pos", "position": 8},
        status_code=200,
    )

    import_pages(
        target_course_id=101,
        export_root=tmp_export,
        canvas=dummy_canvas,
        id_map=id_map,
    )

    # mapping updated
    assert id_map["pages"][12] == 1200
    assert id_map["pages_url"]["pos-old"] == "pos"

    # warning logged once
    msgs = [r.getMessage().lower() for r in caplog.records]
    assert any("position mismatch" in m for m in msgs)
    assert sum("position mismatch" in m for m in msgs) == 1
