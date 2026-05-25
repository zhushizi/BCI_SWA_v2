"""
诊疗记录表格渲染与交互逻辑。
"""

from __future__ import annotations

from typing import Callable, Iterable, Tuple

from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QTableWidgetItem,
    QWidget,
    QHeaderView,
    QStyleOptionButton,
    QStyle,
)

from ui.core.table_utils import set_text_item
from ui.core.utils import get_ui_attr, safe_connect


class CheckBoxHeader(QHeaderView):
    """表头复选框（第 0 列）。"""

    checkStateChanged = Signal(Qt.CheckState)

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._check_state = Qt.Unchecked
        self.setSectionsClickable(True)

    def paintSection(self, painter, rect, logicalIndex):
        super().paintSection(painter, rect, logicalIndex)
        if logicalIndex != 0:
            return
        option = QStyleOptionButton()
        option.state |= QStyle.State_Enabled
        if self._check_state == Qt.Checked:
            option.state |= QStyle.State_On
        elif self._check_state == Qt.PartiallyChecked:
            option.state |= QStyle.State_NoChange
        else:
            option.state |= QStyle.State_Off
        option.rect = self._checkbox_rect(rect)
        self.style().drawControl(QStyle.CE_CheckBox, option, painter)

    def mousePressEvent(self, event):
        index = self.logicalIndexAt(event.pos())
        if index == 0 and self._checkbox_rect(self._section_rect(0)).contains(event.pos()):
            new_state = Qt.Unchecked if self._check_state == Qt.Checked else Qt.Checked
            self.setCheckState(new_state)
            self.checkStateChanged.emit(new_state)
            return
        super().mousePressEvent(event)

    def setCheckState(self, state: Qt.CheckState):
        if state == self._check_state:
            return
        self._check_state = state
        self.updateSection(0)

    def checkState(self) -> Qt.CheckState:
        return self._check_state

    def _checkbox_rect(self, section_rect) -> QRect:
        option = QStyleOptionButton()
        check_box_size = self.style().sizeFromContents(QStyle.CT_CheckBox, option, QSize(), None)
        x = section_rect.x() + (section_rect.width() - check_box_size.width()) // 2
        y = section_rect.y() + (section_rect.height() - check_box_size.height()) // 2
        return QRect(x, y, check_box_size.width(), check_box_size.height())

    def _section_rect(self, logicalIndex: int) -> QRect:
        return QRect(
            self.sectionPosition(logicalIndex),
            0,
            self.sectionSize(logicalIndex),
            self.height(),
        )


