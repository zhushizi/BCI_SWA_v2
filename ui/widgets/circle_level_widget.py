"""
圆环等级滑块控件：可显示/可拖动圆环，中心显示当前等级（如 5 级）。
支持只读模式：仅显示、与 label 联动，不可拖动。
"""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QBrush, QMouseEvent
from PySide6.QtWidgets import QWidget


class CircleLevelWidget(QWidget):
    """圆环等级控件：分段圆弧、蓝色指针、中心「N级」。可设只读（不可调）。"""

    levelChanged = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._min_level = 0
        self._max_level = 99
        self._level = 0
        self._dragging = False
        self._read_only = False

        self._track_color = QColor(0xE4, 0xE4, 0xE4)
        self._arc_color = QColor(102, 164, 245)
        self._pointer_color = QColor(79, 126, 229)
        self._center_color = QColor(102, 164, 245)
        self._bg_color = QColor(255, 255, 255)
        self._text_color = QColor(255, 255, 255)

        self.setMinimumSize(120, 120)
        self.setMouseTracking(False)

    def level(self) -> int:
        return self._level

    def set_level(self, value: int) -> None:
        v = max(self._min_level, min(self._max_level, int(value)))
        if v != self._level:
            self._level = v
            self.update()
            self.levelChanged.emit(self._level)

    def set_level_range(self, min_level: int, max_level: int) -> None:
        self._min_level = max(0, int(min_level))
        self._max_level = max(self._min_level, int(max_level))
        self._level = max(self._min_level, min(self._max_level, self._level))
        self.update()

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = bool(read_only)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, read_only)

    def is_read_only(self) -> bool:
        return self._read_only

    def _angle_for_level(self, level: int) -> float:
        if self._max_level <= self._min_level:
            return 0.0
        t = (level - self._min_level) / (self._max_level - self._min_level)
        return (self._gauge_start_angle() + t * self._gauge_sweep_angle()) % 360.0

    def _level_from_angle(self, angle_deg: float) -> int:
        if self._max_level <= self._min_level:
            return self._min_level
        relative = (angle_deg - self._gauge_start_angle()) % 360.0
        sweep = self._gauge_sweep_angle()
        if relative > sweep:
            relative = sweep if relative - sweep < 360.0 - relative else 0.0
        t = relative / sweep
        return self._min_level + int(round(t * (self._max_level - self._min_level)))

    def _center_rect(self) -> QRectF:
        r = self.rect()
        side = min(r.width(), r.height())
        cx = r.x() + r.width() / 2
        cy = r.y() + r.height() / 2
        return QRectF(cx - side / 2, cy - side / 2, side, side)

    def _handle_radius_px(self) -> float:
        return 22.0

    def _handle_inner_radius_ratio(self) -> float:
        """摇杆内圆半径 / 外圆半径，调小则内圆直径变小，调大则变大。内圆直径 = 2 × 外圆半径 × 此值。"""
        return 0.5

    def _track_width(self) -> float:
        return 27.0

    def _track_outer_diameter(self) -> float:
        """灰色圆环外径（px）。"""
        return 298.0

    def _gauge_start_angle(self) -> float:
        """0 度在正上方，顺时针递增；起点放在左下方。"""
        return 222.0

    def _gauge_sweep_angle(self) -> float:
        """保留底部缺口，形成接近参考图的仪表盘弧线。"""
        return 276.0

    def _angle_to_point(self, cx: float, cy: float, radius: float, angle_deg: float) -> QPointF:
        rad = math.radians(-angle_deg + 90)
        return QPointF(cx + radius * math.cos(rad), cy - radius * math.sin(rad))

    def _point_to_angle(self, cx: float, cy: float, x: float, y: float) -> float:
        dx = x - cx
        dy = cy - y
        a = math.degrees(math.atan2(dx, dy))
        if a < 0:
            a += 360.0
        return a

    def _hit_handle(self, cx: float, cy: float, radius: float, x: float, y: float, scale: float) -> bool:
        p = self._angle_to_point(cx, cy, radius, self._angle_for_level(self._level))
        d = math.hypot(x - p.x(), y - p.y())
        return d <= self._handle_radius_px() * scale + 4

    def _ring_segment_path(
        self,
        cx: float,
        cy: float,
        inner_radius: float,
        outer_radius: float,
        start_angle: float,
        sweep_angle: float,
    ) -> QPainterPath:
        outer_rect = QRectF(cx - outer_radius, cy - outer_radius, outer_radius * 2, outer_radius * 2)
        inner_rect = QRectF(cx - inner_radius, cy - inner_radius, inner_radius * 2, inner_radius * 2)
        qt_start = 90.0 - start_angle

        path = QPainterPath()
        path.moveTo(self._angle_to_point(cx, cy, outer_radius, start_angle))
        path.arcTo(outer_rect, qt_start, -sweep_angle)
        path.lineTo(self._angle_to_point(cx, cy, inner_radius, start_angle + sweep_angle))
        path.arcTo(inner_rect, qt_start - sweep_angle, sweep_angle)
        path.closeSubpath()
        return path

    def _draw_ring_segment(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        inner_radius: float,
        outer_radius: float,
        start_angle: float,
        sweep_angle: float,
        color: QColor,
    ) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPath(
            self._ring_segment_path(cx, cy, inner_radius, outer_radius, start_angle, sweep_angle)
        )

    def _draw_segmented_ring(self, painter: QPainter, rect: QRectF, progress_sweep: float, scale: float) -> None:
        segment_count = 7
        gap = 3.5
        sweep = self._gauge_sweep_angle()
        segment_sweep = (sweep - gap * (segment_count - 1)) / segment_count
        start_angle = self._gauge_start_angle()
        cx = rect.center().x()
        cy = rect.center().y()
        radius_mid = rect.width() / 2
        half_width = self._track_width() * scale / 2
        outer_radius = radius_mid + half_width
        inner_radius = radius_mid - half_width

        for index in range(segment_count):
            segment_offset = index * (segment_sweep + gap)
            segment_start = start_angle + segment_offset
            self._draw_ring_segment(
                painter,
                cx,
                cy,
                inner_radius,
                outer_radius,
                segment_start,
                segment_sweep,
                self._track_color,
            )

            filled_sweep = min(segment_sweep, max(0.0, progress_sweep - segment_offset))
            if filled_sweep > 0:
                self._draw_ring_segment(
                    painter,
                    cx,
                    cy,
                    inner_radius,
                    outer_radius,
                    segment_start,
                    filled_sweep,
                    self._arc_color,
                )

    def _draw_center(self, painter: QPainter, cx: float, cy: float, scale: float) -> None:
        painter.setPen(Qt.NoPen)
        for radius, color in (
            (93.0 * scale, QColor(111, 170, 250, 42)),
            (82.0 * scale, QColor(104, 161, 246, 65)),
            (68.0 * scale, QColor(91, 142, 238, 88)),
        ):
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        center_r = 60.0 * scale
        painter.setBrush(QBrush(self._center_color))
        painter.drawEllipse(QRectF(cx - center_r, cy - center_r, center_r * 2, center_r * 2))

    def _draw_pointer(self, painter: QPainter, cx: float, cy: float, angle_deg: float, scale: float) -> None:
        tip_radius = 116.0 * scale
        base_radius = 39.0 * scale
        half_width = 22.0 * scale
        corner_radius = 8.0 * scale
        tip = self._angle_to_point(cx, cy, tip_radius, angle_deg)
        base = self._angle_to_point(cx, cy, base_radius, angle_deg)
        rad = math.radians(-angle_deg + 90)
        normal_x = -math.sin(rad)
        normal_y = -math.cos(rad)
        left = QPointF(base.x() + normal_x * half_width, base.y() + normal_y * half_width)
        right = QPointF(base.x() - normal_x * half_width, base.y() - normal_y * half_width)

        path = self._rounded_polygon_path([tip, left, right], corner_radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._pointer_color))
        painter.drawPath(path)

    def _rounded_polygon_path(self, points: list[QPointF], radius: float) -> QPainterPath:
        path = QPainterPath()
        if len(points) < 3:
            return path

        def point_between(start: QPointF, end: QPointF, distance: float) -> QPointF:
            length = math.hypot(end.x() - start.x(), end.y() - start.y())
            if length <= 0:
                return QPointF(start)
            ratio = min(0.45, distance / length)
            return QPointF(
                start.x() + (end.x() - start.x()) * ratio,
                start.y() + (end.y() - start.y()) * ratio,
            )

        start = point_between(points[0], points[-1], radius)
        path.moveTo(start)
        for index, point in enumerate(points):
            prev_point = points[index - 1]
            next_point = points[(index + 1) % len(points)]
            curve_start = point_between(point, prev_point, radius)
            curve_end = point_between(point, next_point, radius)
            path.lineTo(curve_start)
            path.quadTo(point, curve_end)
        path.closeSubpath()
        return path

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        rect = self._center_rect()
        cx = rect.center().x()
        cy = rect.center().y()
        scale = min(rect.width(), rect.height()) / 360.0
        outer_diameter = min(
            self._track_outer_diameter() * scale,
            min(rect.width(), rect.height()) - 20.0 * scale,
        )
        outer_r = outer_diameter / 2
        radius_mid = outer_r - self._track_width() * scale / 2
        radius = outer_r - self._track_width() * scale

        painter.fillRect(self.rect(), self._bg_color)

        # 外侧极浅轮廓，增强圆形层次感。
        painter.setPen(QPen(QColor(229, 238, 255, 110), 1.0 * scale))
        painter.setBrush(Qt.NoBrush)
        outline_r = outer_r + 18.0 * scale
        painter.drawEllipse(QRectF(cx - outline_r, cy - outline_r, outline_r * 2, outline_r * 2))

        track_rect = QRectF(
            cx - radius_mid,
            cy - radius_mid,
            radius_mid * 2,
            radius_mid * 2,
        )

        angle_deg = self._angle_for_level(self._level)
        progress_sweep = ((angle_deg - self._gauge_start_angle()) % 360.0)
        progress_sweep = min(progress_sweep, self._gauge_sweep_angle())
        painter.setBrush(Qt.NoBrush)
        self._draw_segmented_ring(painter, track_rect, progress_sweep, scale)
        self._draw_pointer(painter, cx, cy, angle_deg, scale)
        self._draw_center(painter, cx, cy, scale)

        text = f"{self._level}级"
        font = QFont(self.font())
        font.setPointSize(max(16, int(25 * scale)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self._text_color)
        painter.drawText(
            QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
            Qt.AlignCenter,
            text,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._read_only:
            return
        if event.button() != Qt.LeftButton:
            return
        rect = self._center_rect()
        cx = rect.center().x()
        cy = rect.center().y()
        scale = min(rect.width(), rect.height()) / 360.0
        outer_diameter = min(
            self._track_outer_diameter() * scale,
            min(rect.width(), rect.height()) - 20.0 * scale,
        )
        outer_r = outer_diameter / 2
        radius_mid = outer_r - self._track_width() * scale / 2

        if self._hit_handle(cx, cy, radius_mid, event.position().x(), event.position().y(), scale):
            self._dragging = True
            return
        dx = event.position().x() - cx
        dy = event.position().y() - cy
        d = math.hypot(dx, dy)
        if abs(d - radius_mid) <= self._track_width() * scale + 8:
            self.set_level(self._level_from_angle(self._point_to_angle(cx, cy, event.position().x(), event.position().y())))
            self._dragging = True

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._read_only:
            return
        if not self._dragging:
            return
        rect = self._center_rect()
        cx = rect.center().x()
        cy = rect.center().y()
        angle = self._point_to_angle(cx, cy, event.position().x(), event.position().y())
        self.set_level(self._level_from_angle(angle))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = False
