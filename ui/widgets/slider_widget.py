from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import QWidget


class SliderWidget(QWidget):
    """
    通用竖直滑杆控件（顶部=最小值，底部=最大值）。

    - 竖直方向带倒角的轨道
    - 蓝色渐变自轨道顶部填至手柄
    - 圆形手柄与轨道左右相切
    - 可复用于脉冲宽度、阈值等数值选择
    """

    valueChanged = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._min_value = 0
        self._max_value = 100
        self._value = 50
        self._dragging = False

        # 透明背景：让父级 widget 的背景透出
        self._bg_color = QColor(0, 0, 0, 0)
        self._track_border_color = QColor(224, 228, 235)
        self._track_fill_top = QColor(153, 178, 255)
        self._track_fill_bottom = QColor(88, 122, 244)
        self._handle_color = QColor(88, 122, 244)
        self._handle_inner_color = QColor(255, 255, 255)

        self.setMinimumSize(40, 120)
        self.setMouseTracking(False)
        # 允许使用透明背景
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    # ----------- 对外接口 -----------
    def set_range(self, minimum: int, maximum: int) -> None:
        if maximum <= minimum:
            maximum = minimum + 1
        self._min_value = int(minimum)
        self._max_value = int(maximum)
        self.set_value(self._value)

    def set_value(self, value: int) -> None:
        v = max(self._min_value, min(self._max_value, int(value)))
        if v == self._value:
            return
        self._value = v
        self.update()
        self.valueChanged.emit(self._value)

    def value(self) -> int:
        return self._value

    # ----------- 内部几何计算 -----------
    def _track_geometry(self) -> Tuple[QRectF, float, float]:
        """
        返回 (轨道矩形, 圆角半径/手柄半径, 有效移动高度)。
        有效移动高度 = 轨道高度 - 2 * 半径。
        """
        rect = self.rect()
        margin_x = rect.width() * 0.3
        margin_y = rect.height() * 0.08
        track_width = max(10.0, rect.width() - 2 * margin_x)
        track_rect = QRectF(
            rect.center().x() - track_width / 2.0,
            rect.top() + margin_y,
            track_width,
            max(20.0, rect.height() - 2 * margin_y),
        )
        radius = track_rect.width() / 2.0
        effective_h = max(1.0, track_rect.height() - 2.0 * radius)
        return track_rect, radius, effective_h

    def _value_ratio(self) -> float:
        if self._max_value <= self._min_value:
            return 0.0
        return (self._value - self._min_value) / float(self._max_value - self._min_value)

    def _handle_center(self) -> QPointF:
        """手柄位置：顶部=最小值，底部=最大值。"""
        track_rect, radius, effective_h = self._track_geometry()
        t = self._value_ratio()
        center_x = track_rect.center().x()
        top_center_y = track_rect.top() + radius
        center_y = top_center_y + t * effective_h
        return QPointF(center_x, center_y)

    def _value_from_pos(self, y: float) -> int:
        """从屏幕 y 反算数值：顶部=最小值，底部=最大值。"""
        track_rect, radius, effective_h = self._track_geometry()
        top_center_y = track_rect.top() + radius
        t = (y - top_center_y) / effective_h
        t = max(0.0, min(1.0, t))
        value = self._min_value + t * (self._max_value - self._min_value)
        return int(round(value))

    # ----------- 绘制 -----------
    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # 使用透明色清理自身区域，保留父级背景
        painter.fillRect(self.rect(), self._bg_color)

        track_rect, radius, effective_h = self._track_geometry()

        # 轨道（带倒角）
        path_track = QPainterPath()
        path_track.addRoundedRect(track_rect, radius, radius)
        painter.setPen(QPen(self._track_border_color, 1))
        painter.setBrush(QBrush(Qt.white))
        painter.drawPath(path_track)

        # 填充部分：自轨道顶部到手柄中心（蓝色在刻度值上方）
        handle_center = self._handle_center()
        fill_top = track_rect.top()
        fill_bottom = max(handle_center.y(), track_rect.top())
        fill_rect = QRectF(track_rect.left(), fill_top, track_rect.width(), fill_bottom - fill_top)

        if fill_rect.height() > 0:
            gradient = QLinearGradient(
                track_rect.center().x(),
                fill_rect.top(),
                track_rect.center().x(),
                fill_rect.bottom(),
            )
            gradient.setColorAt(0.0, self._track_fill_top)
            gradient.setColorAt(1.0, self._track_fill_bottom)

            painter.save()
            painter.setClipPath(path_track)
            painter.fillRect(fill_rect, gradient)
            painter.restore()

        # 圆形手柄：外圈为轨道宽度（与轨道两侧相切），内圈为白色
        hr = radius
        handle_rect = QRectF(
            handle_center.x() - hr,
            handle_center.y() - hr,
            hr * 2.0,
            hr * 2.0,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._handle_color))
        painter.drawEllipse(handle_rect)

        inner_r = hr * 0.85
        inner_rect = QRectF(
            handle_center.x() - inner_r,
            handle_center.y() - inner_r,
            inner_r * 2.0,
            inner_r * 2.0,
        )
        painter.setBrush(QBrush(self._handle_inner_color))
        painter.drawEllipse(inner_rect)

    # ----------- 交互 -----------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        handle_center = self._handle_center()
        track_rect, radius, _ = self._track_geometry()
        hr = radius
        dx = event.position().x() - handle_center.x()
        dy = event.position().y() - handle_center.y()
        if dx * dx + dy * dy <= (hr + 4.0) * (hr + 4.0):
            self._dragging = True
            event.accept()
            return

        if track_rect.contains(event.position()):
            self.set_value(self._value_from_pos(event.position().y()))
            self._dragging = True
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        self.set_value(self._value_from_pos(event.position().y()))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)
