"""اختبارات خدمة المناطق (Zones)."""

from __future__ import annotations

import pytest

from app.core.db import Database
from app.core.rules import load_zones_from_db
from app.core.zones import ZoneService


def _seed_video(db: Database) -> int:
    db.execute("INSERT INTO videos (filepath, filename) VALUES ('/v/a.mp4', 'a.mp4')")
    row = db.fetch_one("SELECT id FROM videos WHERE filepath = '/v/a.mp4'")
    assert row is not None
    return int(row[0])


def test_add_and_list_zone(tmp_db: Database) -> None:
    vid = _seed_video(tmp_db)
    svc = ZoneService(db=tmp_db)
    zid = svc.add_zone(vid, "stop_line", [(0, 500), (1920, 500)])
    assert zid > 0

    zones = svc.list_zones(vid)
    assert len(zones) == 1
    assert zones[0].zone_type == "stop_line"
    assert zones[0].polygon == [(0.0, 500.0), (1920.0, 500.0)]


def test_add_zone_rejects_unknown_type(tmp_db: Database) -> None:
    vid = _seed_video(tmp_db)
    svc = ZoneService(db=tmp_db)
    with pytest.raises(ValueError, match="نوع منطقة غير مدعوم"):
        svc.add_zone(vid, "banana", [(0, 0), (1, 1)])


def test_add_zone_enforces_min_points(tmp_db: Database) -> None:
    vid = _seed_video(tmp_db)
    svc = ZoneService(db=tmp_db)
    with pytest.raises(ValueError, match="نقاط على الأقل"):
        svc.add_zone(vid, "stop_line", [(0, 0)])
    with pytest.raises(ValueError, match="نقاط على الأقل"):
        svc.add_zone(vid, "no_parking", [(0, 0), (1, 1)])  # يحتاج 3


def test_zones_loadable_by_rules_engine(tmp_db: Database) -> None:
    """المناطق المُضافة عبر ZoneService يقرأها محرك القواعد نفسه (تكامل)."""
    vid = _seed_video(tmp_db)
    svc = ZoneService(db=tmp_db)
    svc.add_zone(vid, "no_parking", [(10, 10), (200, 10), (200, 200), (10, 200)])

    loaded = load_zones_from_db(vid, tmp_db)
    assert len(loaded) == 1
    assert loaded[0].zone_type == "no_parking"
    assert len(loaded[0].polygon) == 4


def test_clear_and_delete_zones(tmp_db: Database) -> None:
    vid = _seed_video(tmp_db)
    svc = ZoneService(db=tmp_db)
    z1 = svc.add_zone(vid, "stop_line", [(0, 1), (2, 3)])
    svc.add_zone(vid, "lane_line_solid", [(0, 1), (2, 3)])
    assert len(svc.list_zones(vid)) == 2

    svc.delete_zone(z1)
    assert len(svc.list_zones(vid)) == 1

    svc.clear_zones(vid)
    assert svc.list_zones(vid) == []
