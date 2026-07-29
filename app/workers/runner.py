"""مشغّل موحّد للعمّال في QThread.

نمط «أنشئ thread، انقل الـworker إليه، اربط ستّ إشارات» كان مكرّراً حرفياً في
`library_view` و`annotator_view` و`trainer_view`. الأخطاء الشائعة فيه (نسيان
`deleteLater`، أو عدم الاحتفاظ بمرجع فيجمعه الـGC أثناء العمل) تظهر كانهيارات
عشوائية يصعب تتبّعها — فتوحيده في مكان واحد ليس تجميلاً.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QThread

logger = logging.getLogger(__name__)


class ThreadHandle:
    """مقبض على (thread, worker) — يحتفظ بالمرجعين ويوفّر إلغاءً آمناً."""

    def __init__(self, thread: QThread, worker: QObject) -> None:
        self.thread = thread
        self.worker = worker

    def is_running(self) -> bool:
        try:
            return bool(self.thread.isRunning())
        except RuntimeError:
            # الـthread حُذف من Qt بعد الانتهاء
            return False

    def cancel(self) -> bool:
        """يطلب الإلغاء من الـworker إن كان يدعمه. يُرجع True لو طُلب فعلاً."""
        cancel_fn = getattr(self.worker, "cancel", None)
        if callable(cancel_fn):
            try:
                cancel_fn()
                return True
            except RuntimeError:
                return False
        return False

    def wait(self, msecs: int = 5000) -> bool:
        try:
            return bool(self.thread.wait(msecs))
        except RuntimeError:
            return True


def run_worker(
    worker: QObject,
    *,
    parent: QObject | None = None,
    on_finished: Callable[[Any], None] | None = None,
    on_failed: Callable[[str], None] | None = None,
    signal_bindings: dict[str, Callable[..., None]] | None = None,
    start: bool = True,
) -> ThreadHandle:
    """يُشغّل `worker` في QThread جديد ويعيد مقبضاً يجب الاحتفاظ به.

    Args:
        worker: كائن له `run()` وإشارتا `finished(object)` و`failed(str)`.
        parent: أب الـthread (عادةً الـview) لضمان عمر صحيح.
        on_finished / on_failed: وصلات الإنهاء.
        signal_bindings: إشارات إضافية بالاسم، مثل `{"progress": self._on_progress}`.
        start: False لتأجيل البدء (للاختبارات).
    """
    thread = QThread(parent)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    finished = worker.finished
    failed = worker.failed

    if on_finished is not None:
        finished.connect(on_finished)
    if on_failed is not None:
        failed.connect(on_failed)
    for name, slot in (signal_bindings or {}).items():
        signal = getattr(worker, name, None)
        if signal is None:
            logger.warning("العامل %s بلا إشارة %s", worker.__class__.__name__, name)
            continue
        signal.connect(slot)

    # ترتيب التنظيف: أنهِ الـthread ثم احذف الـworker ثم الـthread
    finished.connect(thread.quit)
    failed.connect(thread.quit)
    finished.connect(worker.deleteLater)
    failed.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    handle = ThreadHandle(thread, worker)
    if start:
        thread.start()
    return handle


__all__ = ["ThreadHandle", "run_worker"]
