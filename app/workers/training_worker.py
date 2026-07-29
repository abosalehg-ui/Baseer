"""عامل خلفي للتدريب الطويل."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal

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


__all__ = ["TrainingWorker", "TrainResult"]
