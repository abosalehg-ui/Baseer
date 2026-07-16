"""عامل خلفي للتدريب الطويل."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from app.core.trainer import EpochMetrics, TrainConfig, TrainerService, TrainResult

logger = logging.getLogger(__name__)


class TrainingWorker(QObject):
    """يُشغّل التدريب في thread منفصل."""

    epoch_done = pyqtSignal(object)  # EpochMetrics
    finished = pyqtSignal(object)  # TrainResult
    failed = pyqtSignal(str)

    def __init__(self, config: TrainConfig, *, service: TrainerService | None = None) -> None:
        super().__init__()
        self._config = config
        self._service = service
        self._cancelled = False

    def cancel(self) -> None:
        """يطلب إيقاف التدريب بعد الـ epoch الحالي."""
        self._cancelled = True

    def run(self) -> None:
        try:
            service = self._service or TrainerService()
            result = service.train(
                self._config,
                progress_cb=self._on_epoch,
                should_stop=lambda: self._cancelled,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل عامل التدريب")
            self.failed.emit(str(exc))

    def _on_epoch(self, metrics: EpochMetrics) -> None:
        self.epoch_done.emit(metrics)


def start_training_in_thread(
    config: TrainConfig,
    *,
    on_epoch: object = None,
    on_finished: object = None,
    on_failed: object = None,
) -> tuple[QThread, TrainingWorker]:
    """يبدأ التدريب في QThread جديد ويعيد (thread, worker)."""
    thread = QThread()
    worker = TrainingWorker(config)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    if on_epoch is not None:
        worker.epoch_done.connect(on_epoch)
    if on_finished is not None:
        worker.finished.connect(on_finished)
    if on_failed is not None:
        worker.failed.connect(on_failed)

    thread.start()
    return thread, worker


__all__ = ["TrainingWorker", "TrainResult", "start_training_in_thread"]
