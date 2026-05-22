"""سكربت سطر أوامر لتدريب YOLOv8 على dataset بَصير."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.trainer import EpochMetrics, TrainConfig, TrainerService  # noqa: E402


def _print_progress(m: EpochMetrics) -> None:
    map_str = f" mAP50={m.map50:.3f}" if m.map50 is not None else ""
    print(
        f"[{m.epoch:>4}/{m.total}] "
        f"box={m.box_loss:.4f} cls={m.cls_loss:.4f} dfl={m.dfl_loss:.4f}{map_str}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="تدريب YOLOv8 على dataset بَصير")
    parser.add_argument(
        "--base",
        type=Path,
        default=PROJECT_ROOT / "models" / "pretrained" / "yolov8m.pt",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=PROJECT_ROOT / "data" / "dataset" / "dataset.yaml",
    )
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--lr0", type=float, default=0.001)
    parser.add_argument("--name", default="baseer-v1")
    parser.add_argument("--device", default=0)
    parser.add_argument(
        "--project",
        type=Path,
        default=PROJECT_ROOT / "models" / "finetuned",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    config = TrainConfig(
        base_model=args.base,
        dataset_yaml=args.data,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        patience=args.patience,
        lr0=args.lr0,
        project=args.project,
        name=args.name,
        device=args.device,
    )

    service = TrainerService()
    try:
        result = service.train(config, progress_cb=_print_progress)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ فشل التدريب: {exc}", file=sys.stderr)
        return 1

    print(f"\n✔ best.pt: {result.best_pt}")
    print(f"✔ run_dir: {result.run_dir}")
    if result.final_map50 is not None:
        print(f"✔ mAP50: {result.final_map50:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
