"""
新建方案弹窗
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from ui.core.base_dialog import BaseUiDialog
from ui.core.utils import get_ui_attr, safe_connect

UI_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = UI_ROOT / "scheme_newa.ui"


class SchemeNewDialog(BaseUiDialog):
    """新建方案对话框"""

    def __init__(self, parent=None):
        super().__init__(parent=parent, ui_path=UI_PATH)
        self._logger = logging.getLogger(__name__)

        cancel_btn = get_ui_attr(self.ui, "pushButton_cancel")
        safe_connect(self._logger, getattr(cancel_btn, "clicked", None), self.reject)
        ok_btn = get_ui_attr(self.ui, "pushButton_ok")
        safe_connect(self._logger, getattr(ok_btn, "clicked", None), self._on_ok)

    def _on_ok(self):
        name = self._get_text("lineEdit_schemeName")
        if not name:
            return
        self.accept()

    def _get_text(self, widget_name: str) -> str:
        widget = get_ui_attr(self.ui, widget_name)
        if widget is not None:
            try:
                return widget.text().strip()
            except Exception:
                return ""
        return ""

    def get_data(self) -> Dict[str, str]:
        """返回表单数据（EvaluationManager 表字段名）"""
        return {
            "EvaluationID": self._get_text("lineEdit_schemeName"),
            "Threshold1": self._get_text("lineEdit_mode"),
            "Threshold2": self._get_text("lineEdit_stimPos"),
            "Alpha": self._get_text("lineEdit_stimInterval"),
            "EvaluationTime": self._get_text("lineEdit_treatTime"),
        }
