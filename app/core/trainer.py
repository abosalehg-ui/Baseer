"""خدمة التدريب — fine-tuning YOLOv8 وتقييم النموذج."""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings

logger = logging.getLogger(__name__)


# ============================================
# الإعدادات والنتائج
# ============================================
@dataclass(frozen=True)
class TrainConfig:
    """إعدادات تشغيل التدريب."""

    base_model: Path
    dataset_yaml: Path
    epochs: int = 100
    batch: int = 16
    imgsz: int = 640
    patience: int = 20
    optimizer: str = "AdamW"
    lr0: float = 0.001
    device: str | int = 0
    project: Path = field(default_factory=lambda: Path("models/finetuned"))
    name: str = "baseer-v1"
    augment: bool = True
    mosaic: float = 1.0
    mixup: float = 0.1


@dataclass(frozen=True)
class TrainResult:
    """نتائج جلسة تدريب واحدة."""

    best_pt: Path
    last_pt: Path
    results_csv: Path
    run_dir: Path
    final_map50: float | None = None
    final_map: float | None = None


@dataclass(frozen=True)
class EvalReport:
    """تقرير تقييم النموذج على val set."""

    map50: float
    map: float
    precision: float
    recall: float
    per_class_map50: dict[str, float]


@dataclass(frozen=True)
class EpochMetrics:
    """مقاييس epoch واحد — تُمرَّر للـ progress callback."""

    epoch: int
    total: int
    box_loss: float
    cls_loss: float
    dfl_loss: float
    map50: float | None = None


# نوع الـ callables القابلة للحقن (للاختبار)
ProgressCallback = Callable[[EpochMetrics], None]
TrainFunction = Callable[[TrainConfig, ProgressCallback | None], TrainResult]
ValFunction = Callable[[Path, Path], EvalReport]


# ============================================
# الخدمة الرئيسية
# ============================================
class TrainerService:
    """خدمة fine-tuning YOLOv8 مع injection للاختبار."""

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        train_fn: TrainFunction | None = None,
        val_fn: ValFunction | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._train_fn = train_fn
        self._val_fn = val_fn

    def train(
        self,
        config: TrainConfig,
        *,
        progress_cb: ProgressCallback | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> TrainResult:
        """يبدأ تدريب YOLOv8 ويُعيد ملخّص النتيجة.

        `should_stop`: دالة تُستطلَع بعد كل epoch؛ عند إرجاعها True نطلب من
        ultralytics إيقاف التدريب مبكراً (يُحفظ آخر checkpoint).
        """
        self._validate_paths(config)
        if self._train_fn is not None:
            # الدالة المحقونة (للاختبار) تبقى بتوقيعها ثنائي الوسائط
            result = self._train_fn(config, progress_cb)
        else:
            result = _default_train(config, progress_cb, should_stop)
        logger.info(
            "اكتمل التدريب — best.pt في %s، mAP50=%s",
            result.best_pt,
            result.final_map50,
        )
        return result

    def evaluate(self, model_path: Path | str, dataset_yaml: Path | str) -> EvalReport:
        """يُقيّم النموذج على val split."""
        model = Path(model_path)
        ds = Path(dataset_yaml)
        if not model.exists():
            raise FileNotFoundError(f"النموذج غير موجود: {model}")
        if not ds.exists():
            raise FileNotFoundError(f"dataset.yaml غير موجود: {ds}")
        val = self._val_fn or _default_evaluate
        report = val(model, ds)
        logger.info("تقييم النموذج — mAP50=%.3f، mAP=%.3f", report.map50, report.map)
        return report

    def export_onnx(self, model_path: Path | str) -> Path:
        """يصدّر النموذج إلى صيغة ONNX."""
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"النموذج غير موجود: {path}")
        try:
            from ultralytics import YOLO
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("يحتاج ultralytics — ثبّت requirements.txt") from exc
        model = YOLO(str(path))
        out = model.export(format="onnx")
        return Path(out)

    def list_runs(self) -> list[Path]:
        """يُرجع المجلدات تحت `models/finetuned/`."""
        runs_dir = self._settings.models_dir / "finetuned"
        if not runs_dir.exists():
            return []
        return sorted([p for p in runs_dir.iterdir() if p.is_dir()])

    # ============================================
    # مساعدات
    # ============================================
    @staticmethod
    def _validate_paths(config: TrainConfig) -> None:
        if not config.base_model.exists():
            raise FileNotFoundError(
                f"النموذج الأساسي غير موجود: {config.base_model} — "
                "شغّل scripts/download_models.py"
            )
        if not config.dataset_yaml.exists():
            raise FileNotFoundError(
                f"dataset.yaml غير موجود: {config.dataset_yaml} — "
                "شغّل scripts/prepare_dataset.py أولاً"
            )


