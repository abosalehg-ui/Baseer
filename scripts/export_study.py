"""تصدير دراسة بَصير من السطر — JSON / CSV / Excel / PDF عربي."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.dashboard import DashboardService  # noqa: E402
from app.core.exporter import (  # noqa: E402
    build_study,
    export_csv,
    export_excel,
    export_json,
    export_pdf,
    record_export,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="تصدير دراسة من قاعدة بَصير")
    parser.add_argument(
        "--format",
        choices=("json", "csv", "xlsx", "pdf", "all"),
        default="all",
        help="صيغة التصدير (افتراضي: all)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "exports",
        help="مجلد الإخراج",
    )
    parser.add_argument("--name", default="baseer_study", help="اسم الدراسة")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    args.output.mkdir(parents=True, exist_ok=True)

    service = DashboardService()
    study = build_study(service)
    violations = service.list_violations()
    print(f"📊 {len(violations)} مخالفة في القاعدة")

    formats = ("json", "csv", "xlsx", "pdf") if args.format == "all" else (args.format,)
    out_paths: list[Path] = []

    for fmt in formats:
        out = args.output / f"{args.name}.{fmt}"
        try:
            if fmt == "json":
                export_json(study, out)
            elif fmt == "csv":
                export_csv(violations, out)
            elif fmt == "xlsx":
                export_excel(study, violations, out)
            elif fmt == "pdf":
                export_pdf(study, violations, out)
            print(f"✔ {fmt}: {out}")
            out_paths.append(out)
            record_export(
                service._db,  # noqa: SLF001
                study_name=args.name,
                fmt=fmt,
                output_path=out,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {fmt} فشل: {exc}", file=sys.stderr)

    return 0 if out_paths else 1


if __name__ == "__main__":
    sys.exit(main())
