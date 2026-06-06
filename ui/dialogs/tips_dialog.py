"""
提示框对话框：单按钮用 tips_sigle.ui，双按钮（取消+确认）用 tips.ui。
图标按场景切换：成功用 icon_dialog_chengong，其余用 icon_dialog_gantan。
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QFile, QIODevice
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QVBoxLayout
from PySide6.QtUiTools import QUiLoader

from ui.core.dialog_overlay import OverlayDialog
from ui.core.resource_loader import ensure_resources_loaded
from ui.core.utils import get_ui_attr, safe_connect

UI_ROOT = Path(__file__).resolve().parents[1]
UI_PATH_SINGLE = UI_ROOT / "tips_sigle.ui"   # 仅「确认」
UI_PATH_QUESTION = UI_ROOT / "tips.ui"       # 「取消」+「确认」

ICON_SUCCESS = ":/set/pic/icon_dialog_chengong.png"
ICON_WARNING = ":/set/pic/icon_dialog_gantan.png"


class TipsIconType(Enum):
    SUCCESS = "success"
    WARNING = "warning"


def resolve_tips_icon(message: str = "", success: Optional[bool] = None) -> TipsIconType:
    """根据调用方设置或文案推断图标类型。"""
    if success is True:
        return TipsIconType.SUCCESS
    if success is False:
        return TipsIconType.WARNING
    msg = str(message or "")
    if "成功" in msg and "失败" not in msg:
        return TipsIconType.SUCCESS
    return TipsIconType.WARNING


class TipsDialog(OverlayDialog):
    """单按钮提示用 tips_sigle.ui，双按钮确认用 tips.ui。"""

    def __init__(
        self,
        parent=None,
        message: str = "",
        question: bool = False,
        success: Optional[bool] = None,
    ):
        super().__init__(parent)
        ensure_resources_loaded()
        self._logger = logging.getLogger(__name__)
        ui_path = UI_PATH_QUESTION if question else UI_PATH_SINGLE
        ui_file = QFile(str(ui_path))
        if not ui_file.open(QIODevice.ReadOnly):
            raise FileNotFoundError(f"无法打开 UI 文件: {ui_path}")
        loader = QUiLoader()
        self.ui = loader.load(ui_file)
        ui_file.close()
        if self.ui is None:
            raise RuntimeError(f"无法加载 UI 文件: {ui_path}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.ui)

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        close_btn = get_ui_attr(self.ui, "pushButton_close")
        safe_connect(self._logger, getattr(close_btn, "clicked", None), self.reject)
        confirm_btn = get_ui_attr(self.ui, "pushButton_confirm")
        if question:
            cancel_btn = get_ui_attr(self.ui, "pushButton_cancel")
            if cancel_btn is not None:
                safe_connect(self._logger, getattr(cancel_btn, "clicked", None), self.reject)
            safe_connect(self._logger, getattr(confirm_btn, "clicked", None), self.accept)
            self.set_icon(TipsIconType.WARNING)
        else:
            safe_connect(self._logger, getattr(confirm_btn, "clicked", None), self.reject)
            self.set_icon(resolve_tips_icon(message, success))

        self.set_message(message)

    def set_message(self, text: str) -> None:
        msg_label = get_ui_attr(self.ui, "label_message")
        if msg_label is not None:
            msg_label.setText(str(text or ""))

    def set_icon(self, icon_type: TipsIconType) -> None:
        icon_label = get_ui_attr(self.ui, "label_icon")
        if icon_label is None:
            return
        path = ICON_SUCCESS if icon_type == TipsIconType.SUCCESS else ICON_WARNING
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._logger.warning("提示框图标加载失败: %s", path)
            return
        icon_label.setPixmap(pixmap)

    @staticmethod
    def show_tips(
        parent=None,
        message: str = "",
        title: str = "",
        success: Optional[bool] = None,
    ) -> None:
        """显示单按钮提示框（点击确认/关闭后返回）。"""
        d = TipsDialog(parent, message=message, question=False, success=success)
        if title:
            d.setWindowTitle(title)
        d.exec()

    @staticmethod
    def show_confirm(parent=None, message: str = "") -> bool:
        """显示双按钮确认框（取消+确认），使用 tips.ui。返回 True 表示点击「确认」。"""
        d = TipsDialog(parent, message=message, question=True)
        return d.exec() == QDialog.DialogCode.Accepted

    @staticmethod
    def show_choice(
        parent=None,
        message: str = "",
        confirm_text: str = "确认",
        cancel_text: str = "取消",
    ) -> bool:
        """双按钮选择框，可自定义按钮文案。返回 True 表示点击确认钮，False 为取消或关闭。"""
        d = TipsDialog(parent, message=message, question=True)
        cancel_btn = get_ui_attr(d.ui, "pushButton_cancel")
        confirm_btn = get_ui_attr(d.ui, "pushButton_confirm")
        if cancel_btn is not None:
            cancel_btn.setText(str(cancel_text or "取消"))
        if confirm_btn is not None:
            confirm_btn.setText(str(confirm_text or "确认"))
        return d.exec() == QDialog.DialogCode.Accepted