class TreatRecordTable:
    def __init__(self, ui, logger):
        self.ui = ui
        self._logger = logger
        self._block_item_changed = False
        self._row_checkboxes: list[QCheckBox | None] = []
        self._header_checkbox: CheckBoxHeader | None = None

    def _get_table(self):
        return get_ui_attr(self.ui, "tableWidget_treatrecord")

    def setup_header_checkbox(self) -> None:
        table = self._get_table()
        if table is None:
            return
        column_count = table.columnCount()
        if column_count == 0:
            return
        old_header = table.horizontalHeader()
        section_sizes = [old_header.sectionSize(i) for i in range(column_count)]
        default_section_size = old_header.defaultSectionSize()
        stretch_last = old_header.stretchLastSection()

        header = CheckBoxHeader(table)
        header.setDefaultSectionSize(default_section_size)
        for idx, size in enumerate(section_sizes):
            header.resizeSection(idx, size)
        header.setStretchLastSection(stretch_last)
        table.setHorizontalHeader(header)
        self._header_checkbox = header
        header.checkStateChanged.connect(self._on_header_checkbox_state_changed)

        for col in range(column_count):
            item = table.horizontalHeaderItem(col)
            if item is None:
                item = QTableWidgetItem()
                table.setHorizontalHeaderItem(col, item)
            item.setTextAlignment(Qt.AlignCenter)

    def bind_header_click(self) -> None:
        return

    def load_records(
        self,
        records: Iterable[dict],
        on_pdf_clicked: Callable[[int], None] | None = None,
        on_export_pdf_clicked: Callable[[int], None] | None = None,
        on_print_clicked: Callable[[int], None] | None = None,
        *,
        on_view_clicked: Callable[[int], None] | None = None,
        patient_name: str = "",
    ) -> None:
        """嵌入报告页用 on_view_clicked；弹窗用 PDF/导出/打印三个回调。"""
        if on_view_clicked is not None:
            self._load_records_embedded(records, on_view_clicked, patient_name)
            return
        if on_pdf_clicked is None or on_export_pdf_clicked is None or on_print_clicked is None:
            raise TypeError(
                "load_records 需要 on_view_clicked，或同时提供 "
                "on_pdf_clicked / on_export_pdf_clicked / on_print_clicked"
            )
        self._load_records_dialog(
            records, on_pdf_clicked, on_export_pdf_clicked, on_print_clicked
        )

    def _load_records_embedded(
        self,
        records: Iterable[dict],
        on_view_clicked: Callable[[int], None],
        patient_name: str,
    ) -> None:
        table = self._get_table()
        if table is None:
            return

        table.setRowCount(0)
        self._row_checkboxes = []
        self._block_item_changed = True
        display_name = (patient_name or "").strip()

        for record in records:
            row = table.rowCount()
            table.insertRow(row)
            self._set_checkbox_item(table, row, 0)
            name_text = display_name or str(record.get("PatientId", "") or "")
            item_name = set_text_item(table, row, 1, name_text)
            try:
                item_name.setData(Qt.UserRole, record.get("SessionId"))
            except Exception:
                pass
            set_text_item(table, row, 2, record.get("Paradigm", ""))
            set_text_item(table, row, 3, self._map_scheme_name(record.get("StimSchemeAB", "")))
            set_text_item(table, row, 4, self._map_stim_position(record.get("StimPosition", "")))
            set_text_item(table, row, 5, self._map_stim_interval(record.get("StimFreqAB", "")))
            set_text_item(table, row, 6, record.get("TotalTrainDuration", ""))
            set_text_item(table, row, 7, record.get("UpdateTime", ""))
            self._set_view_button(table, row, 8, on_view_clicked)

        self._block_item_changed = False
        self.update_header_check_state()

    def _load_records_dialog(
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
            set_text_item(
                table,
                row,
                4,
                record.get("StimPosition", ""),
            )
            set_text_item(
                table,
                row,
                5,
                record.get("Pulsewidth", record.get("PulseWidth", record.get("StimFreqAB", ""))),
            )
            set_text_item(table, row, 6, record.get("TotalTrainDuration", ""))
            set_text_item(table, row, 7, record.get("UpdateTime", ""))
            self._set_dialog_action_buttons(
                table, row, 8, on_pdf_clicked, on_export_pdf_clicked, on_print_clicked
            )

        self._block_item_changed = False
        self.update_header_check_state()

    @staticmethod
    def _map_stim_position(value) -> str:
        text = str(value or "").strip()
        if text.lower() == "up":
            return "吞咽"
        if text.lower() == "down":
            return "下肢"
        return text

    @staticmethod
    def _map_scheme_name(value) -> str:
        text = str(value or "").strip()
        if text == "0":
            return "方案一"
        if text == "1":
            return "方案二"
        return text

    @staticmethod
    def _map_stim_interval(value) -> str:
        text = str(value or "").strip()
        mapping = {
            "0": "0.5",
            "1": "0.6",
            "2": "0.7",
            "3": "0.8",
            "4": "0.9",
            "5": "1.0",
            "6": "2.0",
            "7": "3.0",
            "8": "4.0",
            "9": "5.0",
        }
        return mapping.get(text, text)

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
        if self._header_checkbox is None:
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
            checked = sum(
                1 for c in self._row_checkboxes if c and c.checkState() == Qt.Checked
            )
            self._block_item_changed = True
            if checked == row_count:
                header_item.setCheckState(Qt.Checked)
            elif checked == 0:
                header_item.setCheckState(Qt.Unchecked)
            else:
                header_item.setCheckState(Qt.PartiallyChecked)
            self._block_item_changed = False
            return

        row_count = len(self._row_checkboxes)
        if row_count == 0:
            self._header_checkbox.setCheckState(Qt.Unchecked)
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
            self._header_checkbox.setCheckState(Qt.Checked)
        elif unchecked == row_count:
            self._header_checkbox.setCheckState(Qt.Unchecked)
        else:
            self._header_checkbox.setCheckState(Qt.PartiallyChecked)
        self._block_item_changed = False

    def _on_header_checkbox_state_changed(self, state: Qt.CheckState) -> None:
        if self._block_item_changed:
            return
        if state not in (Qt.CheckState.Checked, Qt.CheckState.Unchecked):
            return
        self._block_item_changed = True
        checked = state == Qt.CheckState.Checked
        for checkbox in self._row_checkboxes:
            if checkbox is not None:
                checkbox.setChecked(checked)
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

    def _set_view_button(
        self,
        table,
        row: int,
        col: int,
        on_view_clicked: Callable[[int], None],
    ) -> None:
        btn_view = QPushButton("查看")
        btn_view.setCursor(Qt.PointingHandCursor)
        btn_view.setStyleSheet("color: #4B86FC; background: transparent; border: none;")
        btn_view.clicked.connect(lambda checked, r=row: on_view_clicked(r))

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()
        layout.addWidget(btn_view, alignment=Qt.AlignCenter)
        layout.addStretch()
        table.setCellWidget(row, col, container)

    def _set_dialog_action_buttons(
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
