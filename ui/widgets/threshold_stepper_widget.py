from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget


class ThresholdStepperWidget(QFrame):
    """
    阈值加减器：左按钮「−」、中间数值、右按钮「+」。
    兼容原滚轮接口（currentIndexChanged / set_current_index / current_index）。
    """

    valueChanged = Signal(int)
    currentIndexChanged = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("thresholdStepper")
        self._min_value = 0
        self._max_value = 250
        self._step = 1
        self._value = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._minus_btn = QPushButton("−", self)
        self._value_label = QLabel("0", self)
        self._plus_btn = QPushButton("+", self)

        self._minus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._plus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._minus_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._plus_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._minus_btn.setFlat(True)
        self._plus_btn.setFlat(True)

        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_label.setFont(QFont(self.font().family(), 14))

        layout.addWidget(self._minus_btn)
        layout.addWidget(self._value_label, 1)
        layout.addWidget(self._plus_btn)

        self._minus_btn.clicked.connect(self._on_minus)
        self._plus_btn.clicked.connect(self._on_plus)
        self._apply_style()
        self._refresh()

    def set_range(self, minimum: int, maximum: int) -> None:
        if maximum <= minimum:
            maximum = minimum + 1
        self._min_value = int(minimum)
        self._max_value = int(maximum)
        self.set_value(self._value)

    def setRange(self, minimum: int, maximum: int) -> None:
        self.set_range(minimum, maximum)

    def set_single_step(self, step: int) -> None:
        self._step = max(1, int(step))
        self._refresh()

    def setSingleStep(self, step: int) -> None:
        self.set_single_step(step)

    def set_value(self, value: int) -> None:
        v = max(self._min_value, min(self._max_value, int(value)))
        if v == self._value:
            return
        self._value = v
        self._refresh()
        self.valueChanged.emit(self._value)
        self.currentIndexChanged.emit(self.current_index())

    def setValue(self, value: int) -> None:
        self.set_value(value)

    def value(self) -> int:
        return self._value

    def set_current_index(self, index: int) -> None:
        self.set_value(self._min_value + int(index) * self._step)

    def current_index(self) -> int:
        return (self._value - self._min_value) // self._step

    def installEventFilter(self, filter_obj) -> None:  # type: ignore[override]
        super().installEventFilter(filter_obj)
        self._minus_btn.installEventFilter(filter_obj)
        self._plus_btn.installEventFilter(filter_obj)
        self._value_label.installEventFilter(filter_obj)

    def setEnabled(self, enabled: bool) -> None:  # type: ignore[override]
        super().setEnabled(enabled)
        self._apply_style()

    def _on_minus(self) -> None:
        self.set_value(self._value - self._step)

    def _on_plus(self) -> None:
        self.set_value(self._value + self._step)

    def _refresh(self) -> None:
        self._value_label.setText(str(self._value))
        at_min = self._value <= self._min_value
        at_max = self._value >= self._max_value
        self._minus_btn.setEnabled(self.isEnabled() and not at_min)
        self._plus_btn.setEnabled(self.isEnabled() and not at_max)

    def _apply_style(self) -> None:
        if self.isEnabled():
            bg = "#F3F4F6"
            border = "#E5E7EB"
            fg = "#5B7CFF"
            sep = "#E5E7EB"
        else:
            bg = "#F7F7F7"
            border = "#ECECEC"
            fg = "#C8CCD3"
            sep = "#EEEEEE"

        self.setStyleSheet(
            f"QFrame#thresholdStepper {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; }}"
            f"QPushButton {{ background: transparent; border: none; color: {fg}; font-size: 22px; min-width: 54px; max-width: 54px; }}"
            f"QLabel {{ color: {fg}; border-left: 1px solid {sep}; border-right: 1px solid {sep}; background: transparent; }}"
            "QPushButton:disabled { color: #D0D4DA; }"
        )
        self._refresh()
