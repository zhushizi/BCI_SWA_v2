"""
新建患者弹窗
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Any, Optional

from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QApplication,
    QDateTimeEdit,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSpinBox,
    QToolButton,
    QWidgetAction,
)
from PySide6.QtGui import QPalette
from PySide6.QtCore import Qt, QDate, QDateTime
from ui.core.base_dialog import BaseUiDialog
from ui.core.utils import get_ui_attr, safe_call, safe_connect
from ui.dialogs.tips_dialog import TipsDialog

UI_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = UI_ROOT / "patient_newa.ui"

# 日历弹窗月份/年份下拉箭头样式（只注入一次，供 dateTimeEdit 的 calendarPopup 使用）
_CALENDAR_ARROW_STYLE = """
QCalendarWidget QToolButton#qt_calendar_monthbutton,
QCalendarWidget QToolButton#qt_calendar_yearbutton {
    padding-right: 20px;
    min-width: 60px;
}
QCalendarWidget QToolButton#qt_calendar_monthbutton::menu-indicator,
QCalendarWidget QToolButton#qt_calendar_yearbutton::menu-indicator {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    right: 4px;
    width: 14px;
    height: 14px;
}
"""

_VISIT_YEAR_MIN = 2000
_VISIT_YEAR_MAX = 2099
_VISIT_YEAR_MENU_VISIBLE_COUNT = 10


class PatientNewDialog(BaseUiDialog):
    """新建/编辑患者对话框"""

    def __init__(
        self,
        parent=None,
        data: Dict[str, Any] = None,
        is_edit: bool = False,
        patient_app: Optional[Any] = None,
    ):
        super().__init__(parent=parent, ui_path=UI_PATH)
        self._logger = logging.getLogger(__name__)
        self._is_edit = is_edit
        self._patient_app = patient_app

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 不为弹窗叠加阴影效果（避免四角出现 drop shadow）。
        self.ui.setGraphicsEffect(None)
        close_btn = get_ui_attr(self.ui, "label_close")
        safe_connect(self._logger, getattr(close_btn, "clicked", None), self.reject)

        date_edit = get_ui_attr(self.ui, "dateTimeEdit_visit")
        safe_call(self._logger, getattr(date_edit, "setDateTime", None), QDateTime.currentDateTime())
        if isinstance(date_edit, QDateTimeEdit):
            self._configure_visit_date_edit(date_edit)

        age_input = get_ui_attr(self.ui, "spinBox_age")
        if age_input:
            safe_call(self._logger, getattr(age_input, "setValidator", None), QIntValidator(1, 120, age_input))

        height_input = get_ui_attr(self.ui, "lineEdit_height")
        if height_input:
            hv = QDoubleValidator(30.0, 250.0, 1, height_input)
            hv.setNotation(QDoubleValidator.StandardNotation)
            safe_call(self._logger, getattr(height_input, "setValidator", None), hv)

        weight_input = get_ui_attr(self.ui, "lineEdit_weight")
        if weight_input:
            wv = QDoubleValidator(1.0, 300.0, 1, weight_input)
            wv.setNotation(QDoubleValidator.StandardNotation)
            safe_call(self._logger, getattr(weight_input, "setValidator", None), wv)

        birth_edit = get_ui_attr(self.ui, "dateEdit_birthday")
        if birth_edit:
            safe_call(self._logger, getattr(birth_edit, "setSpecialValueText", None), "")
            safe_call(self._logger, getattr(birth_edit, "setDate", None), birth_edit.minimumDate())

        pid_input = get_ui_attr(self.ui, "lineEdit_patientId")
        auto_pid = QDateTime.currentDateTime().toString("yyMMddHHmmss")
        safe_call(self._logger, getattr(pid_input, "setText", None), auto_pid)

        if self._is_edit:
            self.setWindowTitle("编辑患者")
            title_label = get_ui_attr(self.ui, "label")
            safe_call(
                self._logger,
                getattr(title_label, "setStyleSheet", None),
                "border-image: url(:/patient/pic/patient_revise_logo.png);",
            )
        if data:
            self.set_data(data)

        self._apply_calendar_arrow_style()

        cancel_btn = get_ui_attr(self.ui, "pushButton_cancel")
        safe_connect(self._logger, getattr(cancel_btn, "clicked", None), self.reject)
        ok_btn = get_ui_attr(self.ui, "pushButton_ok")
        if ok_btn:
            try:
                ok_btn.clicked.disconnect()
            except TypeError:
                pass
            safe_connect(self._logger, ok_btn.clicked, self._on_ok)

        # .ui 里设的是根控件的尺寸，实际窗口是 BaseUiDialog 的外层 QDialog，需在此固定大小以防拖动调整
        self.setFixedSize(1046, 608)

    @classmethod
    def _apply_calendar_arrow_style(cls) -> None:
        """为应用注入日历月份/年份下拉箭头样式（只执行一次），修正箭头位置。"""
        if getattr(cls, "_calendar_style_applied", False):
            return
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet((app.styleSheet() or "") + _CALENDAR_ARROW_STYLE)
            cls._calendar_style_applied = True

    def _configure_visit_date_edit(self, date_edit: QDateTimeEdit) -> None:
        """就诊日期：年份按钮与月份同为 QToolButton 下拉，列表约 10 行可滚轮。"""
        calendar = date_edit.calendarWidget()
        if calendar is None:
            return

        year_btn = calendar.findChild(QToolButton, "qt_calendar_yearbutton")
        if year_btn is None:
            return

        month_btn = calendar.findChild(QToolButton, "qt_calendar_monthbutton")

        year_spin = calendar.findChild(QSpinBox, "qt_calendar_yearedit")
        if year_spin is not None:
            year_spin.hide()

        min_date = QDate(_VISIT_YEAR_MIN, 1, 1)
        max_date = QDate(_VISIT_YEAR_MAX, 12, 31)
        date_edit.setDateRange(min_date, max_date)
        calendar.setDateRange(min_date, max_date)

        current_year = date_edit.date().year()
        current_year = max(_VISIT_YEAR_MIN, min(_VISIT_YEAR_MAX, current_year))

        year_btn.setText(str(current_year))
        year_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        year_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        if month_btn is not None:
            year_btn.setFont(month_btn.font())
            year_btn.setPalette(month_btn.palette())

        def apply_calendar_year(year: int) -> None:
            selected = calendar.selectedDate()
            max_day = QDate(year, selected.month(), 1).daysInMonth()
            calendar.setSelectedDate(
                QDate(year, selected.month(), min(selected.day(), max_day))
            )
            year_btn.setText(str(year))

        # QMenu 外壳与月份一致；内嵌固定高度列表（约 10 行），避免 100 个 QAction 撑满屏幕
        menu = QMenu(year_btn)
        month_menu = month_btn.menu() if month_btn is not None else None
        if month_menu is not None:
            menu.setStyle(month_menu.style())
            menu.setFont(month_menu.font())
            menu.setPalette(month_menu.palette())
        elif month_btn is not None:
            menu.setFont(month_btn.font())
            menu.setPalette(month_btn.palette())

        list_widget = QListWidget(menu)
        list_widget.setFrameShape(QFrame.Shape.NoFrame)
        list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        list_widget.setSpacing(0)
        if month_menu is not None:
            list_widget.setFont(month_menu.font())
            list_widget.setPalette(month_menu.palette())
            list_widget.setStyleSheet(self._year_list_style_from_menu(month_menu))
            list_widget.setMinimumWidth(max(month_menu.sizeHint().width(), year_btn.sizeHint().width()))
        elif month_btn is not None:
            list_widget.setFont(month_btn.font())

        row_height = list_widget.fontMetrics().height() + 6
        list_widget.setFixedHeight(row_height * _VISIT_YEAR_MENU_VISIBLE_COUNT + 2)

        for year in range(_VISIT_YEAR_MAX, _VISIT_YEAR_MIN - 1, -1):
            item = QListWidgetItem(str(year))
            item.setData(Qt.ItemDataRole.UserRole, year)
            list_widget.addItem(item)

        def on_year_item_clicked(item: QListWidgetItem) -> None:
            year = item.data(Qt.ItemDataRole.UserRole)
            if year is None:
                return
            try:
                apply_calendar_year(int(year))
            except (TypeError, ValueError):
                return
            menu.close()

        list_widget.itemClicked.connect(on_year_item_clicked)

        menu_action = QWidgetAction(menu)
        menu_action.setDefaultWidget(list_widget)
        menu.addAction(menu_action)
        year_btn.setMenu(menu)

        def scroll_year_list_to_current() -> None:
            year = calendar.yearShown()
            for row in range(list_widget.count()):
                item = list_widget.item(row)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == year:
                    list_widget.setCurrentRow(row)
                    list_widget.scrollToItem(item, Qt.ScrollHint.PositionAtCenter)
                    break

        menu.aboutToShow.connect(scroll_year_list_to_current)

        def on_page_changed(year: int, _month: int) -> None:
            year_btn.setText(str(year))

        calendar.currentPageChanged.connect(on_page_changed)

    @staticmethod
    def _year_list_style_from_menu(month_menu: QMenu) -> str:
        """列表项配色对齐月份 QMenu（系统菜单高亮/背景）。"""
        pal = month_menu.palette()
        bg = pal.color(QPalette.ColorRole.Window).name()
        fg = pal.color(QPalette.ColorRole.WindowText).name()
        hl = pal.color(QPalette.ColorRole.Highlight).name()
        hlf = pal.color(QPalette.ColorRole.HighlightedText).name()
        return f"""
