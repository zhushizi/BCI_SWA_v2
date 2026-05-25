"""
诊疗记录对话框
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect

from ui.core.base_dialog import BaseUiDialog
from ui.core.utils import get_ui_attr, safe_connect
from ui.dialogs.treat_record.treat_record_actions import TreatRecordActions
from ui.dialogs.treat_record.treat_record_table import TreatRecordTable

UI_ROOT = Path(__file__).resolve().parents[2]
UI_PATH = UI_ROOT / "treat_record.ui"


class TreatRecordDialog(BaseUiDialog):
    """诊疗记录对话框"""

    def __init__(
        self,
        parent=None,
        patient_app=None,
        patient_id: str = None,
        patient_name: str = None,
        report_app=None,
        session_app=None,
    ):
        super().__init__(parent=parent, ui_path=UI_PATH, layout_spacing=0)
        self._logger = logging.getLogger(__name__)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14)
        shadow.setXOffset(0)
        shadow.setYOffset(0)
        shadow.setColor(QColor(0, 0, 0, 24))
        self.ui.setGraphicsEffect(shadow)
        _sheet = (self.ui.styleSheet() or "").strip()
        _extra = "border-radius: 32px; background-color: #ffffff"
        self.ui.setStyleSheet(f"{_sheet}; {_extra}" if _sheet else _extra)

        self.patient_app = patient_app
        self.report_app = report_app
        self.session_app = session_app
        self.patient_id = patient_id
        self.patient_name = patient_name

        self._table = TreatRecordTable(self.ui, self._logger)
        self._actions = TreatRecordActions(
            session_app=self.session_app,
            report_app=self.report_app,
            patient_id=self.patient_id,
            patient_name=self.patient_name,
            logger=self._logger,
        )

        self._init_ui()

    def _init_ui(self):
        self._table.setup_header_checkbox()
        self._setup_connections()
        if self.patient_id:
            self._load_treat_records()

    def _setup_connections(self):
        back_btn = get_ui_attr(self.ui, "pushButton")
        safe_connect(self._logger, getattr(back_btn, "clicked", None), self.accept)

        export_btn = get_ui_attr(self.ui, "pushButton_2")
        safe_connect(self._logger, getattr(export_btn, "clicked", None), self._on_export_clicked)

        delete_btn = get_ui_attr(self.ui, "pushButton_3")
        safe_connect(self._logger, getattr(delete_btn, "clicked", None), self._on_delete_clicked)

        self._table.bind_header_click()

    def _load_treat_records(self):
        if not self.session_app or not self.patient_id:
            return
        records = self.session_app.get_patient_treat_sessions_by_patient(self.patient_id)
        self._table.load_records(
            records,
            on_pdf_clicked=self._on_pdf_clicked,
            on_export_pdf_clicked=self._on_export_pdf_clicked,
            on_print_clicked=self._on_print_clicked,
        )

    def _on_export_clicked(self):
        pass

    def _on_delete_clicked(self):
        self._actions.delete_selected(self._table)

    def _on_print_clicked(self, row: int):
        self._actions.print_row(row)

    def _on_pdf_clicked(self, row: int):
        self._actions.pdf_row(row, self._table)

    def _on_export_pdf_clicked(self, row: int):
        self._actions.export_pdf_row(row, self._table)
