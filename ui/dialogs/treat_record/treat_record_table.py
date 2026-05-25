"""
诊疗记录表格渲染与交互逻辑。
"""

from __future__ import annotations

from typing import Callable, Iterable, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QTableWidgetItem, QWidget

from ui.core.table_utils import set_text_item
from ui.core.utils import get_ui_attr, safe_connect


class TreatRecordTable:
    def __init__(self, ui, logger):
        self.ui = ui
        self._logger = logger
        self._block_item_changed = False
        self._row_checkboxes: list[QCheckBox | None] = []

    def _get_table(self):
        return get_ui_attr(self.ui, "tableWidget_treatrecord")

    def setup_header_checkbox(self) -> None:
        table = self._get_table()
        if table is None:
            return
        header = table.horizontalHeader()
        header.setSectionsClickable(True)
        header_item = table.horizontalHeaderItem(0)
        if header_item is None:
            header_item = QTableWidgetItem()
            table.setHorizontalHeaderItem(0, header_item)
        header_item.setFlags(header_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        header_item.setCheckState(Qt.Unchecked)

    def bind_header_click(self) -> None:
        table = self._get_table()
        if table is None:
            return
        header = table.horizontalHeader()
        safe_connect(self._logger, getattr(header, "sectionClicked", None), self.on_header_section_clicked)

    def load_records(
        self,
        records: Iterable[dict],
        on_pdf_clicked: Callable[[int], None],
        on_export_pdf_clicked: Callable[[int], None],
        on_print_clicked: Callable[[int], None],
    ) -> None:
        table = self._get_table()
        if table is None:
            return

        table.setRowCount(0)
        self._row_checkboxes = []
        self._block_item_changed = True

        for record in records:
            row = table.rowCount()
            table.insertRow(row)
            self._set_checkbox_item(table, row, 0)
            item_pid = set_text_item(table, row, 1, record.get("PatientId", ""))
            try:
                item_pid.setData(Qt.UserRole, record.get("SessionId"))
            except Exception:
                pass
            set_text_item(table, row, 2, record.get("Paradigm", ""))
            set_text_item(table, row, 3, "-")
            set_text_item(table, row, 4, record.get("StimPosition", ""))
            set_text_item(table, row, 5, record.get("Pulsewidth", record.get("PulseWidth", record.get("StimFreqAB", ""))))
            set_text_item(table, row, 6, record.get("TotalTrainDuration", ""))
            set_text_item(table, row, 7, record.get("UpdateTime", ""))
            self._set_action_button(table, row, 8, on_pdf_clicked, on_export_pdf_clicked, on_print_clicked)

        self._block_item_changed = False
        self.update_header_check_state()

    def get_selected_session_ids(self) -> Tuple[list[int], list[int]]:
        table = self._get_table()
        if table is None:
            return [], []

        rows_to_delete: list[int] = []
        session_ids: list[int] = []
        for row, checkbox in enumerate(self._row_checkboxes):
            if checkbox and checkbox.checkState() == Qt.Checked:
                pid_item = table.item(row, 1)
                session_id = None
                if pid_item is not None:
                    session_id = pid_item.data(Qt.UserRole)
                if session_id:
                    rows_to_delete.append(row)
                    session_ids.append(session_id)
        return rows_to_delete, session_ids

    def remove_rows(self, rows: Iterable[int]) -> None:
        table = self._get_table()
        if table is None:
            return
        for row in sorted(rows, reverse=True):
            table.removeRow(row)
            if row < len(self._row_checkboxes):
                self._row_checkboxes.pop(row)
        self.update_header_check_state()

    def extract_row_data(self, row: int) -> tuple[dict, str | None, int | None]:
        table = self._get_table()
        if table is None:
            return {}, None, None
        record_data: dict = {}
        treat_start_time = None
        session_id = None
        for col in range(1, 8):
            item = table.item(row, col)
            if item:
                header_item = table.horizontalHeaderItem(col)
                if header_item:
                    header_text = header_item.text()
                    record_data[header_text] = item.text()
                    if header_text == "治疗时间":
                        treat_start_time = item.text()
        item_pid = table.item(row, 1)
        if item_pid is not None:
            try:
                session_id = item_pid.data(Qt.UserRole)
            except Exception:
                session_id = None
        return record_data, treat_start_time, session_id

    def update_header_check_state(self) -> None:
        table = self._get_table()
        if table is None:
            return
        header_item = table.horizontalHeaderItem(0)
        if header_item is None:
            return
        row_count = len(self._row_checkboxes)
        if row_count == 0:
            header_item.setCheckState(Qt.Unchecked)
            return
        checked = 0
        unchecked = 0
        for checkbox in self._row_checkboxes:
            if checkbox is None:
                continue
            if checkbox.checkState() == Qt.Checked:
                checked += 1
            elif checkbox.checkState() == Qt.Unchecked:
                unchecked += 1
        self._block_item_changed = True
        if checked == row_count:
            header_item.setCheckState(Qt.Checked)
        elif unchecked == row_count:
            header_item.setCheckState(Qt.Unchecked)
        else:
            header_item.setCheckState(Qt.PartiallyChecked)
        self._block_item_changed = False

    def on_header_section_clicked(self, index: int) -> None:
        if index != 0:
            return
        table = self._get_table()
        if table is None:
            return
        header_item = table.horizontalHeaderItem(0)
        if header_item is None:
            return
        new_state = Qt.Checked if header_item.checkState() != Qt.Checked else Qt.Unchecked
        self._block_item_changed = True
        for checkbox in self._row_checkboxes:
            if checkbox is not None:
                checkbox.setChecked(new_state == Qt.Checked)
        self._block_item_changed = False
        self.update_header_check_state()

    def _on_row_checkbox_changed(self, row: int, state: int) -> None:
        if self._block_item_changed:
            return
        self.update_header_check_state()

    def _set_checkbox_item(self, table, row: int, col: int) -> None:
        checkbox = QCheckBox()
        checkbox.setTristate(False)
        checkbox.stateChanged.connect(lambda state, r=row: self._on_row_checkbox_changed(r, state))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(checkbox)
        table.setCellWidget(row, col, container)
        while len(self._row_checkboxes) <= row:
            self._row_checkboxes.append(None)
        self._row_checkboxes[row] = checkbox

    def _set_action_button(
        self,
        table,
        row: int,
        col: int,
        on_pdf_clicked: Callable[[int], None],
        on_export_pdf_clicked: Callable[[int], None],
        on_print_clicked: Callable[[int], None],
    ) -> None:
        btn_pdf = QPushButton("PDF")
        btn_pdf.setCursor(Qt.PointingHandCursor)
        btn_pdf.setStyleSheet("color: #4B86FC; background: transparent; border: none;")
        btn_pdf.clicked.connect(lambda checked, r=row: on_pdf_clicked(r))

        btn_export = QPushButton("导出")
        btn_export.setCursor(Qt.PointingHandCursor)
        btn_export.setStyleSheet("color: #4B86FC; background: transparent; border: none;")
        btn_export.clicked.connect(lambda checked, r=row: on_export_pdf_clicked(r))

        btn_print = QPushButton("打印")
        btn_print.setCursor(Qt.PointingHandCursor)
        btn_print.setStyleSheet("color: #4B86FC; background: transparent; border: none;")
        btn_print.clicked.connect(lambda checked, r=row: on_print_clicked(r))

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addStretch()
        layout.addWidget(btn_pdf, alignment=Qt.AlignCenter)
        layout.addWidget(btn_export, alignment=Qt.AlignCenter)
        layout.addWidget(btn_print, alignment=Qt.AlignCenter)
        layout.addStretch()
        table.setCellWidget(row, col, container)
