from __future__ import annotations

from enum import Enum
from typing import Optional

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class EvalWaveKind(Enum):
    SQUARE = "square"
    SHARP = "sharp"


class EvalWaveWidget(QWidget):
    """评估页波形预览：方波/尖波铺满控件宽度，可选简单滚动动画。"""

    def __init__(self, kind: EvalWaveKind, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._phase = 0.0
        self._animating = False
        self._bg_color = QColor("#DDDDDD")
        self._wave_color = QColor("#789EFF")
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._on_tick)
        self.setMinimumHeight(60)

    def set_background_color(self, color: str) -> None:
        self._bg_color = QColor(color)
        self.update()

    def start_animation(self) -> None:
        self._animating = True
        self._timer.start()

    def stop_animation(self) -> None:
        self._animating = False
        self._timer.stop()
        self._phase = 0.0
        self.update()

    def _on_tick(self) -> None:
        self._phase += 1.0
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        painter.fillRect(rect, self._bg_color)

        margin_x = 12
        margin_y = 14
        draw_left = float(rect.left() + margin_x)
        draw_right = float(rect.right() - margin_x)
        draw_width = max(1.0, draw_right - draw_left)
        mid_y = rect.center().y()
        amp = max(8.0, (rect.height() - 2 * margin_y) * 0.38)

        # 居中虚线基准
        dash_pen = QPen(self._wave_color, 1, Qt.PenStyle.DashLine)
        painter.setPen(dash_pen)
        painter.drawLine(QPointF(draw_left, mid_y), QPointF(draw_right, mid_y))

        wave_pen = QPen(self._wave_color, 2)
        painter.setPen(wave_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        scroll = (self._phase * 3.0) if self._animating else 0.0
        if self._kind == EvalWaveKind.SQUARE:
            path = self._build_square_path(draw_left, draw_width, mid_y, amp, scroll)
        else:
            path = self._build_sharp_path(draw_left, draw_width, mid_y, amp, scroll)

        painter.drawPath(path)

    def _cycle_count(self, width: float) -> int:
        # 按宽度自适应周期数，保证铺满
        return max(8, int(width / 48))

    def _build_square_path(
        self, left: float, width: float, mid_y: float, amp: float, scroll: float
    ) -> QPainterPath:
        high = mid_y - amp
        low = mid_y + amp
        cycles = self._cycle_count(width)
        half = width / (cycles * 2)

        path = QPainterPath()
        x = left - (scroll % (half * 2))
        y = high
        path.moveTo(x, y)

        # 多画一段，避免滚动时出现空白
        total_steps = cycles * 2 + 2
        for _ in range(total_steps):
            x_next = x + half
            path.lineTo(x_next, y)
            y = low if abs(y - high) < 0.01 else high
            path.lineTo(x_next, y)
            x = x_next

        return path

    def _build_sharp_path(
        self, left: float, width: float, mid_y: float, amp: float, scroll: float
    ) -> QPainterPath:
        """
        尖波：与方波共用 cycles / half，每个三角只占 half 宽度（与方波平台段等宽），
        这样同宽度下峰数与方波一致。
        """
        high = mid_y - amp
        low = mid_y + amp
        cycles = self._cycle_count(width)
        half = width / (cycles * 2)

        path = QPainterPath()
        x = left - (scroll % (half * 2))
        path.moveTo(x, high)

        total_steps = cycles * 2 + 2
        for i in range(total_steps):
            x_mid = x + half * 0.5
            x_end = x + half
            if i % 2 == 0:
                path.lineTo(x_mid, mid_y)
                path.lineTo(x_end, low)
            else:
                path.lineTo(x_mid, mid_y)
                path.lineTo(x_end, high)
            x = x_end

        return path
