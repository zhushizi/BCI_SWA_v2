from __future__ import annotations

import logging
from typing import Any, Optional

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPen, QColor, QPolygonF
from PySide6.QtWidgets import QWidget


class BCIWaveWidget(QWidget):
    """
    简易 EEG 波形显示控件（多通道叠加分区显示）。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._eeg_data: Any = None
        self._timestamp: float | None = None
        self._prev_timestamp: float | None = None
        self._buffers: list[list[float]] = []
        self._sample_interval: float | None = None
        self._window_sec = 10.0
        self._max_points = 800
        self._bg_color = QColor("#FFFFFF")
        self._grid_color = QColor("#E8E8E8")
        self._wave_color = QColor("#789EFF")
        self._label_color = QColor("#789EFF")
        self._draw_labels = True
        self._channel_labels: list[str] = []
        self._hidden_channel_indices: set[int] = set()
        self._extra_channel_labels: list[str] = []
        self._default_channel_count = 16

    def update_eeg(self, eeg_data: Any, timestamp: Optional[float] = None) -> None:
        self._append_frame(eeg_data, timestamp=timestamp)
        self.update()

    def set_draw_labels(self, enabled: bool) -> None:
        self._draw_labels = bool(enabled)
        self.update()

    def get_visible_labels(self) -> list[str]:
        labels: list[str] = []
        count = self._get_channel_count_for_labels()
        source = self._build_label_source(count)
        for idx, label in enumerate(source):
            channel_index = idx + 1
            if channel_index in self._hidden_channel_indices:
                continue
            if self._is_ch_placeholder(label):
                continue
            if label.upper() == "NONE":
                label = ""
            labels.append(label)
        if self._eeg_data is not None:
            labels.extend(self._extra_channel_labels)
        return labels

    def set_extra_channels(self, labels: list[str]) -> None:
        """底部模拟通道：有真实脑电数据时绘制水平直线，不参与数据缓冲。"""
        self._extra_channel_labels = [str(item or "").strip() for item in (labels or []) if str(item or "").strip()]
        self.update()

    def set_channel_labels(self, labels: list[str]) -> None:
        sanitized: list[str] = []
        for item in labels or []:
            text = str(item or "").strip()
            sanitized.append(text)
        self._channel_labels = sanitized
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        painter.fillRect(rect, self._bg_color)

        if self._eeg_data is None:
            painter.setPen(QPen(QColor(180, 180, 180), 1))
            painter.drawText(rect, Qt.AlignCenter, "暂无波形数据")
            return

        eeg = self._to_2d_array(self._eeg_data)
        if eeg is None:
            painter.setPen(QPen(QColor(180, 180, 180), 1))
            painter.drawText(rect, Qt.AlignCenter, "波形格式不支持")
            return

        visible_eeg, visible_labels = self._filter_channels(eeg)
        extra_labels = list(self._extra_channel_labels)

        n_chan = len(visible_eeg) + len(extra_labels)
        if n_chan <= 0:
            painter.setPen(QPen(QColor(180, 180, 180), 1))
            painter.drawText(rect, Qt.AlignCenter, "暂无波形数据")
            return

        width = rect.width()
        height = rect.height()
        channel_height = height / n_chan

        painter.setPen(QPen(self._grid_color, 1))
        for i in range(1, n_chan):
            y = int(i * channel_height)
            painter.drawLine(0, y, width, y)

        painter.setPen(QPen(self._wave_color, 1))
        for idx, samples in enumerate(visible_eeg):
            if not samples:
                continue
            data = self._downsample(samples, self._max_points)
            max_abs = max((abs(v) for v in data), default=1.0)
            if max_abs == 0:
                max_abs = 1.0

            y_offset = (idx + 0.5) * channel_height
            y_scale = channel_height * 0.4 / max_abs
            x_step = width / max(len(data) - 1, 1)

            label = visible_labels[idx] if idx < len(visible_labels) else ""
            if self._draw_labels and label:
                painter.setPen(self._label_color)
                painter.drawText(6, int(y_offset - channel_height * 0.3), label)

            painter.setPen(QPen(self._wave_color, 1))
            poly = QPolygonF()
            for i, v in enumerate(data):
                x = i * x_step
                y = y_offset - v * y_scale
                poly.append(QPointF(x, y))
            painter.drawPolyline(poly)

        base_idx = len(visible_eeg)
        for offset, label in enumerate(extra_labels):
            row_idx = base_idx + offset
            y_offset = (row_idx + 0.5) * channel_height
            if self._draw_labels and label:
                painter.setPen(self._label_color)
                painter.drawText(6, int(y_offset - channel_height * 0.3), label)
            painter.setPen(QPen(self._wave_color, 1))
            painter.drawLine(0, int(y_offset), width, int(y_offset))

    def _downsample(self, samples: list[float], max_points: int) -> list[float]:
        if len(samples) <= max_points:
            return samples
        step = max(int(len(samples) / max_points), 1)
        return samples[::step]

    def _append_frame(self, eeg_data: Any, timestamp: Optional[float]) -> None:
        eeg = self._to_2d_array(eeg_data)
        if eeg is None:
            self._eeg_data = None
            return

        n_chan = len(eeg)
        if n_chan <= 0:
            return

        if not self._buffers or len(self._buffers) != n_chan:
            self._buffers = [[] for _ in range(n_chan)]

        n_samples = len(eeg[0]) if eeg[0] else 0
        if timestamp is not None and n_samples > 0:
            if self._prev_timestamp is not None:
                delta = float(timestamp) - float(self._prev_timestamp)
                if delta > 0:
                    self._sample_interval = delta / float(n_samples)
            self._prev_timestamp = float(timestamp)

        for idx, samples in enumerate(eeg):
            if samples:
                self._buffers[idx].extend(samples)

        max_keep = self._get_max_keep()
        if max_keep > 0:
            for idx in range(n_chan):
                if len(self._buffers[idx]) > max_keep:
                    self._buffers[idx] = self._buffers[idx][-max_keep:]

        self._eeg_data = self._buffers
        self._timestamp = timestamp

    def _get_max_keep(self) -> int:
        if self._sample_interval and self._sample_interval > 0:
            return max(int(self._window_sec / self._sample_interval), 1)
        return self._max_points

    def _to_2d_array(self, eeg_data: Any) -> Optional[list[list[float]]]:
        if hasattr(eeg_data, "tolist") and hasattr(eeg_data, "shape"):
            try:
                data = eeg_data.tolist()
                if isinstance(data, list) and data and isinstance(data[0], list):
                    return [[float(v) for v in ch] for ch in data]
            except Exception:
                self._logger.exception("EEG 数据转换失败")

        if isinstance(eeg_data, list) and eeg_data:
            if all(isinstance(ch, list) for ch in eeg_data):
                return [[float(v) for v in ch] for ch in eeg_data]
        return None

    def _filter_channels(self, eeg: list[list[float]]) -> tuple[list[list[float]], list[str]]:
        visible_eeg: list[list[float]] = []
        visible_labels: list[str] = []
        source = self._build_label_source(len(eeg))
        for idx, samples in enumerate(eeg):
            channel_index = idx + 1
            if channel_index in self._hidden_channel_indices:
                continue
            label = ""
            if idx < len(source):
                label = source[idx]
            if self._is_ch_placeholder(label):
                continue
            if label.upper() == "NONE":
                label = ""
            visible_eeg.append(samples)
            visible_labels.append(label)
        return visible_eeg, visible_labels

    def _get_channel_count_for_labels(self) -> int:
        eeg_count = 0
        if isinstance(self._eeg_data, list) and self._eeg_data and isinstance(self._eeg_data[0], list):
            eeg_count = len(self._eeg_data)
        label_count = len(self._channel_labels) if self._channel_labels else 0
        return max(eeg_count, label_count, int(self._default_channel_count))

    def _build_label_source(self, count: int) -> list[str]:
        if count <= 0:
            return []
        source: list[str] = []
        for idx in range(count):
            if idx < len(self._channel_labels):
                source.append(self._channel_labels[idx])
            else:
                source.append("")
        return source

    @staticmethod
    def _is_ch_placeholder(label: str) -> bool:
        return "CH" in str(label or "").strip().upper()
