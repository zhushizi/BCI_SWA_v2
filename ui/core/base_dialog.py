"""
通用对话框基类：统一 UI 加载与布局嵌入流程。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QFile, QIODevice, Qt, QEvent
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QShowEvent, QHideEvent

from ui.core.resource_loader import ensure_resources_loaded

# 继承 BaseUiDialog 的弹窗呼出时的固定坐标（左上角 x, y，单位像素）
DIALOG_FIXED_POSITION = (472, 150)

# 呼出弹窗时背后页面的灰色蒙版样式（半透明黑）
OVERLAY_STYLE = "background-color: rgba(0, 0, 0, 0.45);"


class BaseUiDialog(QDialog):
    """通用对话框：负责加载 .ui 并嵌入布局。"""

    def __init__(
        self,
        parent=None,
        ui_path: str | Path = "",
        layout_margins: Sequence[int] = (0, 0, 0, 0),
        layout_spacing: Optional[int] = None,
    ) -> None:
        super().__init__(parent)
        ensure_resources_loaded()
        self._logger = logging.getLogger(__name__)
        self.ui = self._load_ui(ui_path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*layout_margins)
        if layout_spacing is not None:
            layout.setSpacing(layout_spacing)
        layout.addWidget(self.ui)
        self._content_layout = layout
        self._overlay: Optional[QWidget] = None

    def showEvent(self, event: QShowEvent) -> None:
        """呼出时移动到固定坐标，并在父窗口上显示灰色蒙版。"""
        super().showEvent(event)
        x, y = DIALOG_FIXED_POSITION
        self.move(x, y)
        parent = self.parent()
        if isinstance(parent, QWidget) and parent.isVisible():
            self._overlay = QWidget(parent)
            self._overlay.setStyleSheet(OVERLAY_STYLE)
            self._overlay.setGeometry(parent.rect())
            self._overlay.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            self._overlay.raise_()
            self._overlay.show()
            parent.installEventFilter(self)

    def hideEvent(self, event: QHideEvent) -> None:
        """隐藏时移除灰色蒙版。"""
        parent = self.parent()
        if isinstance(parent, QWidget):
            parent.removeEventFilter(self)
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        """父窗口缩放时同步蒙版大小。"""
        if event.type() == QEvent.Resize and obj is self.parent() and self._overlay is not None:
            self._overlay.setGeometry(obj.rect())
        return super().eventFilter(obj, event)

    def _load_ui(self, ui_path: str | Path):
        ui_file = QFile(str(ui_path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise FileNotFoundError(f"无法打开 UI 文件: {ui_path}")
        loader = QUiLoader()
        form = loader.load(ui_file)
        ui_file.close()
        if form is None:
            raise RuntimeError(f"无法加载 UI 文件: {ui_path}")
        return form