QListWidget {{
    background-color: {bg};
    color: {fg};
    border: none;
    outline: 0;
}}
QListWidget::item {{
    padding: 4px 28px 4px 12px;
}}
QListWidget::item:selected {{
    background-color: {hl};
    color: {hlf};
}}
"""

    @staticmethod
    def _is_valid_id_card(s: str) -> bool:
        """15 位全数字，或 18 位（前 17 位数字，末位数字或 X）。"""
        t = (s or "").strip()
        if not t:
            return True  # 未填不强制（仅对已填内容校验格式）
        if len(t) == 15:
            return t.isdigit()
        if len(t) == 18:
            return t[:17].isdigit() and (t[17].isdigit() or t[17].upper() == "X")
        return False

    @staticmethod
    def _is_valid_phone(s: str) -> bool:
        """11 位纯数字；未填不强制。"""
        t = (s or "").strip()
        if not t:
            return True
        return len(t) == 11 and t.isdigit()

    @staticmethod
    def _parse_float(text: str) -> Optional[float]:
        t = (text or "").strip()
        if not t:
            return None
        try:
            return float(t)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_valid_ethnicity(text: str) -> bool:
        """
        民族字段合理性校验：
        - 不能为空
        - 仅允许中文、英文与中间空格
        - 长度限制 2~20
        """
        t = (text or "").strip()
        if not t:
            return False
        if not (2 <= len(t) <= 20):
            return False
        for ch in t:
            if ch == " ":
                continue
            if "\u4e00" <= ch <= "\u9fff":
                continue
            if ch.isalpha():
                continue
            return False
        return True

    def _on_ok(self):
        pid = self._get_text("lineEdit_patientId")
        name = self._get_text("lineEdit_name")
        if not pid or not name:
            TipsDialog.show_tips(self, "请填写姓名（必填项）")
            name_input = get_ui_attr(self.ui, "lineEdit_name")
            safe_call(self._logger, getattr(name_input, "setFocus", None))
            return
        id_card = self._get_text("lineEdit_idCard")
        if id_card and not self._is_valid_id_card(id_card):
            TipsDialog.show_tips(self, "身份证号不规范，请重新填写")
            id_input = get_ui_attr(self.ui, "lineEdit_idCard")
            safe_call(self._logger, getattr(id_input, "setFocus", None))
            return
        phone = self._get_text("lineEdit_phone")
        if phone and not self._is_valid_phone(phone):
            TipsDialog.show_tips(self, "手机号须为11位纯数字，请重新填写")
            phone_input = get_ui_attr(self.ui, "lineEdit_phone")
            safe_call(self._logger, getattr(phone_input, "setFocus", None))
            return
        age_text = self._get_text("spinBox_age")
        if age_text:
            try:
                age = int(age_text)
            except (TypeError, ValueError):
                age = None
            if age is None or age < 1 or age > 120:
                TipsDialog.show_tips(self, "年龄需为1-120，请重新填写")
                age_input = get_ui_attr(self.ui, "spinBox_age")
                safe_call(self._logger, getattr(age_input, "setFocus", None))
                safe_call(self._logger, getattr(age_input, "selectAll", None))
                return

        height_text = self._get_text("lineEdit_height")
        if height_text:
            height = self._parse_float(height_text)
            if height is None or not (30.0 <= height <= 250.0):
                TipsDialog.show_tips(self, "身高需为 30-250 cm，请重新填写")
                height_input = get_ui_attr(self.ui, "lineEdit_height")
                safe_call(self._logger, getattr(height_input, "setFocus", None))
                safe_call(self._logger, getattr(height_input, "selectAll", None))
                return

        weight_text = self._get_text("lineEdit_weight")
        if weight_text:
            weight = self._parse_float(weight_text)
            if weight is None or not (1.0 <= weight <= 300.0):
                TipsDialog.show_tips(self, "体重需为 1-300 kg，请重新填写")
                weight_input = get_ui_attr(self.ui, "lineEdit_weight")
                safe_call(self._logger, getattr(weight_input, "setFocus", None))
                safe_call(self._logger, getattr(weight_input, "selectAll", None))
                return

        birth_edit = get_ui_attr(self.ui, "dateEdit_birthday")
        if birth_edit:
            try:
                birth_date = birth_edit.date()
                if (
                    birth_date != birth_edit.minimumDate()
                    and birth_date > QDateTime.currentDateTime().date()
                ):
                    TipsDialog.show_tips(self, "出生日期不能晚于今天")
                    safe_call(self._logger, getattr(birth_edit, "setFocus", None))
                    return
            except Exception:
                TipsDialog.show_tips(self, "出生日期格式不正确，请重新选择")
                safe_call(self._logger, getattr(birth_edit, "setFocus", None))
                return

        ethnicity = self._get_text("lineEdit_ethnicity")
        if ethnicity and not self._is_valid_ethnicity(ethnicity):
            TipsDialog.show_tips(self, "民族需为 2-20 位中英文字符，请重新填写")
            ethnicity_input = get_ui_attr(self.ui, "lineEdit_ethnicity")
            safe_call(self._logger, getattr(ethnicity_input, "setFocus", None))
            safe_call(self._logger, getattr(ethnicity_input, "selectAll", None))
            return
        if (
            not self._is_edit
            and self._patient_app is not None
            and getattr(self._patient_app, "patient_id_exists", None)
            and self._patient_app.patient_id_exists(pid)
        ):
            TipsDialog.show_tips(self, "就诊编号（病历号）已存在，请使用其他编号")
            pid_input = get_ui_attr(self.ui, "lineEdit_patientId")
            safe_call(self._logger, getattr(pid_input, "setFocus", None))
            safe_call(self._logger, getattr(pid_input, "selectAll", None))
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

    def set_data(self, data: Dict[str, Any]):
        """将传入数据回填到表单中"""
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_patientId"), "setText", None), str(data.get("PatientId", "")))
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_name"), "setText", None), str(data.get("Name", "")))
        combo_gender = get_ui_attr(self.ui, "comboBox_gender")
        if combo_gender:
            sex = data.get("Sex", "")
            index = combo_gender.findText(sex)
            if index != -1:
                safe_call(self._logger, combo_gender.setCurrentIndex, index)
        combo_marital = get_ui_attr(self.ui, "comboBox_marital")
        if combo_marital:
            marital = data.get("MaritalStatus", "")
            index = combo_marital.findText(marital)
            if index != -1:
                safe_call(self._logger, combo_marital.setCurrentIndex, index)
        spin_age = get_ui_attr(self.ui, "spinBox_age")
        if spin_age:
            age = data.get("Age")
            if age is not None:
                safe_call(self._logger, spin_age.setText, str(age))
        date_edit = get_ui_attr(self.ui, "dateTimeEdit_visit")
        if date_edit:
            visit_time = data.get("VisitTime", "")
            dt = QDateTime.fromString(visit_time, "yyyy/MM/dd HH:mm:ss")
            if dt.isValid():
                safe_call(self._logger, date_edit.setDateTime, dt)
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_phone"), "setText", None), str(data.get("PhoneNumber", "")))
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_idCard"), "setText", None), str(data.get("IdCard", "")))
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_notes"), "setText", None), str(data.get("Notes", "")))
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_diagnosisResult"), "setText", None), str(data.get("DiagnosisResult", "")))
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_durationOfIllness"), "setText", None), str(data.get("DurationOfillness", "")))
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_underlyingHealthCondition"), "setText", None), str(data.get("UnderlyingHealthCondition", "")))
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_height"), "setText", None), str(data.get("Height", "") or ""))
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_weight"), "setText", None), str(data.get("Weight", "") or ""))
        safe_call(self._logger, getattr(get_ui_attr(self.ui, "lineEdit_ethnicity"), "setText", None), str(data.get("Ethnicity", "") or ""))
        birth_edit = get_ui_attr(self.ui, "dateEdit_birthday")
        if birth_edit:
            birthday = str(data.get("Birthday", "") or "").strip()
            if birthday:
                for fmt in ("yyyy/MM/dd", "yyyy/MM/dd HH:mm:ss", "yyyy-MM-dd"):
                    dt = QDateTime.fromString(birthday, fmt)
                    if dt.isValid():
                        safe_call(self._logger, birth_edit.setDate, dt.date())
                        break

    def get_data(self) -> Dict[str, Any]:
        """获取表单数据"""
        sex = ""
        combo_gender = get_ui_attr(self.ui, "comboBox_gender")
        if combo_gender:
            sex = combo_gender.currentText()

        marital_status = ""
        combo_marital = get_ui_attr(self.ui, "comboBox_marital")
        if combo_marital:
            marital_status = combo_marital.currentText()

        age = None
        spin_age = get_ui_attr(self.ui, "spinBox_age")
        if spin_age:
            age_text = ""
            try:
                age_text = (spin_age.text() or "").strip()
            except Exception:
                age_text = ""
            if age_text:
                try:
                    age = int(age_text)
                except (TypeError, ValueError):
                    age = None

        visit_time = ""
        date_edit = get_ui_attr(self.ui, "dateTimeEdit_visit")
        if date_edit:
            visit_time = date_edit.dateTime().toString("yyyy/MM/dd HH:mm:ss")

        birthday = ""
        birth_edit = get_ui_attr(self.ui, "dateEdit_birthday")
        if birth_edit:
            try:
                if birth_edit.date() != birth_edit.minimumDate():
                    birthday = birth_edit.date().toString("yyyy/MM/dd")
            except Exception:
                birthday = ""

        return {
            "PatientId": self._get_text("lineEdit_patientId"),
            "Name": self._get_text("lineEdit_name"),
            "Sex": sex,
            "MaritalStatus": marital_status,
            "Age": age,
            "VisitTime": visit_time,
            "PhoneNumber": self._get_text("lineEdit_phone"),
            "IdCard": self._get_text("lineEdit_idCard"),
            "Notes": self._get_text("lineEdit_notes"),
            "Birthday": birthday,
            "Height": self._get_text("lineEdit_height"),
            "Weight": self._get_text("lineEdit_weight"),
            "Ethnicity": self._get_text("lineEdit_ethnicity"),
            "DiagnosisResult": self._get_text("lineEdit_diagnosisResult"),
            "DurationOfillness": self._get_text("lineEdit_durationOfIllness"),
            "UnderlyingHealthCondition": self._get_text("lineEdit_underlyingHealthCondition"),
        }
