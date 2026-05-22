"""اختبارات خدمة التدريب — كلها بـ mocked train/val بدون ultralytics."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.trainer import (
    EpochMetrics,
    EvalReport,
    TrainConfig,
    TrainerService,
    TrainResult,
    loss_series,
    parse_results_csv,
)


@pytest.fixture()
def fake_paths(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "yolov8m.pt"
    base.write_bytes(b"\x80\x02PYTORCH")
    ds = tmp_path / "dataset.yaml"
    ds.write_text("path: ./\ntrain: images/train\nval: images/val\nnc: 1\nnames:\n  0: x\n")
    return base, ds


def _make_train_fn(emit_epochs: int = 3, final_map: float = 0.78):
    def _train(cfg: TrainConfig, progress_cb) -> TrainResult:
        for i in range(1, emit_epochs + 1):
            if progress_cb is not None:
                progress_cb(
                    EpochMetrics(
                        epoch=i,
                        total=cfg.epochs,
                        box_loss=1.0 - 0.1 * i,
                        cls_loss=0.5 - 0.05 * i,
                        dfl_loss=0.8 - 0.05 * i,
                        map50=0.5 + 0.05 * i,
                    )
                )
        run_dir = cfg.project / cfg.name
        weights = run_dir / "weights"
        weights.mkdir(parents=True, exist_ok=True)
        (weights / "best.pt").write_bytes(b"BEST")
        (weights / "last.pt").write_bytes(b"LAST")
        results_csv = run_dir / "results.csv"
        results_csv.write_text(
            "epoch,train/box_loss,train/cls_loss,train/dfl_loss,metrics/mAP50(B)\n"
            "1,0.9,0.45,0.75,0.55\n"
            "2,0.8,0.40,0.70,0.60\n"
            "3,0.7,0.35,0.65,0.65\n"
        )
        return TrainResult(
            best_pt=weights / "best.pt",
            last_pt=weights / "last.pt",
            results_csv=results_csv,
            run_dir=run_dir,
            final_map50=final_map,
            final_map=final_map - 0.1,
        )

    return _train


def _make_val_fn() -> object:
    def _val(model_path: Path, dataset_yaml: Path) -> EvalReport:
        return EvalReport(
            map50=0.75,
            map=0.55,
            precision=0.80,
            recall=0.72,
            per_class_map50={"vehicle": 0.85, "person": 0.65},
        )

    return _val


# ============================================
# train()
# ============================================
def test_train_returns_result_with_best_and_last_pt(
    tmp_path: Path, fake_paths: tuple[Path, Path]
) -> None:
    base, ds = fake_paths
    service = TrainerService(train_fn=_make_train_fn())
    cfg = TrainConfig(
        base_model=base,
        dataset_yaml=ds,
        epochs=10,
        project=tmp_path / "runs",
        name="t1",
    )
    result = service.train(cfg)
    assert result.best_pt.exists()
    assert result.last_pt.exists()
    assert result.results_csv.exists()
    assert result.final_map50 == 0.78


def test_train_emits_progress_callback(tmp_path: Path, fake_paths: tuple[Path, Path]) -> None:
    base, ds = fake_paths
    seen: list[EpochMetrics] = []

    service = TrainerService(train_fn=_make_train_fn(emit_epochs=5))
    cfg = TrainConfig(
        base_model=base,
        dataset_yaml=ds,
        epochs=5,
        project=tmp_path / "runs",
        name="t2",
    )
    service.train(cfg, progress_cb=seen.append)

    assert len(seen) == 5
    assert [m.epoch for m in seen] == [1, 2, 3, 4, 5]
    assert all(m.total == 5 for m in seen)
    # loss decreases monotonically in our fake
    assert seen[0].box_loss > seen[-1].box_loss


def test_train_raises_when_base_model_missing(
    tmp_path: Path, fake_paths: tuple[Path, Path]
) -> None:
    _, ds = fake_paths
    service = TrainerService(train_fn=_make_train_fn())
    cfg = TrainConfig(
        base_model=tmp_path / "ghost.pt",
        dataset_yaml=ds,
        epochs=1,
    )
    with pytest.raises(FileNotFoundError, match="النموذج الأساسي غير موجود"):
        service.train(cfg)


def test_train_raises_when_dataset_yaml_missing(
    tmp_path: Path, fake_paths: tuple[Path, Path]
) -> None:
    base, _ = fake_paths
    service = TrainerService(train_fn=_make_train_fn())
    cfg = TrainConfig(
        base_model=base,
        dataset_yaml=tmp_path / "ghost.yaml",
        epochs=1,
    )
    with pytest.raises(FileNotFoundError, match="dataset.yaml غير موجود"):
        service.train(cfg)


# ============================================
# evaluate()
# ============================================
def test_evaluate_returns_per_class_metrics(tmp_path: Path) -> None:
    model = tmp_path / "best.pt"
    model.write_bytes(b"x")
    ds = tmp_path / "dataset.yaml"
    ds.write_text("nc: 2\n")
    service = TrainerService(val_fn=_make_val_fn())
    report = service.evaluate(model, ds)
    assert report.map50 == 0.75
    assert "vehicle" in report.per_class_map50
    assert report.per_class_map50["vehicle"] == 0.85


def test_evaluate_raises_when_model_missing(tmp_path: Path) -> None:
    ds = tmp_path / "dataset.yaml"
    ds.write_text("nc: 1\n")
    service = TrainerService(val_fn=_make_val_fn())
    with pytest.raises(FileNotFoundError, match="النموذج"):
        service.evaluate(tmp_path / "ghost.pt", ds)


def test_evaluate_raises_when_dataset_missing(tmp_path: Path) -> None:
    model = tmp_path / "m.pt"
    model.write_bytes(b"x")
    service = TrainerService(val_fn=_make_val_fn())
    with pytest.raises(FileNotFoundError, match="dataset.yaml"):
        service.evaluate(model, tmp_path / "ghost.yaml")


# ============================================
# list_runs()
# ============================================
def test_list_runs_returns_empty_when_no_dir(tmp_path: Path) -> None:
    from app.config import AppSettings

    s = AppSettings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        db_path=tmp_path / "data" / "results.duckdb",
        log_file=tmp_path / "logs" / "baseer.log",
    )
    service = TrainerService(settings=s)
    assert service.list_runs() == []


def test_list_runs_returns_finetuned_subdirs(tmp_path: Path) -> None:
    from app.config import AppSettings

    s = AppSettings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        db_path=tmp_path / "data" / "results.duckdb",
        log_file=tmp_path / "logs" / "baseer.log",
    )
    runs = s.models_dir / "finetuned"
    (runs / "v1").mkdir(parents=True)
    (runs / "v2").mkdir(parents=True)
    (runs / "v3.txt").write_text("ignore me")

    service = TrainerService(settings=s)
    result = service.list_runs()
    names = {p.name for p in result}
    assert names == {"v1", "v2"}


# ============================================
# parse_results_csv + loss_series
# ============================================
def test_parse_results_csv_reads_numeric_fields(tmp_path: Path) -> None:
    csv = tmp_path / "results.csv"
    csv.write_text("epoch,train/box_loss,train/cls_loss\n" "1,0.5,0.3\n" "2,0.4,0.25\n")
    rows = parse_results_csv(csv)
    assert len(rows) == 2
    assert rows[0]["train/box_loss"] == 0.5
    assert rows[1]["train/cls_loss"] == 0.25


def test_parse_results_csv_returns_empty_when_missing(tmp_path: Path) -> None:
    assert parse_results_csv(tmp_path / "ghost.csv") == []


def test_loss_series_extracts_columns() -> None:
    rows = [
        {"train/box_loss": 0.9, "train/cls_loss": 0.5, "train/dfl_loss": 0.7},
        {"train/box_loss": 0.7, "train/cls_loss": 0.4, "train/dfl_loss": 0.6},
    ]
    series = loss_series(rows)
    assert series["train/box_loss"] == [0.9, 0.7]
    assert series["train/cls_loss"] == [0.5, 0.4]
    assert series["train/dfl_loss"] == [0.7, 0.6]
