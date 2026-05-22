"""خدمة التصنيف — تصدير pseudo-labels لـ CVAT وجسر REST API."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from app.config import AppSettings, get_cvat_settings, get_settings
from app.constants import DETECTION_CLASSES, VideoStatus
from app.core.analyzer import Detection, detections_grouped_by_frame
from app.core.db import Database, get_database

logger = logging.getLogger(__name__)


# ============================================
# تصدير CVAT XML 1.1 (image format)
# ============================================
def build_cvat_xml(
    *,
    task_name: str,
    image_size: tuple[int, int],
    detections_per_frame: dict[int, list[Detection]],
    label_names: Iterable[str] | None = None,
) -> ET.ElementTree:
    """يبني شجرة XML بصيغة CVAT 1.1 (image annotations).

    Args:
        task_name: اسم المهمة في CVAT.
        image_size: (width, height) للإطار.
        detections_per_frame: قاموس {frame_no: [Detection, ...]}.
        label_names: قائمة أسماء الـ classes (افتراضياً DETECTION_CLASSES).
    """
    width, height = image_size
    labels = list(label_names) if label_names else list(DETECTION_CLASSES.values())

    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"

    meta = ET.SubElement(root, "meta")
    task = ET.SubElement(meta, "task")
    ET.SubElement(task, "name").text = task_name
    ET.SubElement(task, "size").text = str(len(detections_per_frame))
    ET.SubElement(task, "mode").text = "annotation"
    ET.SubElement(task, "created").text = datetime.now(UTC).isoformat()

    labels_el = ET.SubElement(task, "labels")
    for name in labels:
        label_el = ET.SubElement(labels_el, "label")
        ET.SubElement(label_el, "name").text = name
        ET.SubElement(label_el, "attributes")

    for image_id, (frame_no, dets) in enumerate(sorted(detections_per_frame.items())):
        image_el = ET.SubElement(
            root,
            "image",
            id=str(image_id),
            name=f"frame_{frame_no:06d}.jpg",
            width=str(width),
            height=str(height),
        )
        for det in dets:
            ET.SubElement(
                image_el,
                "box",
                label=det.class_name,
                occluded="0",
                source="auto",
                xtl=f"{det.bbox[0]:.2f}",
                ytl=f"{det.bbox[1]:.2f}",
                xbr=f"{det.bbox[2]:.2f}",
                ybr=f"{det.bbox[3]:.2f}",
                z_order="0",
            )

    return ET.ElementTree(root)


# ============================================
# الخدمة الرئيسية
# ============================================
class AnnotatorService:
    """خدمة تصدير وتصنيف عبر CVAT."""

    def __init__(
        self,
        *,
        db: Database | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._db = db or get_database(self._settings)
        self._cvat = get_cvat_settings()

    # ============================================
    # تصدير
    # ============================================
    def export_video_pseudo_labels(self, video_id: int, output_dir: Path | None = None) -> Path:
        """يُصدّر pseudo-labels لمقطع بصيغة CVAT XML."""
        out_dir = output_dir or (self._settings.data_dir / "annotations" / "raw")
        out_dir.mkdir(parents=True, exist_ok=True)

        row = self._db.fetch_one(
            "SELECT filename, width, height FROM videos WHERE id = ?", (video_id,)
        )
        if row is None:
            raise ValueError(f"لا يوجد مقطع بالمعرّف {video_id}")
        filename, width, height = row
        if width is None or height is None:
            raise ValueError("أبعاد المقطع غير معروفة — أعد استيراد المقطع.")

        det_rows = self._db.fetch_all(
            "SELECT frame_no, timestamp_ms, class_name, confidence, "
            "bbox_x1, bbox_y1, bbox_x2, bbox_y2, track_id "
            "FROM detections WHERE video_id = ? ORDER BY frame_no, id",
            (video_id,),
        )
        detections = [
            Detection(
                frame_no=int(r[0]),
                timestamp_ms=int(r[1]),
                class_name=str(r[2]),
                confidence=float(r[3]),
                bbox=(float(r[4]), float(r[5]), float(r[6]), float(r[7])),
                track_id=int(r[8]) if r[8] is not None else None,
            )
            for r in det_rows
        ]
        groups = detections_grouped_by_frame(detections)

        tree = build_cvat_xml(
            task_name=f"baseer_video_{video_id}",
            image_size=(int(width), int(height)),
            detections_per_frame=groups,
        )
        out_path = out_dir / f"video_{video_id}_{Path(str(filename)).stem}.xml"
        tree.write(out_path, encoding="utf-8", xml_declaration=True)
        logger.info("صُدِّرت pseudo-labels للمقطع %d → %s", video_id, out_path)
        return out_path

    def export_batch_pseudo_labels(
        self, video_ids: list[int], output_dir: Path | None = None
    ) -> list[Path]:
        """يُصدّر pseudo-labels لمجموعة مقاطع."""
        return [self.export_video_pseudo_labels(vid, output_dir) for vid in video_ids]

    # ============================================
    # تحديث حالة المراجعة
    # ============================================
    def mark_reviewed(self, video_ids: list[int]) -> None:
        """يحدّث حالة المقاطع إلى reviewed بعد إكمال المراجعة في CVAT."""
        for vid in video_ids:
            self._db.execute(
                "UPDATE videos SET status = ? WHERE id = ?",
                (VideoStatus.REVIEWED.value, vid),
            )

    def list_prelabeled_video_ids(self) -> list[int]:
        """يعيد المقاطع التي تم pseudo-labeling لها وتحتاج مراجعة."""
        rows = self._db.fetch_all(
            "SELECT id FROM videos WHERE status = ? ORDER BY id",
            (VideoStatus.PRELABELED.value,),
        )
        return [int(r[0]) for r in rows]

    # ============================================
    # روابط CVAT
    # ============================================
    @property
    def cvat_url(self) -> str:
        return self._cvat.cvat_url

    def cvat_task_url(self, task_id: int) -> str:
        return f"{self._cvat.cvat_url.rstrip('/')}/tasks/{task_id}"


__all__ = ["AnnotatorService", "build_cvat_xml"]
