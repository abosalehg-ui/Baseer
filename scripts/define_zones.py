"""سكربت سطر أوامر لتعريف مناطق مقطع (zones) من ملف JSON.

يفكّ حصار الكواشف التي تحتاج مناطق (الإشارة الحمراء، الوقوف الخاطئ، التجاوز)
ريثما تتوفر أداة الرسم في الواجهة.

صيغة ملف JSON:
    [
      {"zone_type": "stop_line", "polygon": [[0, 500], [1920, 500]]},
      {"zone_type": "no_parking", "polygon": [[10, 10], [200, 10], [200, 200], [10, 200]]}
    ]

مثال:
    python scripts/define_zones.py --video-id 3 --zones zones.json
    python scripts/define_zones.py --video-id 3 --list
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.library import LibraryService  # noqa: E402
from app.core.zones import ZoneService  # noqa: E402


def _require_video(video_id: int) -> bool:
    """يتحقق من وجود المقطع قبل الكتابة — بدله يفشل القيد المرجعي برسالة تقنية."""
    if LibraryService().get_video_details(video_id) is None:
        print(f"✗ لا يوجد مقطع بالمعرّف {video_id} في القاعدة", file=sys.stderr)
        return False
    return True


def _load_zone_specs(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("ملف JSON يجب أن يكون قائمة من كائنات {zone_type, polygon}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="تعريف مناطق مقطع (zones) من JSON")
    parser.add_argument("--video-id", type=int, required=True, help="معرّف المقطع في DB")
    parser.add_argument("--zones", type=Path, help="ملف JSON يحتوي قائمة المناطق")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="حذف كل مناطق المقطع الحالية قبل الإضافة",
    )
    parser.add_argument("--list", action="store_true", help="عرض مناطق المقطع الحالية والخروج")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    service = ZoneService()

    if args.list:
        _print_zones(service, args.video_id)
        return 0

    if args.zones is None:
        print("✗ يجب تمرير --zones <ملف JSON> أو --list", file=sys.stderr)
        return 1

    try:
        specs = _load_zone_specs(args.zones)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ تعذّرت قراءة {args.zones}: {exc}", file=sys.stderr)
        return 1

    if not _require_video(args.video_id):
        return 1

    if args.replace:
        service.clear_zones(args.video_id)
        print(f"⤳ حُذفت مناطق المقطع #{args.video_id} السابقة")

    added = 0
    for spec in specs:
        try:
            service.add_zone(
                args.video_id,
                str(spec["zone_type"]),
                [(float(p[0]), float(p[1])) for p in spec["polygon"]],
                metadata=spec.get("metadata"),
            )
            added += 1
        except Exception as exc:  # noqa: BLE001
            print(f"✗ فشل إضافة منطقة {spec!r}: {exc}", file=sys.stderr)
            return 1

    print(f"✔ أُضيفت {added} منطقة للمقطع #{args.video_id}")
    _print_zones(service, args.video_id)
    return 0


def _print_zones(service: ZoneService, video_id: int) -> None:
    zones = service.list_zones(video_id)
    if not zones:
        print(f"لا توجد مناطق للمقطع #{video_id}")
        return
    print(f"\nمناطق المقطع #{video_id}:")
    for z in zones:
        print(f"  #{z.id}  {z.zone_type:>16}  ({len(z.polygon)} نقاط)")


if __name__ == "__main__":
    sys.exit(main())
