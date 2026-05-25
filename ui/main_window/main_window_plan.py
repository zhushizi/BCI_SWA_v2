from __future__ import annotations
'''
方案页（tabWidget 的 tab3）管理
'''
import logging
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QPushButton, QHBoxLayout, QDialog, QTableWidgetItem

from ui.core.base_table_controller import BaseTableController
from ui.core.utils import get_ui_attr, safe_connect
from ui.dialogs.scheme_newa import SchemeNewDialog
from ui.dialogs.tips_dialog import TipsDialog


class PlanPageController(BaseTableController):
    """方案页（tabWidget 的 tab3）管理"""

    def __init__(
        self,
        parent: QWidget,
        ui,
        scheme_app,
        logger: Optional[logging.Logger] = None,
        on_plan_new_clicked=None,
    ):
        super().__init__(ui, table_name="tableWidget_plan")
        self.parent = parent
        self.scheme_app = scheme_app
        self.logger = logger or logging.getLogger(__name__)
        self._plan_data: List[dict] = []
        self._all_plan_data: List[dict] = []
        self._plan_delete_font_size = 18
        self._on_plan_new_clicked = on_plan_new_clicked

    # ---------- 对外接口 ----------
    def bind_signals(self):
        search = get_ui_attr(self.ui, "lineEdit_plan_search")
        safe_connect(self.logger, getattr(search, "textChanged", None), self._on_search_text_changed)
        reset_btn = get_ui_attr(self.ui, "pushButton_plan_reset")
        safe_connect(self.logger, getattr(reset_btn, "clicked", None), self._on_reset_search)
        new_btn = get_ui_attr(self.ui, "pushButton_plan_new")
        if callable(self._on_plan_new_clicked):
            safe_connect(self.logger, getattr(new_btn, "clicked", None), self._on_plan_new_clicked)
        else:
            safe_connect(self.logger, getattr(new_btn, "clicked", None), self._open_new_plan_dialog)

    def init_ui(self):
        self._setup_plan_table()

    def refresh(self):
        self._load_plan_data()

    def set_plan_action_font_size(self, size: int):
        if size and size > 0:
            self._plan_delete_font_size = size
            self.refresh()

    # ---------- 内部逻辑 ----------
    def _get_plan_table(self):
        return self.get_table()

    def _setup_plan_table(self):
        table = self._get_plan_table()
        if table is None:
            return

        self.init_table()
        table.setRowCount(0)
        for col in range(table.columnCount()):
            item = table.horizontalHeaderItem(col)
            if item is None:
                item = QTableWidgetItem()
                table.setHorizontalHeaderItem(col, item)
            item.setTextAlignment(Qt.AlignCenter)
        self._load_plan_data()

    def _load_plan_data(self):
        table = self._get_plan_table()
        if table is None:
            return

        plans: List[dict] = []
        try:
            plans = self.scheme_app.get_schemes()
        except Exception as e:
            self.logger.exception("加载评估数据失败")
            TipsDialog.show_tips(self.parent, f"加载评估数据失败: {e}")
            plans = []

        self._all_plan_data = plans or []
        self._apply_plan_filter()

    def _on_search_text_changed(self, _text: str = "") -> None:
        self._apply_plan_filter()

    def _on_reset_search(self) -> None:
        search = get_ui_attr(self.ui, "lineEdit_plan_search")
        if search is not None:
            search.clear()
        self._apply_plan_filter()

    def _apply_plan_filter(self) -> None:
        table = self._get_plan_table()
        if table is None:
            return
        keyword = ""
        search = get_ui_attr(self.ui, "lineEdit_plan_search")
        if search is not None:
            keyword = (search.text() or "").strip().lower()
        if not keyword:
            filtered = list(self._all_plan_data)
        else:
            filtered = []
            for plan in self._all_plan_data:
                pid = str(plan.get("PatientID", "") or "").lower()
                eid = str(plan.get("EvaluationID", "") or "").lower()
                if keyword in pid or keyword in eid:
                    filtered.append(plan)
        self._populate_plan_table(table, filtered)

    def _populate_plan_table(self, table, plans: List[dict]):
        self.clear_table()
        self._plan_data = plans or []

        if not plans:
            return

        table.setRowCount(len(plans))

        for row, plan in enumerate(plans):
            self.set_text_item(row, 0, plan.get("PatientID"))
            self.set_text_item(row, 1, plan.get("Threshold1"))
            self.set_text_item(row, 2, plan.get("Threshold2"))
            self.set_text_item(row, 3, plan.get("Alpha"))
            self.set_text_item(row, 4, plan.get("EvaluationTime"))
            self.set_text_item(row, 5, plan.get("EvaluationResult"))
            self._setup_plan_row_widgets(table, row)

    def _setup_plan_row_widgets(self, table, row: int):
        del_btn = QPushButton("删除")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setFlat(True)
        del_btn.setStyleSheet(self._plan_button_style())
        del_btn.clicked.connect(lambda checked, r=row: self._on_delete_plan_clicked(r))

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(del_btn)

        if table.columnCount() > 6:
            table.setCellWidget(row, 6, container)

    def _plan_button_style(self) -> str:
        return (
            "QPushButton {"
            "    color: #4B86FC;"
            "    background: transparent;"
            "    border: none;"
            f"    font-size: {self._plan_delete_font_size}px;"
            "}"
            "QPushButton:pressed {"
            "    color: #2f64c8;"
            "}"
        )

    def _on_delete_plan_clicked(self, row: int):
        if not self._plan_data or row >= len(self._plan_data):
            TipsDialog.show_tips(self.parent, "无法获取方案信息")
            return

        plan = self._plan_data[row]
        scheme_id = plan.get("SchemeId")
        scheme_name = plan.get("EvaluationID", "")

        if scheme_id is None:
            TipsDialog.show_tips(self.parent, "缺少方案标识，无法删除")
            return

        if not TipsDialog.show_confirm(self.parent, f"确定删除评估记录「{scheme_name or '未命名'}」？"):
            return

        try:
            ok = self.scheme_app.delete_scheme(scheme_id)
        except Exception as e:
            self.logger.error(f"删除方案异常: {e}")
            TipsDialog.show_tips(self.parent, f"删除方案失败: {e}")
            return

        if ok:
            TipsDialog.show_tips(self.parent, "删除方案成功")
            self.refresh()
        else:
            TipsDialog.show_tips(self.parent, "删除方案失败")

    def _open_new_plan_dialog(self):
        dialog = SchemeNewDialog(self.parent)
        if dialog.exec() != QDialog.Accepted:
            return

        data = dialog.get_data()
        try:
            ok = self.scheme_app.add_scheme(data)
        except Exception as e:
            self.logger.error(f"新增方案异常: {e}")
            TipsDialog.show_tips(self.parent, f"新增方案失败: {e}")
            return

        if ok:
            TipsDialog.show_tips(self.parent, "新增方案成功")
            self.refresh()
        else:
            TipsDialog.show_tips(self.parent, "新增方案失败")
