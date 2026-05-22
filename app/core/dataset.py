"""خدمة تجهيز الـ dataset — قراءة CVAT export وتقسيم train/val/test وتوليد dataset.yaml."""

from __future__ import annotations

import logging
import random
import shutil
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.constants import DETECTION_CLASSES, SUPPORTED_VIDEO_EXTENSIONS

logger = logging.getLogger(__name__)


IMAGE_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
LABEL_EXTENSION: str = ".txt"


@dataclass(frozen=True)
class LabeledSample:
    """عينة واحدة من الـ dataset (صورة + ملف تصنيف)."""

    image: Path
    label: Path

    @property
    def stem(self) -> str:
        return self.image.stem


@dataclass
class DatasetSplit:
    """نتيجة تقسيم الـ dataset."""

    train: list[LabeledSample] = field(default_factory=list)
    val: list[LabeledSample] = field(default_factory=list)
    test: list[LabeledSample] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.train) + len(self.val) + len(self.test)


@dataclass
class ClassStats:
    """إحصاءات class واحد."""

    class_id: int
    class_name: str
    instances: int
    images: int


@dataclass
class DatasetReport:
    """تقرير شامل عن الـ dataset."""

    total_samples: int
    train_count: int
    val_count: int
    test_count: int
    per_class: list[ClassStats]
    issues: list[str] = field(default_factory=list)


# ============================================
# قراءة export من CVAT (YOLO 1.1)
# ============================================
def collect_samples(source_dir: Path | str) -> list[LabeledSample]:
    """يجمع العينات (صورة + label) من مجلد export.

    يتجاهل أي صورة بدون ملف .txt مطابق.
    """
    src = Path(source_dir)
    if not src.is_dir():
        raise NotADirectoryError(f"مجلد المصدر غير موجود: {src}")

    by_stem: dict[str, dict[str, Path]] = {}
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            by_stem.setdefault(path.stem, {})["image"] = path
        elif suffix == LABEL_EXTENSION:
            by_stem.setdefault(path.stem, {})["label"] = path

    samples: list[LabeledSample] = []
    for stem, files in by_stem.items():
        if "image" in files and "label" in files:
            samples.append(LabeledSample(image=files["image"], label=files["label"]))
        else:
            missing = "image" if "image" not in files else "label"
            logger.debug("تخطي %s — ينقصه %s", stem, missing)

    samples.sort(key=lambda s: s.stem)
    return samples


# ============================================
# التقسيم
# ============================================
def split_samples(
    samples: list[LabeledSample],
    ratios: tuple[float, float, float] = (0.7, 0.2, 0.1),
    *,
    seed: int = 42,
) -> DatasetSplit:
    """يقسم العينات إلى train/val/test بنسب محددة وبشكل حتمي."""
    if not samples:
        return DatasetSplit()
    if not abs(sum(ratios) - 1.0) < 1e-6:
        raise ValueError(f"النسب يجب أن يكون مجموعها 1.0، الحالي: {sum(ratios)}")

    shuffled = list(samples)
    rng = random.Random(seed)
    rng.shuffle(shuffled)

    total = len(shuffled)
    train_n = int(total * ratios[0])
    val_n = int(total * ratios[1])
    # نضمن أن كل العينات تذهب لمكان (تجنب الفقدان بسبب التقريب)
    train = shuffled[:train_n]
    val = shuffled[train_n : train_n + val_n]
    test = shuffled[train_n + val_n :]
    return DatasetSplit(train=train, val=val, test=test)


# ============================================
# كتابة بنية YOLOv8
# ============================================
def write_yolo_layout(
    split: DatasetSplit,
    output_dir: Path | str,
    *,
    copy_files: bool = False,
    overwrite: bool = False,
) -> Path:
    """ينشئ بنية مجلدات YOLOv8 ويضع الصور والـ labels فيها.

    Args:
        split: نتيجة `split_samples()`.
        output_dir: المجلد الهدف.
        copy_files: True لنسخ، False لإنشاء symlinks (أوفر للمساحة).
        overwrite: True لحذف المجلد الهدف لو موجود.
    """
    out = Path(output_dir)
    if out.exists():
        if not overwrite:
            raise FileExistsError(f"مجلد الإخراج موجود: {out} — استخدم overwrite=True")
        shutil.rmtree(out)

    for split_name, items in (("train", split.train), ("val", split.val), ("test", split.test)):
        img_dir = out / "images" / split_name
        lbl_dir = out / "labels" / split_name
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        for sample in items:
            _materialize(sample.image, img_dir / sample.image.name, copy=copy_files)
            _materialize(sample.label, lbl_dir / sample.label.name, copy=copy_files)

    logger.info("كُتبت بنية YOLOv8 في %s (نسخ=%s)", out, copy_files)
    return out


def _materialize(src: Path, dst: Path, *, copy: bool) -> None:
    """ينسخ أو يصنع symlink من src إلى dst."""
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if copy:
        shutil.copy2(src, dst)
    else:
        try:
            dst.symlink_to(src.resolve())
        except (OSError, NotImplementedError):
            shutil.copy2(src, dst)


