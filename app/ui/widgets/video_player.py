"""مشغل فيديو بسيط لمعاينة المقاطع داخل التطبيق."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)


class VideoPlayer(QWidget):
    """مشغل فيديو بسيط مع شريط تحكم وزر تشغيل/إيقاف."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self._wire_signals()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._video_widget = QVideoWidget(self)
        self._video_widget.setMinimumHeight(240)
        layout.addWidget(self._video_widget, stretch=1)

        controls = QHBoxLayout()
        self._play_btn = QPushButton(self)
        self._play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        controls.addWidget(self._play_btn)

        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setRange(0, 0)
        controls.addWidget(self._slider, stretch=1)

        self._time_label = QLabel("0:00 / 0:00", self)
        controls.addWidget(self._time_label)

        layout.addLayout(controls)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video_widget)

    def _wire_signals(self) -> None:
        self._play_btn.clicked.connect(self._toggle_play)
        self._slider.sliderMoved.connect(self._player.setPosition)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._update_play_icon)

    # ============================================
    # واجهة عامة
    # ============================================
    def load(self, video_path: Path | str) -> None:
        """يُحمّل ملف فيديو ويعرضه بدون تشغيل."""
        path = Path(video_path)
        self._player.setSource(QUrl.fromLocalFile(str(path)))

    def clear(self) -> None:
        """يوقف ويفرّغ المشغل."""
        self._player.stop()
        self._player.setSource(QUrl())

    def seek(self, position_ms: int) -> None:
        """يقفز إلى توقيت محدد."""
        self._player.setPosition(int(position_ms))

    # ============================================
    # سلوك داخلي
    # ============================================
    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _update_play_icon(self, state: QMediaPlayer.PlaybackState) -> None:
        icon_id = (
            QStyle.StandardPixmap.SP_MediaPause
            if state == QMediaPlayer.PlaybackState.PlayingState
            else QStyle.StandardPixmap.SP_MediaPlay
        )
        self._play_btn.setIcon(self.style().standardIcon(icon_id))

    def _on_position(self, position_ms: int) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(position_ms)
        self._slider.blockSignals(False)
        self._update_time_label(position_ms, self._player.duration())

    def _on_duration(self, duration_ms: int) -> None:
        self._slider.setRange(0, duration_ms)
        self._update_time_label(self._player.position(), duration_ms)

    def _update_time_label(self, position_ms: int, duration_ms: int) -> None:
        self._time_label.setText(f"{_fmt(position_ms)} / {_fmt(duration_ms)}")


def _fmt(ms: int) -> str:
    """يُنسّق ميلي ثانية إلى m:ss أو h:mm:ss."""
    s = max(0, ms // 1000)
    minutes, sec = divmod(s, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:d}:{sec:02d}"
