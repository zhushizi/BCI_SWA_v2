from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QMouseEvent
from PySide6.QtWidgets import QWidget


class WheelWidget(QWidget):
    """
    通用滚轮控件：仿手机时间选择器样式。

    - 垂直方向显示多行文本
    - 中间一行高亮放大，表示当前选中值
    - 通过鼠标滚轮或拖拽切换当前索引
    - 可复用于脉冲宽度、阈值等数值选择
    """

    currentIndexChanged = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._values: list[str] = []
        self._current_index: int = 0

        self._center_color = QColor(88, 122, 244)
        self._side_color = QColor(88, 122, 244)
        # 透明背景：让父级 widget 的背景透出
        self._bg_color = QColor(0, 0, 0, 0)

        self._row_count_visible = 5
        self._base_font_family = self.font().family()

        # 拖动状态
        self._dragging = False
        self._last_pos_y: float = 0.0
        self._drag_offset: float = 0.0  # 累积行偏移（小数），实现跟手滚动
        # 惯性滚动：松手时的速度（指数移动平均），单位：行/帧
        self._velocity: float = 0.0
        self._inertia_offset: float = 0.0  # 惯性阶段的累积偏移
        self._inertia_timer = QTimer(self)
        self._inertia_timer.setInterval(16)  # ~60 FPS
        self._inertia_timer.timeout.connect(self._on_inertia_step)

        self.setMinimumSize(80, 120)
        self.setFocusPolicy(Qt.NoFocus)
        # 允许使用透明背景
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    # ---------- 对外接口 ----------
    def set_values(self, values: Sequence[str]) -> None:
        self._values = [str(v) for v in values]
        if not self._values:
            self._current_index = 0
        else:
            self._current_index = max(0, min(self._current_index, len(self._values) - 1))
        self.update()

    def set_current_index(self, index: int) -> None:
        if not self._values:
            self._current_index = 0
            self.update()
            return
        idx = max(0, min(int(index), len(self._values) - 1))
        if idx != self._current_index:
            self._current_index = idx
            self.update()
            self.currentIndexChanged.emit(self._current_index)

    def current_index(self) -> int:
        return self._current_index

    def set_visible_row_count(self, row_count: int) -> None:
        """设置滚轮可见行数；使用奇数行以保证选中项位于正中。"""
        count = max(1, int(row_count))
        if count % 2 == 0:
            count += 1
        if count != self._row_count_visible:
            self._row_count_visible = count
            self.update()

    def set_item_colors(self, selected: QColor, unselected: QColor) -> None:
        """设置选中项与未选中项文字颜色。"""
        self._center_color = QColor(selected)
        self._side_color = QColor(unselected)
        self.update()

    # ---------- 内部绘制 ----------
    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        # 使用透明色清理自身区域，保留父级背景
        painter.fillRect(rect, self._bg_color)

        if not self._values:
            painter.setPen(QColor(180, 180, 180))
            painter.drawText(rect, Qt.AlignCenter, "--")
            return

        center_y = rect.center().y()
        # 可见行按高度等分，中间行表示当前选中值。
        line_spacing = rect.height() / float(self._row_count_visible)

        half_visible = self._row_count_visible // 2
        for offset in range(-half_visible, half_visible + 1):
            # 固定 7 行槽位：越界也保留行高，避免靠近首尾时行被挤压、选中项偏位
            y = center_y + offset * line_spacing
            idx = self._current_index + offset
            if idx < 0 or idx >= len(self._values):
                continue

            text = self._values[idx]

            # 根据距离中心的偏移设置字号和透明度
            dist = abs(offset)
            if dist == 0:
                font_size = 30
                alpha = 255
            elif dist == 1:
                font_size = 22
                alpha = 180
            else:
                font_size = 18 if dist == 2 else 16
                alpha = 120 if dist == 2 else 80

            font = QFont(self._base_font_family, font_size)
            painter.setFont(font)
            color = QColor(self._center_color if dist == 0 else self._side_color)
            color.setAlpha(alpha)
            painter.setPen(color)

            text_rect = rect.adjusted(0, 0, 0, 0)
            text_rect.setY(int(y - line_spacing / 2))
            text_rect.setHeight(int(line_spacing))
            painter.drawText(text_rect, Qt.AlignCenter, text)

    # ---------- 交互 ----------
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if not self._values:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        step = 1 if delta < 0 else -1
        self.set_current_index(self._current_index + step)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            if self._inertia_timer.isActive():
                self._inertia_timer.stop()
                self._velocity = 0.0
            self._dragging = True
            self._last_pos_y = float(event.position().y())
            self._drag_offset = 0.0
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if not self._dragging or not self._values:
            super().mouseMoveEvent(event)
            return
        y = float(event.position().y())
        dy = y - self._last_pos_y
        self._last_pos_y = y

        line_spacing = self.height() / float(self._row_count_visible or 1)
        if line_spacing <= 0:
            return
        # 累积偏移：拖动多少像素就换算成多少“行”，实现跟手滚动
        delta_index = dy / line_spacing
        self._drag_offset += delta_index
        # 每累积满整数行就更新索引（dy>0 向下拖 -> 索引减小）
        step = int(self._drag_offset)
        if step != 0:
            self.set_current_index(self._current_index - step)
            self._drag_offset -= step
        # 用指数移动平均记录速度，松手后用于惯性
        self._velocity = 0.6 * self._velocity + 0.4 * (-delta_index)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            # 松手时把“拖动的速度”略放大，使惯性更明显；然后启动惯性定时器
            if len(self._values) > 1 and abs(self._velocity) > 0.02:
                self._velocity *= 2.0
                self._inertia_offset = 0.0
                if not self._inertia_timer.isActive():
                    self._inertia_timer.start()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---------- 惯性滚动内部逻辑 ----------
    def _on_inertia_step(self) -> None:
        if not self._values:
            self._inertia_timer.stop()
            self._velocity = 0.0
            return
        # 每帧衰减，实现缓慢停止（衰减更慢一些）
        self._velocity *= 0.96
        # 把当前速度累加到惯性偏移中，允许小速度多帧后累积出步进
        self._inertia_offset += self._velocity

        step = int(self._inertia_offset)
        if step != 0:
            new_index = max(0, min(len(self._values) - 1, self._current_index + step))
            self.set_current_index(new_index)
            self._inertia_offset -= step
            # 碰到边界时停止惯性，避免在两端抖动
            if new_index == 0 or new_index == len(self._values) - 1:
                self._velocity = 0.0
                self._inertia_offset = 0.0
                self._inertia_timer.stop()
                return

        # 当速度和偏移都很小的时候停止
        if abs(self._velocity) < 0.23 and abs(self._inertia_offset) < 0.03:
            self._inertia_timer.stop()
            self._velocity = 0.0
            self._inertia_offset = 0.0
