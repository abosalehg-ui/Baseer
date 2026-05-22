"""اختبارات دوال الـ hashing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.hash_utils import file_hash, phash_distance


def test_file_hash_is_stable(tmp_path: Path) -> None:
    f = tmp_path / "sample.bin"
    f.write_bytes(b"baseer-test" * 1024)
    h1 = file_hash(f)
    h2 = file_hash(f)
    assert h1 == h2
    assert len(h1) == 64  # SHA256


def test_file_hash_differs_for_different_content(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"AAAA" * 1024)
    b.write_bytes(b"BBBB" * 1024)
    assert file_hash(a) != file_hash(b)


def test_file_hash_raises_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        file_hash(tmp_path / "nope.bin")


def test_phash_distance_zero_for_identical_hashes() -> None:
    h = "ffeeddccbbaa9988"
    assert phash_distance(h, h) == 0


def test_phash_distance_counts_bit_differences() -> None:
    assert phash_distance("0000000000000000", "0000000000000001") == 1
    assert phash_distance("0000000000000000", "000000000000000f") == 4