# ============================================
# تحليل results.csv (للرسوم البيانية)
# ============================================
def parse_results_csv(csv_path: Path | str) -> list[dict[str, float]]:
    """يقرأ ملف results.csv من Ultralytics ويُرجع قائمة epoch metrics."""
    path = Path(csv_path)
    if not path.exists():
        return []
    rows: list[dict[str, float]] = []
    with path.open(encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for raw in reader:
            cleaned: dict[str, float] = {}
            for key, value in raw.items():
                key_clean = key.strip()
                try:
                    cleaned[key_clean] = float(value.strip())
                except (ValueError, AttributeError):
                    continue
            if cleaned:
                rows.append(cleaned)
    return rows


def loss_series(rows: list[dict[str, float]]) -> dict[str, list[float]]:
    """يستخرج سلاسل الـ losses عبر الـ epochs لرسمها."""
    keys = ("train/box_loss", "train/cls_loss", "train/dfl_loss")
    series: dict[str, list[float]] = {k: [] for k in keys}
    for row in rows:
        for key in keys:
            if key in row:
                series[key].append(row[key])
    return series


# ============================================
# الـ implementation الفعلي (lazy import)
# ============================================
def _default_train(
    config: TrainConfig,
    progress_cb: ProgressCallback | None,
    should_stop: Callable[[], bool] | None = None,
) -> TrainResult:
    """مغلّف ultralytics.train — يُستدعى عند الاستخدام الحقيقي فقط."""
    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("يحتاج ultralytics — ثبّت requirements.txt") from exc

    model = YOLO(str(config.base_model))

    if progress_cb is not None or should_stop is not None:
        _attach_progress_callback(model, config.epochs, progress_cb, should_stop)

    results = model.train(
        data=str(config.dataset_yaml),
        epochs=config.epochs,
        batch=config.batch,
        imgsz=config.imgsz,
        patience=config.patience,
        optimizer=config.optimizer,
        lr0=config.lr0,
        device=config.device,
        project=str(config.project),
        name=config.name,
        augment=config.augment,
        mosaic=config.mosaic,
        mixup=config.mixup,
        verbose=True,
    )

    run_dir = Path(getattr(results, "save_dir", config.project / config.name))
    return TrainResult(
        best_pt=run_dir / "weights" / "best.pt",
        last_pt=run_dir / "weights" / "last.pt",
        results_csv=run_dir / "results.csv",
        run_dir=run_dir,
        final_map50=_safe_metric(results, "metrics/mAP50(B)"),
        final_map=_safe_metric(results, "metrics/mAP50-95(B)"),
    )


def _attach_progress_callback(
    model: Any,
    total_epochs: int,
    callback: ProgressCallback | None,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """يربط callback يُستدعى بعد كل epoch، ويطلب الإيقاف عند should_stop()."""

    def _on_epoch_end(trainer: Any) -> None:
        if callback is not None:
            metrics = dict(getattr(trainer, "metrics", {}) or {})
            callback(
                EpochMetrics(
                    epoch=int(getattr(trainer, "epoch", 0)) + 1,
                    total=total_epochs,
                    box_loss=float(metrics.get("train/box_loss", 0.0)),
                    cls_loss=float(metrics.get("train/cls_loss", 0.0)),
                    dfl_loss=float(metrics.get("train/dfl_loss", 0.0)),
                    map50=metrics.get("metrics/mAP50(B)"),
                )
            )
        # طلب الإيقاف المبكر من ultralytics (يحفظ آخر checkpoint)
        if should_stop is not None and should_stop():
            trainer.stop = True
            logger.info("طُلب إيقاف التدريب — سيتوقف بعد هذا الـ epoch")

    try:
        model.add_callback("on_train_epoch_end", _on_epoch_end)
    except Exception:  # noqa: BLE001
        logger.warning("تعذّر تسجيل progress callback")


def _default_evaluate(model_path: Path, dataset_yaml: Path) -> EvalReport:
    """تقييم النموذج عبر ultralytics."""
    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("يحتاج ultralytics — ثبّت requirements.txt") from exc

    model = YOLO(str(model_path))
    metrics = model.val(data=str(dataset_yaml), verbose=False)
    box = metrics.box

    per_class: dict[str, float] = {}
    names = getattr(metrics, "names", {}) or {}
    maps_per_class = list(getattr(box, "maps", []) or [])
    for idx, value in enumerate(maps_per_class):
        per_class[str(names.get(idx, idx))] = float(value)

    return EvalReport(
        map50=float(getattr(box, "map50", 0.0)),
        map=float(getattr(box, "map", 0.0)),
        precision=float(getattr(box, "mp", 0.0)),
        recall=float(getattr(box, "mr", 0.0)),
        per_class_map50=per_class,
    )


def _safe_metric(results: Any, key: str) -> float | None:
    """يقرأ مقياساً من ناتج ultralytics بأمان."""
    results_dict = getattr(results, "results_dict", None)
    if not results_dict:
        return None
    value = results_dict.get(key)
    return float(value) if value is not None else None


__all__ = [
    "EpochMetrics",
    "EvalReport",
    "TrainConfig",
    "TrainResult",
    "TrainerService",
    "loss_series",
    "parse_results_csv",
]
