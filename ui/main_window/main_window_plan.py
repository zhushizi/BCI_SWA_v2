from __future__ import annotations
'''
方案页（tabWidget 的 tab3）管理
'''
import logging
from math import ceil
from typing import List, Optional

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QWidget,
    QPushButton,
    QHBoxLayout,
    QDialog,
    QTableWidgetItem,
    QFrame,
    QLabel,
    QLineEdit,
)

from ui.core.base_table_controller import BaseTableController
from ui.core.utils import get_ui_attr, safe_connect
from ui.dialogs.scheme_newa import SchemeNewDialog
from ui.dialogs.tips_dialog import TipsDialog


class _PlanTableViewportFilter(QObject):
    """表格视口尺寸变化时重算每页行数并刷新分页。"""

    def __init__(self, controller: "PlanPageController") -> None:
        super().__init__()
        self._controller = controller

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            old_size = self._controller._page_size
            self._controller._recalculate_page_size()
            if self._controller._page_size != old_size:
                self._controller._refresh_page()
            else:
                self._controller._layout_pagination_position()
        return False


class PlanPageController(BaseTableController):
    """方案页（tabWidget 的 tab3）管理"""

    _PAGINATION_HEIGHT = 36
    _PAGINATION_RIGHT_INSET = 24
    _PAGINATION_BOTTOM_INSET = 6
    _DEFAULT_PAGE_SIZE = 15

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
        self._filtered_plans: List[dict] = []
        self._page_index = 0
        self._page_size = self._DEFAULT_PAGE_SIZE
        self._pagination_frame: Optional[QFrame] = None
        self._viewport_filter: Optional[_PlanTableViewportFilter] = None
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
        self._build_pagination()
        self._install_table_viewport_filter()
        self._update_pagination()

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

    def _install_table_viewport_filter(self) -> None:
        table = self._get_plan_table()
        if table is None:
            return
        viewport = table.viewport()
        if viewport is None:
            return
        if self._viewport_filter is not None:
            viewport.removeEventFilter(self._viewport_filter)
        self._viewport_filter = _PlanTableViewportFilter(self)
        viewport.installEventFilter(self._viewport_filter)

    def _build_pagination(self) -> None:
        if self._pagination_frame is not None:
            return

        table = self._get_plan_table()
        parent = table.parentWidget() if table is not None else self.parent
        if parent is None:
            parent = self.parent

        pagination = QFrame(parent)
        pagination.setObjectName("planManagePagination")
        pagination.setMinimumHeight(self._PAGINATION_HEIGHT)
        pagination.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        pagination.setStyleSheet(
            "QFrame#planManagePagination { background: transparent; }"
            "QLabel { color: #98A2B3; font-size: 12px; padding: 2px 0; }"
            "QPushButton {"
            "background: transparent;"
            "border: none;"
            "color: #98A2B3;"
            "font-size: 13px;"
            "padding: 0;"
            "}"
            "QPushButton:hover:enabled { color: #4B86FC; }"
            "QPushButton:disabled { color: #D7DDEA; }"
            "QLineEdit {"
            "background: #FFFFFF;"
            "border: none;"
            "border-radius: 4px;"
            "color: #8E8E93;"
            "font-size: 12px;"
            "padding: 1px 4px;"
            "}"
        )
        layout = QHBoxLayout(pagination)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch()

        self._total_label = QLabel("共0条", pagination)
        layout.addWidget(self._total_label)

        self._prev_button = QPushButton("<", pagination)
        self._prev_button.setFixedSize(16, 24)
        self._prev_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_button.clicked.connect(self._on_prev_page)
        layout.addWidget(self._prev_button)

        self._page_label = QLabel("0/0页", pagination)
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._page_label)

        self._next_button = QPushButton(">", pagination)
        self._next_button.setFixedSize(16, 24)
        self._next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_button.clicked.connect(self._on_next_page)
        layout.addWidget(self._next_button)

        layout.addSpacing(4)
        layout.addWidget(QLabel("前往", pagination))

        self._page_jump_input = QLineEdit(pagination)
        self._page_jump_input.setFixedSize(36, 20)
        self._page_jump_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_jump_input.setValidator(QIntValidator(1, 9999, self._page_jump_input))
        self._page_jump_input.returnPressed.connect(self._on_jump_page)
        self._page_jump_input.editingFinished.connect(self._on_jump_page)
        layout.addWidget(self._page_jump_input)

        layout.addWidget(QLabel("页", pagination))
        self._pagination_frame = pagination
        pagination.show()
        self._layout_pagination_position()

    def _layout_pagination_position(self) -> None:
        if self._pagination_frame is None:
            return
        table = self._get_plan_table()
        if table is None:
            return

        geo = table.geometry()
        self._pagination_frame.adjustSize()
        content_width = self._pagination_frame.sizeHint().width()
        pag_h = max(self._PAGINATION_HEIGHT, self._pagination_frame.sizeHint().height())
        pag_w = min(content_width, geo.width())
        pag_x = geo.x() + geo.width() - pag_w - self._PAGINATION_RIGHT_INSET
        pag_y = geo.y() + geo.height() - pag_h - self._PAGINATION_BOTTOM_INSET
        self._pagination_frame.setGeometry(pag_x, pag_y, pag_w, pag_h)
        self._pagination_frame.raise_()

    def _recalculate_page_size(self) -> None:
        table = self._get_plan_table()
        if table is None:
            return
        v_header = table.verticalHeader()
        row_height = v_header.defaultSectionSize() if v_header is not None else 46
        viewport_h = table.viewport().height()
        if viewport_h <= 0:
            header = table.horizontalHeader()
            header_h = header.height() if header is not None else 40
            viewport_h = max(table.geometry().height() - header_h, row_height)
        page_size = max(1, viewport_h // row_height)
        if page_size != self._page_size:
            self._page_size = page_size
            self._clamp_page_index()

    def _total_pages(self) -> int:
        if not self._filtered_plans:
            return 0
        return int(ceil(len(self._filtered_plans) / self._page_size))

    def _clamp_page_index(self) -> None:
        total_pages = self._total_pages()
        if total_pages <= 0:
            self._page_index = 0
            return
        self._page_index = min(max(self._page_index, 0), total_pages - 1)

    def _page_plans(self) -> List[dict]:
        start = self._page_index * self._page_size
        end = start + self._page_size
        return self._filtered_plans[start:end]

    def _update_pagination(self) -> None:
        if self._pagination_frame is None:
            return
        total = len(self._filtered_plans)
        total_pages = self._total_pages()
        current_page = 0 if total_pages == 0 else self._page_index + 1
        self._total_label.setText(f"共{total}条")
        self._page_label.setText(f"{current_page}/{total_pages}页")
        self._page_jump_input.setText("" if total_pages == 0 else str(current_page))
        self._page_jump_input.setEnabled(total_pages > 0)
        self._prev_button.setEnabled(self._page_index > 0)
        self._next_button.setEnabled(total_pages > 0 and self._page_index < total_pages - 1)
        self._layout_pagination_position()

    def _refresh_page(self) -> None:
        table = self._get_plan_table()
        if table is None:
            return
        self._recalculate_page_size()
        self._clamp_page_index()
        self._render_plan_table_page(table, self._page_plans())
        self._update_pagination()

    def _on_prev_page(self) -> None:
        if self._page_index <= 0:
            return
        self._page_index -= 1
        self._refresh_page()

    def _on_next_page(self) -> None:
        total_pages = self._total_pages()
        if total_pages == 0 or self._page_index >= total_pages - 1:
            return
        self._page_index += 1
        self._refresh_page()

    def _on_jump_page(self) -> None:
        total_pages = self._total_pages()
        if total_pages == 0:
            return
        text = self._page_jump_input.text().strip()
        try:
            page = int(text)
        except ValueError:
            self._update_pagination()
            return
        self._page_index = min(max(page, 1), total_pages) - 1
        self._refresh_page()

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
        self._page_index = 0
        self._apply_plan_filter()

    def _on_reset_search(self) -> None:
        search = get_ui_attr(self.ui, "lineEdit_plan_search")
        if search is not None:
            search.clear()
        self._page_index = 0
        self._apply_plan_filter()

    def _apply_plan_filter(self) -> None:
        keyword = ""
        search = get_ui_attr(self.ui, "lineEdit_plan_search")
        if search is not None:
            keyword = (search.text() or "").strip().lower()
        if not keyword:
            self._filtered_plans = list(self._all_plan_data)
        else:
            filtered = []
            for plan in self._all_plan_data:
                pid = str(plan.get("PatientID", "") or "").lower()
                eid = str(plan.get("EvaluationID", "") or "").lower()
                if keyword in pid or keyword in eid:
                    filtered.append(plan)
            self._filtered_plans = filtered
        self._refresh_page()

    def _render_plan_table_page(self, table, plans: List[dict]) -> None:
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
