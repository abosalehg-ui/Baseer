"""عامل خلفي لتشغيل الاستدلال على مجموعة مقاطع."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal

from app.core.analyzer import AnalysisConfig, AnalysisResult, AnalyzerService

logger = logging.getLogger(__name__)


class InferenceWorker(QObject):
    """يُجري الاستدلال على دفعة مقاطع في thread منفصل."""

    progress = pyqtSignal(int, int, int)  # current, total, video_id
    finished = pyqtSignal(object)  # list[AnalysisResult]
    failed = pyqtSignal(str)

    def __init__(
        self,
        video_ids: list[int],
        config: AnalysisConfig,
        *,
        service: AnalyzerService | None = None,
    ) -> None:
        super().__init__()
        self._video_ids = video_ids
        self._config = config
        self._service = service
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            service = self._service or AnalyzerService()
            results: list[AnalysisResult] = []
            for index, vid in enumerate(self._video_ids, start=1):
                if self._cancelled:
                    break
                self.progress.emit(index, len(self._video_ids), vid)
                try:
                    results.append(service.analyze_video(vid, self._config))
                except Exception as exc:  # noqa: BLE001
                    logger.exception("فشل تحليل المقطع %d: %s", vid, exc)
            self.finished.emit(results)
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل عامل الاستدلال")
            self.failed.emit(str(exc))


__all__ = ["InferenceWorker"]