# ============================================
# توليد dataset.yaml
# ============================================
def write_dataset_yaml(
    output_dir: Path | str,
    *,
    class_names: dict[int, str] | None = None,
    include_test: bool = True,
) -> Path:
    """يكتب dataset.yaml بصيغة Ultralytics YOLOv8."""
    out = Path(output_dir)
    names = class_names or DETECTION_CLASSES
    yaml_path = out / "dataset.yaml"

    lines = [
        f"path: {out.resolve()}",
        "train: images/train",
        "val: images/val",
    ]
    if include_test:
        lines.append("test: images/test")
    lines.append("")
    lines.append(f"nc: {len(names)}")
    lines.append("names:")
    for cls_id in sorted(names.keys()):
        lines.append(f"  {cls_id}: {names[cls_id]}")

    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml_path


# ============================================
# الإحصاءات والتحقق
# ============================================
def compute_class_stats(
    samples: Iterable[LabeledSample],
    class_names: dict[int, str] | None = None,
) -> list[ClassStats]:
    """يحسب عدد instances وعدد الصور لكل class."""
    names = class_names or DETECTION_CLASSES
    instances = Counter[int]()
    images = Counter[int]()

    for sample in samples:
        seen_in_image: set[int] = set()
        for cls_id in _read_class_ids(sample.label):
            instances[cls_id] += 1
            seen_in_image.add(cls_id)
        for cls_id in seen_in_image:
            images[cls_id] += 1

    return [
        ClassStats(
            class_id=cls_id,
            class_name=names.get(cls_id, str(cls_id)),
            instances=instances.get(cls_id, 0),
            images=images.get(cls_id, 0),
        )
        for cls_id in sorted(names.keys())
    ]


def _read_class_ids(label_path: Path) -> list[int]:
    """يقرأ معرفات الـ classes من ملف YOLO label."""
    try:
        lines = label_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    ids: list[int] = []
    for line in lines:
        parts = line.strip().split()
        if not parts:
            continue
        try:
            ids.append(int(parts[0]))
        except ValueError:
            continue
    return ids


def validate_dataset(
    split: DatasetSplit,
    stats: list[ClassStats],
    *,
    min_per_class: int = 100,
    min_val_ratio: float = 0.05,
) -> DatasetReport:
    """يجمع تقريراً شاملاً مع تشخيص المشاكل."""
    issues: list[str] = []

    for cs in stats:
        if cs.instances < min_per_class:
            issues.append(
                f"الـ class '{cs.class_name}' لديه {cs.instances} instance فقط "
                f"(الحد الأدنى {min_per_class})"
            )

    if split.total > 0:
        val_ratio = len(split.val) / split.total
        if val_ratio < min_val_ratio:
            issues.append(f"نسبة val ({val_ratio:.1%}) أقل من الحد الأدنى ({min_val_ratio:.1%})")

    if not split.train:
        issues.append("لا توجد عينات في train")
    if not split.val:
        issues.append("لا توجد عينات في val")

    return DatasetReport(
        total_samples=split.total,
        train_count=len(split.train),
        val_count=len(split.val),
        test_count=len(split.test),
        per_class=stats,
        issues=issues,
    )


# ============================================
# واجهة الخدمة الشاملة
# ============================================
class DatasetService:
    """خدمة تجهيز الـ dataset من CVAT export إلى YOLOv8."""

    def __init__(self, *, class_names: dict[int, str] | None = None) -> None:
        self._class_names = class_names or DETECTION_CLASSES

    def prepare(
        self,
        source_dir: Path | str,
        output_dir: Path | str,
        *,
        ratios: tuple[float, float, float] = (0.7, 0.2, 0.1),
        seed: int = 42,
        copy_files: bool = False,
        overwrite: bool = True,
        min_per_class: int = 100,
    ) -> DatasetReport:
        """ينفّذ المسار الكامل: جمع → تقسيم → كتابة → yaml → تقرير."""
        samples = collect_samples(source_dir)
        if not samples:
            raise ValueError(f"لم تُعثر على أي عينات في {source_dir}")

        split = split_samples(samples, ratios, seed=seed)
        write_yolo_layout(split, output_dir, copy_files=copy_files, overwrite=overwrite)
        write_dataset_yaml(output_dir, class_names=self._class_names, include_test=bool(split.test))

        stats = compute_class_stats(samples, self._class_names)
        return validate_dataset(split, stats, min_per_class=min_per_class)


__all__ = [
    "ClassStats",
    "DatasetReport",
    "DatasetService",
    "DatasetSplit",
    "LabeledSample",
    "collect_samples",
    "compute_class_stats",
    "split_samples",
    "validate_dataset",
    "write_dataset_yaml",
    "write_yolo_layout",
]


# يُستخدم لاحقاً في trainer للتحقق من أن الفيديوهات الأصلية ما زالت موجودة
def known_video_extensions() -> tuple[str, ...]:
    return SUPPORTED_VIDEO_EXTENSIONS
