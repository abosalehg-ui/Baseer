"""اختبارات خدمة التصنيف وتصدير CVAT XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.constants import VideoStatus
from app.core.analyzer import Detection
from app.core.annotator import AnnotatorService, build_cvat_xml
from app.core.db import Database


def test_build_cvat_xml_has_correct_structure() -> None:
    detections = {
        0: [
            Detection(0, 0, "vehicle", 0.9, (10, 20, 100, 200)),
            Detection(0, 0, "person", 0.7, (110, 50, 150, 200)),
        ],
        15: [Detection(15, 500, "vehicle", 0.85, (5, 5, 50, 50))],
    }
    tree = build_cvat_xml(
        task_name="test_task",
        image_size=(1920, 1080),
        detections_per_frame=detections,
    )
    root = tree.getroot()
    assert root.tag == "annotations"
    assert root.find("version").text == "1.1"

    images = root.findall("image")
    assert len(images) == 2

    first_image = images[0]
    assert first_image.attrib["width"] == "1920"
    assert first_image.attrib["height"] == "1080"
    boxes = first_image.findall("box")
    assert len(boxes) == 2
    assert boxes[0].attrib["label"] == "vehicle"
    assert boxes[0].attrib["xtl"] == "10.00"


def test_build_cvat_xml_includes_labels_section() -> None:
    tree = build_cvat_xml(
        task_name="t",
        image_size=(640, 480),
        detections_per_frame={},
        label_names=["vehicle", "person", "helmet"],
    )
    root = tree.getroot()
    labels = root.findall(".//label/name")
    assert {lbl.text for lbl in labels} == {"vehicle", "person", "helmet"}


def test_build_cvat_xml_sorts_frames(tmp_path: Path) -> None:
    detections = {
        20: [Detection(20, 666, "vehicle", 0.5, (0, 0, 10, 10))],
        5: [Detection(5, 166, "vehicle", 0.5, (0, 0, 10, 10))],
        10: [Detection(10, 333, "vehicle", 0.5, (0, 0, 10, 10))],
    }
    tree = build_cvat_xml(task_name="t", image_size=(100, 100), detections_per_frame=detections)
    images = tree.getroot().findall("image")
    names = [img.attrib["name"] for img in images]
    assert names == ["frame_000005.jpg", "frame_000010.jpg", "frame_000020.jpg"]


@pytest.fixture()
def video_with_detections(tmp_db: Database, tmp_path: Path) -> int:
    video = tmp_path / "test.mp4"
    video.write_bytes(b"x")
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, width, height, status) " "VALUES (?, ?, ?, ?, ?)",
        (str(video), "test.mp4", 1280, 720, VideoStatus.PRELABELED.value),
    )
    row = tmp_db.fetch_one("SELECT id FROM videos WHERE filepath = ?", (str(video),))
    assert row is not None
    vid = int(row[0])

    tmp_db.executemany(
        "INSERT INTO detections "
        "(video_id, frame_no, timestamp_ms, class_name, confidence, "
        " bbox_x1, bbox_y1, bbox_x2, bbox_y2, track_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (vid, 0, 0, "vehicle", 0.9, 10, 20, 100, 200, None),
            (vid, 5, 166, "person", 0.7, 50, 60, 120, 300, None),
        ],
    )
    return vid


def test_export_video_pseudo_labels_writes_xml(
    tmp_db: Database, video_with_detections: int, tmp_path: Path
) -> None:
    out_dir = tmp_path / "raw"
    service = AnnotatorService(db=tmp_db)
    output = service.export_video_pseudo_labels(video_with_detections, output_dir=out_dir)

    assert output.exists()
    assert output.parent == out_dir
    tree = ET.parse(output)
    images = tree.getroot().findall("image")
    assert len(images) == 2


def test_export_video_pseudo_labels_raises_for_unknown_video(
    tmp_db: Database, tmp_path: Path
) -> None:
    service = AnnotatorService(db=tmp_db)
    with pytest.raises(ValueError, match="لا يوجد مقطع"):
        service.export_video_pseudo_labels(99999, output_dir=tmp_path)


def test_export_video_pseudo_labels_raises_when_dimensions_missing(
    tmp_db: Database, tmp_path: Path
) -> None:
    video = tmp_path / "nodim.mp4"
    video.write_bytes(b"x")
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename) VALUES (?, ?)",
        (str(video), "nodim.mp4"),
    )
    row = tmp_db.fetch_one("SELECT id FROM videos WHERE filepath = ?", (str(video),))
    assert row is not None
    service = AnnotatorService(db=tmp_db)
    with pytest.raises(ValueError, match="أبعاد"):
        service.export_video_pseudo_labels(int(row[0]), output_dir=tmp_path)


def test_mark_reviewed_updates_status(tmp_db: Database, tmp_path: Path) -> None:
    video = tmp_path / "rev.mp4"
    video.write_bytes(b"x")
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, status) VALUES (?, ?, ?)",
        (str(video), "rev.mp4", VideoStatus.PRELABELED.value),
    )
    row = tmp_db.fetch_one("SELECT id FROM videos WHERE filepath = ?", (str(video),))
    assert row is not None
    vid = int(row[0])

    service = AnnotatorService(db=tmp_db)
    service.mark_reviewed([vid])

    status = tmp_db.fetch_one("SELECT status FROM videos WHERE id = ?", (vid,))
    assert status is not None
    assert status[0] == VideoStatus.REVIEWED.value


def test_list_prelabeled_returns_only_prelabeled(tmp_db: Database, tmp_path: Path) -> None:
    for i, status in enumerate(
        [
            VideoStatus.IMPORTED.value,
            VideoStatus.PRELABELED.value,
            VideoStatus.PRELABELED.value,
            VideoStatus.REVIEWED.value,
        ]
    ):
        f = tmp_path / f"v{i}.mp4"
        f.write_bytes(b"x")
        tmp_db.execute(
            "INSERT INTO videos (filepath, filename, status) VALUES (?, ?, ?)",
            (str(f), f.name, status),
        )
    ids = AnnotatorService(db=tmp_db).list_prelabeled_video_ids()
    assert len(ids) == 2


def test_cvat_task_url_format(tmp_db: Database) -> None:
    service = AnnotatorService(db=tmp_db)
    url = service.cvat_task_url(42)
    assert url.endswith("/tasks/42")
