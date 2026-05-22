"""اختبارات خدمة تجهيز الـ dataset."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.dataset import (
    DatasetService,
    DatasetSplit,
    LabeledSample,
    collect_samples,
    compute_class_stats,
    split_samples,
    validate_dataset,
    write_dataset_yaml,
    write_yolo_layout,
)


# ============================================
# Helpers
# ============================================
def _make_sample(dir_path: Path, stem: str, class_ids: list[int]) -> tuple[Path, Path]:
    """ينشئ زوج صورة + label وهمي."""
    img = dir_path / f"{stem}.jpg"
    lbl = dir_path / f"{stem}.txt"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
    lbl.write_text(
        "\n".join(f"{cid} 0.5 0.5 0.1 0.1" for cid in class_ids) + "\n",
        encoding="utf-8",
    )
    return img, lbl


# ============================================
# collect_samples
# ============================================
def test_collect_samples_pairs_images_and_labels(tmp_path: Path) -> None:
    _make_sample(tmp_path, "frame_001", [0])
    _make_sample(tmp_path, "frame_002", [1, 2])

    samples = collect_samples(tmp_path)
    assert len(samples) == 2
    assert all(s.image.exists() and s.label.exists() for s in samples)
    assert [s.stem for s in samples] == ["frame_001", "frame_002"]


def test_collect_samples_skips_unpaired_files(tmp_path: Path) -> None:
    _make_sample(tmp_path, "good", [0])
    # صورة بلا label
    (tmp_path / "lonely.jpg").write_bytes(b"\xff\xd8\xff")
    # label بلا صورة
    (tmp_path / "orphan.txt").write_text("0 0.5 0.5 0.1 0.1\n", encoding="utf-8")

    samples = collect_samples(tmp_path)
    assert len(samples) == 1
    assert samples[0].stem == "good"


def test_collect_samples_descends_into_subdirs(tmp_path: Path) -> None:
    sub = tmp_path / "obj_train_data"
    sub.mkdir()
    _make_sample(sub, "frame_001", [0])
    _make_sample(sub, "frame_002", [1])

    samples = collect_samples(tmp_path)
    assert len(samples) == 2


def test_collect_samples_raises_for_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        collect_samples(tmp_path / "ghost")


# ============================================
# split_samples
# ============================================
def test_split_samples_uses_given_ratios(tmp_path: Path) -> None:
    samples = [LabeledSample(tmp_path / f"{i}.jpg", tmp_path / f"{i}.txt") for i in range(100)]
    split = split_samples(samples, ratios=(0.7, 0.2, 0.1), seed=0)
    assert len(split.train) == 70
    assert len(split.val) == 20
    assert len(split.test) == 10


def test_split_samples_is_deterministic_with_seed(tmp_path: Path) -> None:
    samples = [LabeledSample(tmp_path / f"{i}.jpg", tmp_path / f"{i}.txt") for i in range(50)]
    a = split_samples(samples, seed=42)
    b = split_samples(samples, seed=42)
    assert [s.stem for s in a.train] == [s.stem for s in b.train]
    assert [s.stem for s in a.val] == [s.stem for s in b.val]


def test_split_samples_no_overlap(tmp_path: Path) -> None:
    samples = [LabeledSample(tmp_path / f"{i}.jpg", tmp_path / f"{i}.txt") for i in range(40)]
    split = split_samples(samples, seed=7)
    train = {s.stem for s in split.train}
    val = {s.stem for s in split.val}
    test = {s.stem for s in split.test}
    assert train.isdisjoint(val)
    assert train.isdisjoint(test)
    assert val.isdisjoint(test)
    assert train | val | test == {s.stem for s in samples}


def test_split_samples_rejects_invalid_ratios(tmp_path: Path) -> None:
    samples = [LabeledSample(tmp_path / "x.jpg", tmp_path / "x.txt")]
    with pytest.raises(ValueError, match="مجموعها 1.0"):
        split_samples(samples, ratios=(0.8, 0.1, 0.05))


def test_split_samples_empty_input_returns_empty_split() -> None:
    split = split_samples([])
    assert split.total == 0


# ============================================
# write_yolo_layout
# ============================================
def test_write_yolo_layout_creates_expected_dirs(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    samples = [LabeledSample(*_make_sample(src, f"f_{i:03d}", [0])) for i in range(10)]
    split = split_samples(samples, ratios=(0.6, 0.3, 0.1), seed=1)

    out = tmp_path / "out"
    write_yolo_layout(split, out, copy_files=True)

    for sub in ("train", "val", "test"):
        assert (out / "images" / sub).is_dir()
        assert (out / "labels" / sub).is_dir()

    train_imgs = list((out / "images" / "train").glob("*.jpg"))
    train_lbls = list((out / "labels" / "train").glob("*.txt"))
    assert len(train_imgs) == len(split.train)
    assert len(train_imgs) == len(train_lbls)


def test_write_yolo_layout_refuses_existing_dir_without_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(FileExistsError):
        write_yolo_layout(DatasetSplit(), out, copy_files=True)


def test_write_yolo_layout_overwrites_when_requested(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("old", encoding="utf-8")

    write_yolo_layout(DatasetSplit(), out, copy_files=True, overwrite=True)
    assert not (out / "stale.txt").exists()
    assert (out / "images" / "train").is_dir()


# ============================================
# write_dataset_yaml
# ============================================
def test_write_dataset_yaml_includes_all_keys(tmp_path: Path) -> None:
    yaml_path = write_dataset_yaml(tmp_path, class_names={0: "vehicle", 1: "person"})
    content = yaml_path.read_text(encoding="utf-8")
    assert "train: images/train" in content
    assert "val: images/val" in content
    assert "test: images/test" in content
    assert "nc: 2" in content
    assert "0: vehicle" in content
    assert "1: person" in content


def test_write_dataset_yaml_omits_test_when_requested(tmp_path: Path) -> None:
    yaml_path = write_dataset_yaml(tmp_path, include_test=False)
    content = yaml_path.read_text(encoding="utf-8")
    assert "test:" not in content


# ============================================
# compute_class_stats + validate_dataset
# ============================================
def test_compute_class_stats_counts_instances_and_images(tmp_path: Path) -> None:
    samples = [
        LabeledSample(*_make_sample(tmp_path, "a", [0, 0, 1])),
        LabeledSample(*_make_sample(tmp_path, "b", [0])),
        LabeledSample(*_make_sample(tmp_path, "c", [2])),
    ]
    stats = compute_class_stats(samples, class_names={0: "v", 1: "p", 2: "h"})
    by_id = {s.class_id: s for s in stats}
    assert by_id[0].instances == 3 and by_id[0].images == 2
    assert by_id[1].instances == 1 and by_id[1].images == 1
    assert by_id[2].instances == 1 and by_id[2].images == 1


def test_validate_dataset_flags_low_class_counts(tmp_path: Path) -> None:
    samples = [LabeledSample(*_make_sample(tmp_path, f"s{i}", [0])) for i in range(5)]
    split = split_samples(samples, seed=0)
    stats = compute_class_stats(samples, class_names={0: "v"})
    report = validate_dataset(split, stats, min_per_class=100)
    assert any("class" in issue and "100" in issue for issue in report.issues)


def test_validate_dataset_clean_when_thresholds_met(tmp_path: Path) -> None:
    samples = [LabeledSample(*_make_sample(tmp_path, f"s{i}", [0])) for i in range(120)]
    split = split_samples(samples, seed=0)
    stats = compute_class_stats(samples, class_names={0: "v"})
    report = validate_dataset(split, stats, min_per_class=100)
    assert report.issues == []
    assert report.total_samples == 120


# ============================================
# DatasetService.prepare (end-to-end)
# ============================================
def test_dataset_service_prepare_end_to_end(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    for i in range(20):
        _make_sample(src, f"f_{i:03d}", [i % 3])

    out = tmp_path / "dataset"
    service = DatasetService(class_names={0: "vehicle", 1: "person", 2: "helmet"})
    report = service.prepare(
        src, out, ratios=(0.6, 0.3, 0.1), seed=0, copy_files=True, min_per_class=1
    )

    assert (out / "dataset.yaml").exists()
    assert report.total_samples == 20
    assert report.train_count + report.val_count + report.test_count == 20
    # كل class له على الأقل سامبل
    classes = {s.class_id: s for s in report.per_class}
    assert classes[0].instances > 0
    assert classes[1].instances > 0
    assert classes[2].instances > 0
