"""يفرض حدود بنية الكود المُعلَنة في `docs/architecture.md`.

سبب وجوده: جدول «معايير الجودة» في README كان يدّعي «لا ملف > 500 سطر ✅»
و«لا دالة > 50 سطر» بينما `rules.py` = 622 سطراً و`_build_ui` = 103 أسطر.
**قاعدة مُعلَنة ومخروقة أسوأ من عدم وجود قاعدة** — إمّا تُفرَض أو تُحذف.

الحدود هنا مختلفة بين الطبقات عن قصد:

* `app/core` و`app/utils` — منطق تطبيقي: حدود صارمة، فطول الدالة هناك مؤشر
  حقيقي على تعدد المسؤوليات.
* `app/ui` و`app/workers` — بناء واجهات **تصريحي** بطبيعته: `_build_ui` تضع
  عشرين ودجة بالتتابع، وتقطيعها لمجرد الرقم يُنتج دوالّ بلا معنى. الحد أعلى
  ويمنع الانفلات لا أكثر.

التشغيل: python scripts/check_structure.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# (بادئة المسار، أقصى أسطر ملف، أقصى أسطر دالة)
LIMITS: tuple[tuple[str, int, int], ...] = (
    ("app/core", 560, 95),
    ("app/utils", 400, 60),
    ("app/ui", 520, 110),
    ("app/workers", 300, 60),
)

# ملفات مستثناة صراحةً مع سبب مكتوب (لا استثناءات صامتة)
EXEMPT: dict[str, str] = {}


def _limits_for(path: Path) -> tuple[int, int] | None:
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    for prefix, max_file, max_func in LIMITS:
        if rel.startswith(prefix):
            return max_file, max_func
    return None


def check() -> list[str]:
    """يُرجع قائمة المخالفات (فارغة = نظيف)."""
    problems: list[str] = []
    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")):
        limits = _limits_for(path)
        if limits is None:
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel in EXEMPT:
            continue
        max_file, max_func = limits

        source = path.read_text(encoding="utf-8")
        line_count = len(source.splitlines())
        if line_count > max_file:
            problems.append(f"{rel}: الملف {line_count} سطراً (الحد {max_file})")

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover - يلتقطه ruff أولاً
            problems.append(f"{rel}: خطأ صياغة — {exc}")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            if length > max_func:
                problems.append(
                    f"{rel}:{node.lineno}: الدالة '{node.name}' {length} سطراً (الحد {max_func})"
                )
    return problems


def main() -> int:
    problems = check()
    if not problems:
        print("✔ بنية الكود ضمن الحدود المُعلَنة")
        return 0
    print("✗ تجاوزات في بنية الكود:", file=sys.stderr)
    for problem in problems:
        print(f"  • {problem}", file=sys.stderr)
    print(
        "\nإمّا قسّم الوحدة، أو عدّل الحد في scripts/check_structure.py "
        "مع تحديث docs/architecture.md.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
