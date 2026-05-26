"""
治疗页拆分模块：导航、阻抗/WS联动、会话确认。
"""

from __future__ import annotations

from typing import Iterable, Optional
from datetime import datetime

from PySide6.QtCore import QObject, QEvent, Qt, QTimer
from PySide6.QtWidgets import QLabel, QPushButton

from ui.dialogs.tips_dialog import TipsDialog
from ui.core.utils import get_ui_attr, safe_call, safe_connect
from ui.widgets.eval_wave_widget import EvalWaveKind, EvalWaveWidget
from ui.widgets.slider_widget import SliderWidget
from ui.widgets.threshold_stepper_widget import ThresholdStepperWidget
from service.business.hardware.dd_ack_retry import DdAckRetrySender


class TreatWsBridge:
    def __init__(self, host):
        self._host = host
        self.ui = host.ui
        self._logger = host._logger

    def send_impedance_close(self) -> None:
        if not self._host.ws_service:
            return
        try:
            self._host.ws_service.send_notification(
                "main.set_ImpedanceMode",
                {"open_or_close": "close"},
            )
        except Exception:
            self._logger.exception("发送阻抗关闭通知失败")

    def send_impedance_open(self) -> None:
        if not self._host.ws_service:
            return
        try:
            self._host.ws_service.send_notification(
                "main.set_ImpedanceMode",
                {"open_or_close": "open"},
            )
        except Exception:
            self._logger.exception("发送阻抗开启通知失败")

    def close_impedance_mode(self) -> None:
        try:
            self._host.impedance_ctrl.stop_impedance()
        except Exception:
            self._logger.exception("关闭阻抗检测失败")
        self.send_impedance_close()


class TreatSessionGuard:
    def __init__(self, host):
        self._host = host

    def confirm_exit_if_session_active(self) -> bool:
        if not self._host.session_app or not self._host.session_app.has_active_session():
            return True
        parent = self._host.ui.window() if self._host.ui else None
        if not TipsDialog.show_confirm(parent, "本次治疗还未完成，确认退出？"):
            return False
        self._host.session_app.end_session("manual_exit")
        return True


class _SliderHostResizeFilter(QObject):
    """宿主 widget 尺寸变化时，让内嵌 SliderWidget 始终铺满。"""

    def __init__(self, slider: SliderWidget, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._slider = slider

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            self._slider.setGeometry(obj.rect())
        return False


class _Threshold1GuardFilter(QObject):
    """未点击「开始测试」时，拦截对阈值1滚轮/滑杆的操作并提示。"""

    def __init__(self, nav: "TreatNavigation", parent=None):
        super().__init__(parent)
        self._nav = nav

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and getattr(self._nav, "_neu_step", 0) == 0:
            TipsDialog.show_tips(self._nav.ui.window() if self._nav.ui else None, "请先点击“开始测试”按钮")
            return True
        return False


# 评估页 tab_6：阈值一 / 阈值二 列内控件（调节其一列时另一列全部置灰）
_THRESHOLD1_COLUMN_WIDGETS = (
    "label_eval_threshold1_title",
    "label_eval_tip1",
    "label_eval_hint1",
    "widget_threshold1_wheel",
    "widget_threshold1_slider",
    "label_eval_t1_min",
    "label_eval_t1_max",
    "label_eval_wave_square_title",
    "label_squarewave",
    "label_6",
)
_EVAL_TITLE_STYLE_ACTIVE = "color: #333333;"
_EVAL_TITLE_STYLE_DISABLED = "color: #C8CCD3;"
_EVAL_ACCENT_STYLE_ACTIVE = "color: rgb(88, 122, 244);"
_EVAL_ACCENT_STYLE_DISABLED = "color: #C8CCD3;"
_EVAL_HINT_STYLE_ACTIVE = "color: #666666;"
_EVAL_HINT_STYLE_DISABLED = "color: #C8CCD3;"
_EVAL_WAVE_TITLE_STYLE_DISABLED = "color: #C8CCD3;"
_EVAL_WAVE_LABEL_BG_ACTIVE = "background-color: rgb(221, 221, 221);"
_EVAL_WAVE_LABEL_BG_DISABLED = "background-color: #ECECEC;"
_EVAL_HOST_STYLE_TRANSPARENT = "background-color: transparent;"
_EVAL_WHEEL_HOST_STYLE_DISABLED = "background-color: #ECECEC; border-radius: 6px;"
_THRESHOLD1_BEGIN_BTN_STYLE_INITIAL = (
    "QPushButton {"
    "    background-color: #789EFF;"
    "    color: white;"
    "    border-radius: 10px;"
    "    border: none;"
    "}"
)
_THRESHOLD1_BEGIN_BTN_STYLE_STEP1 = (
    "QPushButton {"
    "    background-color: #F48438;"
    "    color: white;"
    "    border-radius: 10px;"
    "    border: none;"
    "}"
)
_THRESHOLD1_BEGIN_BTN_STYLE_DISABLED = (
    "QPushButton {"
    "    background-color: #E5E7EB;"
    "    color: #C8CCD3;"
    "    border-radius: 10px;"
    "    border: none;"
    "}"
)
_THRESHOLD2_COMPLETE_BTN_STYLE_ACTIVE = (
    "QPushButton {"
    "    background-color: #789EFF;"
    "    color: white;"
    "    border-radius: 10px;"
    "    border: none;"
    "}"
)
_THRESHOLD2_COMPLETE_BTN_STYLE_DISABLED = (
    "QPushButton {"
    "    background-color: #E5E7EB;"
    "    color: #C8CCD3;"
    "    border-radius: 10px;"
    "    border: none;"
    "}"
)

_THRESHOLD2_COLUMN_WIDGETS = (
    "label_eval_threshold2_title",
    "label_eval_tip2",
    "label_eval_hint2",
    "widget_threshold2_wheel",
    "widget_threshold2_slider",
    "label_eval_t2_min",
    "label_eval_t2_max",
    "label_eval_t1_max_2",
    "label_eval_wave_sharp_title",
    "label_sharpwave",
    "label_20",
)


class TreatNavigation:
    # 阈值1 滚轮/滑杆：0-250，步长1
    THRESHOLD1_MIN = 0
    THRESHOLD1_MAX = 250
    # 阈值2 滚轮/滑杆：0-500，步长2
    THRESHOLD2_MIN = 0
    THRESHOLD2_MAX = 500
    THRESHOLD2_STEP = 2
    ACK_TIMEOUT_SEC = 0.5
    MAX_RESENDS = 5

    def __init__(self, host):
        self._host = host
        self.ui = host.ui
        self._logger = host._logger
        # 神经评估步骤：0=初始，1=调节阈值1，2=调节阈值2，3=评估完成（两列置灰，仅重置回初始）
        self._neu_step = 0
        self._threshold1_wheel: Optional[ThresholdStepperWidget] = None
        self._threshold2_wheel: Optional[ThresholdStepperWidget] = None
        self._threshold1_slider: Optional[SliderWidget] = None
        self._threshold2_slider: Optional[SliderWidget] = None
        self._neu_mask: Optional[QLabel] = None
        self._wave_square: Optional[EvalWaveWidget] = None
        self._wave_sharp: Optional[EvalWaveWidget] = None
        # 滚轮防抖：仅在停止在某个值后发送指令，调整过程中不发送
    def bind(self) -> None:
        return_btn = get_ui_attr(self.ui, "pushButton_return")
        safe_connect(self._logger, getattr(return_btn, "clicked", None), self.on_preprocess_return)
        next_btn = get_ui_attr(self.ui, "pushButton_next")
        safe_connect(self._logger, getattr(next_btn, "clicked", None), self.on_preprocess_next)
        threshold1_begin_btn = get_ui_attr(self.ui, "pushButton_threshold1_begin")
        safe_connect(self._logger, getattr(threshold1_begin_btn, "clicked", None), self.on_threshold1_begin_clicked)
        neu_reset_btn = get_ui_attr(self.ui, "pushButton_neureset")
        safe_connect(self._logger, getattr(neu_reset_btn, "clicked", None), self.on_neu_reset_clicked)
        neu_next_btn = get_ui_attr(self.ui, "pushButton_neunext")
        safe_connect(self._logger, getattr(neu_next_btn, "clicked", None), self.on_neu_next_clicked)
        threshold2_complete_btn = self._get_threshold2_complete_button()
        safe_connect(self._logger, getattr(threshold2_complete_btn, "clicked", None), self.on_threshold2_complete_clicked)

        self._init_threshold1_wheel()
        self._init_threshold2_wheel()
        self._init_threshold1_slider()
        self._init_threshold2_slider()
        self._bind_threshold_wheel_signals()
        # 未开始时操作阈值1滚轮/滑杆则提示
        _guard = _Threshold1GuardFilter(self, self.ui)
        if self._threshold1_wheel is not None:
            self._threshold1_wheel.installEventFilter(_guard)
        if self._threshold1_slider is not None:
            self._threshold1_slider.installEventFilter(_guard)

        main_tab = get_ui_attr(self.ui, "tabWidget_main")
        safe_connect(self._logger, getattr(main_tab, "currentChanged", None), self.on_main_tab_changed)
        sub_tab = get_ui_attr(self.ui, "tabWidget_2")
        safe_connect(self._logger, getattr(sub_tab, "currentChanged", None), self.on_sub_tab_changed)

        self._init_neu_mask()
        self._init_eval_waves()

    def _init_neu_mask(self) -> None:
        if self._neu_mask is not None:
            return
        label_48 = get_ui_attr(self.ui, "label_48")
        if label_48 is None:
            return
        parent = label_48.parent()
        if parent is None:
            return
        mask = QLabel(parent)
        mask.setGeometry(label_48.geometry())
        mask.setStyleSheet(
            "background-color: rgba(194, 199, 206, 128); border-radius: 25px;"
        )
        mask.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        mask.hide()
        self._neu_mask = mask

    def _show_neu_mask_over(self, label_name: str) -> None:
        if self._neu_mask is None:
            return
        target = get_ui_attr(self.ui, label_name)
        if target is None:
            self._neu_mask.hide()
            return
        parent = target.parent()
        if parent is not None and parent is not self._neu_mask.parent():
            self._neu_mask.setParent(parent)
        self._neu_mask.setGeometry(target.geometry())
        self._neu_mask.raise_()
        self._neu_mask.show()

    def _hide_neu_mask(self) -> None:
        if self._neu_mask is not None:
            self._neu_mask.hide()

    def _mount_eval_wave(
        self, label_name: str, kind: EvalWaveKind, bg_color: str
    ) -> Optional[EvalWaveWidget]:
        """用自绘波形控件替换 QLabel+GIF，波形铺满 label 区域。"""
        label = get_ui_attr(self.ui, label_name)
        if label is None:
            return None
        parent = label.parentWidget()
        if parent is None:
            return None
        wave = EvalWaveWidget(kind, parent)
        wave.setObjectName(f"{label_name}_draw")
        wave.setGeometry(label.geometry())
        wave.set_background_color(bg_color)
        label.hide()
        wave.show()
        wave.raise_()
        return wave

    def _sync_eval_wave_geometry(self) -> None:
        """label 布局变化后，同步波形控件尺寸以铺满；尖波与方波显示区域一致。"""
        square_label = get_ui_attr(self.ui, "label_squarewave")
        sharp_label = get_ui_attr(self.ui, "label_sharpwave")
        wave_bg = "background-color: rgb(221, 221, 221);"
        if square_label is not None:
            square_label.setStyleSheet(wave_bg)
        if sharp_label is not None and square_label is not None:
            sq_geo = square_label.geometry()
            sh_geo = sharp_label.geometry()
            sharp_label.setStyleSheet(wave_bg)
            sharp_label.setGeometry(sh_geo.x(), sh_geo.y(), sq_geo.width(), sq_geo.height())

        pairs = (
            ("label_squarewave", self._wave_square),
            ("label_sharpwave", self._wave_sharp),
        )
        for label_name, wave in pairs:
            if wave is None:
                continue
            label = get_ui_attr(self.ui, label_name)
            if label is not None:
                wave.setGeometry(label.geometry())
                wave.set_background_color("#DDDDDD")
                wave.raise_()

    def _init_eval_waves(self) -> None:
        """方波/尖波自绘控件，铺满 label_squarewave / label_sharpwave 区域。"""
        if self._wave_square is None:
            self._wave_square = self._mount_eval_wave(
                "label_squarewave", EvalWaveKind.SQUARE, "#DDDDDD"
            )
        if self._wave_sharp is None:
            self._wave_sharp = self._mount_eval_wave(
                "label_sharpwave", EvalWaveKind.SHARP, "#DDDDDD"
            )

    def _stop_eval_waves(self) -> None:
        """停止波形滚动动画，保持静态铺满显示。"""
        if self._wave_square is not None:
            self._wave_square.stop_animation()
        if self._wave_sharp is not None:
            self._wave_sharp.stop_animation()

    def _ensure_eval_waves_on_enter_tab6(self) -> None:
        """进入 tab_6 时确保波形控件已创建并铺满、静态显示。"""
        if self._wave_square is None or self._wave_sharp is None:
            self._init_eval_waves()
        self._sync_eval_wave_geometry()
        self._stop_eval_waves()

    def _init_threshold1_wheel(self) -> None:
        """在 widget_threshold1_wheel 中创建「按钮 + 数值」加减器，范围 0-250 步长 1。"""
        if self._threshold1_wheel is not None:
            return
        host = get_ui_attr(self.ui, "widget_threshold1_wheel")
        if host is None:
            return
        host.setCursor(Qt.CursorShape.PointingHandCursor)
        stepper = ThresholdStepperWidget(host)
        stepper.setGeometry(host.rect())
        stepper.set_range(self.THRESHOLD1_MIN, self.THRESHOLD1_MAX)
        stepper.set_single_step(1)
        stepper.set_value(0, emit_index_changed=False)
        self._threshold1_wheel = stepper
        # 阈值1：保持宿主可用，未开始时由 _Threshold1GuardFilter 拦截

    def _init_threshold2_wheel(self) -> None:
        """在 widget_threshold2_wheel 中创建「按钮 + 数值」加减器，范围 0-500 步长 2，初始值 2。"""
        if self._threshold2_wheel is not None:
            return
        host = get_ui_attr(self.ui, "widget_threshold2_wheel")
        if host is None:
            return
        host.setCursor(Qt.CursorShape.PointingHandCursor)
        stepper = ThresholdStepperWidget(host)
        stepper.setGeometry(host.rect())
        stepper.set_range(self.THRESHOLD2_MIN, self.THRESHOLD2_MAX)
        stepper.set_single_step(self.THRESHOLD2_STEP)
        stepper.set_value(2, emit_index_changed=False)
        self._threshold2_wheel = stepper
        host.setEnabled(False)

    def _init_threshold1_slider(self) -> None:
        """在 widget_threshold1_slider 中创建滑杆，范围 0-250，与滚轮双向同步。"""
        if self._threshold1_slider is not None:
            return
        host = get_ui_attr(self.ui, "widget_threshold1_slider")
        if host is None:
            return
        host.setCursor(Qt.CursorShape.PointingHandCursor)
        slider = SliderWidget(host)
        slider.setGeometry(host.rect())
        host.installEventFilter(_SliderHostResizeFilter(slider, host))
        slider.set_range(self.THRESHOLD1_MIN, self.THRESHOLD1_MAX)
        slider.set_value(0)
        stepper = self._threshold1_wheel
        if stepper is not None:
            def on_slider_value_changed(v: int) -> None:
                if stepper.value() != v:
                    stepper.set_value(v)

            def on_stepper_value_changed(v: int) -> None:
                if slider.value() != v:
                    slider.set_value(v)

            slider.valueChanged.connect(on_slider_value_changed)
            stepper.valueChanged.connect(on_stepper_value_changed)
        self._threshold1_slider = slider

    def _init_threshold2_slider(self) -> None:
        """在 widget_threshold2_slider 中创建滑杆，范围 0-500 步长 2，与滚轮双向同步，初始值 2。"""
        if self._threshold2_slider is not None:
            return
        host = get_ui_attr(self.ui, "widget_threshold2_slider")
        if host is None:
            return
        host.setCursor(Qt.CursorShape.PointingHandCursor)
        slider = SliderWidget(host)
        slider.setGeometry(host.rect())
        host.installEventFilter(_SliderHostResizeFilter(slider, host))
        threshold2_count = (self.THRESHOLD2_MAX - self.THRESHOLD2_MIN) // self.THRESHOLD2_STEP + 1
        slider.set_range(0, threshold2_count - 1)
        slider.set_value(1)
        stepper = self._threshold2_wheel
        if stepper is not None:
            def on_slider_value_changed(index: int) -> None:
                value = index * self.THRESHOLD2_STEP
                if stepper.value() != value:
                    stepper.set_value(value)

            def on_stepper_value_changed(value: int) -> None:
                index = value // self.THRESHOLD2_STEP
                if slider.value() != index:
                    slider.set_value(index)

            slider.valueChanged.connect(on_slider_value_changed)
            stepper.valueChanged.connect(on_stepper_value_changed)
        self._threshold2_slider = slider
        host.setEnabled(False)

    def _bind_threshold_wheel_signals(self) -> None:
        """加减器 currentIndexChanged 已在控件内 1s 节流，此处直接触发下发。"""
        if self._threshold1_wheel is not None:
            self._threshold1_wheel.currentIndexChanged.connect(self._on_threshold1_commit)

        if self._threshold2_wheel is not None:
            self._threshold2_wheel.currentIndexChanged.connect(self._on_threshold2_commit)

    def _on_threshold1_commit(self, _index: int = 0) -> None:
        self.on_threshold1_value_changed(0)

    def _on_threshold2_commit(self, _index: int = 0) -> None:
        self.on_threshold2_value_changed(0)

    def enter_preprocess_page(self) -> None:
        if hasattr(self._host.stim_ctrl, "reset_stimulus_grades_local"):
            self._host.stim_ctrl.reset_stimulus_grades_local()
        else:
            self._host.stim_ctrl.reset_stimulus_grades()
        self._reset_neu_threshold_spinboxes()
        radio_checksafe = get_ui_attr(self.ui, "radioButton_checksafe")
        if radio_checksafe is not None:
            safe_call(self._logger, getattr(radio_checksafe, "setChecked", None), False)
        main_tab = get_ui_attr(self.ui, "tabWidget_main")
        if main_tab:
            main_tab.setCurrentIndex(1)
        sub_tab = get_ui_attr(self.ui, "tabWidget_2")
        if sub_tab:
            sub_tab.setCurrentIndex(0)
        self.sync_preprocess_title_by_sub_tab()
        self._host.stim_ctrl.on_enter()

    def enter_stim_page(self) -> None:
        """进入电刺激页（tab_3），范式按钮点击后直接进入。"""
        if hasattr(self._host.stim_ctrl, "reset_stimulus_grades_local"):
            self._host.stim_ctrl.reset_stimulus_grades_local()
        else:
            self._host.stim_ctrl.reset_stimulus_grades()
        self._reset_neu_threshold_spinboxes()
        radio_checksafe = get_ui_attr(self.ui, "radioButton_checksafe")
        if radio_checksafe is not None:
            safe_call(self._logger, getattr(radio_checksafe, "setChecked", None), False)
        main_tab = get_ui_attr(self.ui, "tabWidget_main")
        if main_tab:
            main_tab.setCurrentIndex(1)
        self._set_sub_tab_by_name("tab_3")
        self.sync_preprocess_title_by_sub_tab()
        self._host.stim_ctrl.on_enter()

    def enter_evaluate_page(self) -> None:
        """进入评估页（tab_6），由 pushButton_plan_new 等入口使用。"""
        main_tab = get_ui_attr(self.ui, "tabWidget_main")
        if main_tab:
            main_tab.setCurrentIndex(1)
        self._set_sub_tab_by_name("tab_6")
        self.sync_preprocess_title_by_sub_tab()
        # 延迟到下一事件循环，等 tab_6 完成显示后再初始化静态图，否则首次进入看不到
        QTimer.singleShot(0, self._ensure_eval_waves_on_enter_tab6)

    def _get_grade_from_label(self, name: str) -> int:
        label = get_ui_attr(self.ui, name)
        if label is None:
            return 0
        try:
            grade_str = (label.text() or "").replace("级", "").strip()
            return int(grade_str) if grade_str else 0
        except (ValueError, AttributeError):
            return 0

    def on_preprocess_next(self) -> None:
        sub_tab = get_ui_attr(self.ui, "tabWidget_2")
        if self._get_current_sub_tab_name() == "tab_3":
            right_grade = self._get_grade_from_label("label_stim_intensity")
            if right_grade == 0:
                TipsDialog.show_tips(self.ui.window() if self.ui else None, "请进行电刺激强度测试")
                return
        if not self._host.stim_ctrl.ensure_stopped_before_next():
            return
        self._set_sub_tab_by_name("tab_4")
        self.sync_preprocess_title_by_sub_tab()
        self._host.impedance_ctrl.on_enter()

    def on_neu_next_clicked(self) -> None:
        threshold1 = self._get_threshold1_value()
        # 阈值2：入库时需要记录滚轮显示的实际值（0-500，步长 2）
        if self._threshold2_wheel is not None:
            threshold2 = self._threshold2_wheel.value()
        else:
            threshold2 = self._get_threshold2_value() * self.THRESHOLD2_STEP
        if threshold1 == 0 and threshold2 == 0:
            if not TipsDialog.show_confirm(self.ui.window() if self.ui else None, "未进行评估是否返回"):
                return
        if not self._save_neu_eval_to_db():
            return
        on_completed = getattr(self._host, "_on_evaluation_completed", None)
        if callable(on_completed):
            try:
                on_completed()
            except Exception:
                self._logger.exception("评估完成后刷新方案表失败")
        self._navigate_to_plan_tab()

    def _navigate_to_plan_tab(self) -> None:
        main_tab = get_ui_attr(self.ui, "tabWidget_main")
        if main_tab is not None:
            main_tab.setCurrentIndex(0)
        tab_widget = get_ui_attr(self.ui, "tabWidget")
        tab_plan = get_ui_attr(self.ui, "tab_plan")
        if tab_widget is not None and tab_plan is not None:
            idx = tab_widget.indexOf(tab_plan)
            if idx >= 0:
                tab_widget.setCurrentIndex(idx)

    def on_threshold1_begin_clicked(self) -> None:
        """融合「启动」与「阈值1完成」：初始态点击=启动，step1 点击=阈值1完成。停止请用「重置」。"""
        if self._neu_step == 0:
            alpha_label = get_ui_attr(self.ui, "label_alpha")
            evalresult_label = get_ui_attr(self.ui, "label_evalresult")
            if alpha_label is not None:
                alpha_label.setText("")
            if evalresult_label is not None:
                evalresult_label.setText("")
            # 点击开始测试时，高亮按钮背景为 #F48438
            begin_btn = get_ui_attr(self.ui, "pushButton_threshold1_begin")
            if begin_btn is not None:
                begin_btn.setStyleSheet(_THRESHOLD1_BEGIN_BTN_STYLE_STEP1)
            self._reset_neu_threshold_spinboxes()
            self._send_neu_eval_frame()
            self._send_neu_start_command_frame()
            self._set_neu_tab_eval_step1_state()
            self._stop_eval_waves()
            if self._wave_square is not None:
                self._wave_square.start_animation()
            return
        if self._neu_step == 1:
            self._send_neu_threshold2_realtime_frame()
            self._set_neu_tab_eval_step2_state()
            if self._wave_square is not None:
                self._wave_square.stop_animation()
            if self._wave_sharp is not None:
                self._wave_sharp.start_animation()

    def on_neu_reset_clicked(self) -> None:
        """重置：停止评估、清空数值与结果，恢复为初始态（仅「开始测试」可点）。"""
        alpha_label = get_ui_attr(self.ui, "label_alpha")
        evalresult_label = get_ui_attr(self.ui, "label_evalresult")
        if alpha_label is not None:
            alpha_label.setText("")
        if evalresult_label is not None:
            evalresult_label.setText("")
        self._send_neu_stop_command_frame()
        self._reset_neu_threshold_spinboxes()
        self._set_neu_tab_initial_state()

    def on_threshold2_complete_clicked(self) -> None:
        self._update_neu_alpha_eval_result()
        self._send_neu_stop_command_frame()
        self._set_neu_tab_eval_completed_state()
        self._stop_eval_waves()

    def on_threshold1_value_changed(self, _value: int) -> None:
        if self._neu_step == 1:
            self._send_neu_threshold1_realtime_frame()

    def on_threshold2_value_changed(self, _value: int) -> None:
        if self._neu_step == 2:
            self._send_neu_threshold2_realtime_frame()

    def on_preprocess_return(self) -> None:
        current_tab_name = self._get_current_sub_tab_name()
        if current_tab_name == "tab_6":
            if self._neu_step > 0:
                if not TipsDialog.show_confirm(
                    self.ui.window() if self.ui else None,
                    "未保存评估结果，是否返回？",
                ):
                    return
            self._send_neu_stop_command_frame()
            self._stop_eval_waves()
            self._navigate_to_plan_tab()
            return
        if current_tab_name == "tab_5":
            try:
                if not self._host.training_main_ctrl.is_paused_state():
                    TipsDialog.show_tips(self.ui.window() if self.ui else None, "请先暂停")
                    return
            except Exception:
                self._logger.exception("检查训练暂停状态失败")
            self._host._ws_bridge.send_impedance_open()
            self._set_sub_tab_by_name("tab_4")
            self.sync_preprocess_title_by_sub_tab()
            self._host.training_sub_ctrl.show_welcome_tab()
            return
        if current_tab_name == "tab_4":
            self._host._ws_bridge.close_impedance_mode()
            self._set_sub_tab_by_name("tab_3")
            self.sync_preprocess_title_by_sub_tab()
            return
        if current_tab_name == "tab_3":
            try:
                if bool(getattr(self._host.stim_ctrl, "is_test_running", False)):
                    TipsDialog.show_tips(self.ui.window() if self.ui else None, "请先点击“停止按钮”按钮，才能返回上一步")
                    return
            except Exception:
                self._logger.exception("检查电刺激测试运行状态失败")
            # 从电刺激页返回：交给会话守卫弹出“本次治疗未结束”提示
            if not self._host._session_guard.confirm_exit_if_session_active():
                return
            if callable(self._host._on_return_home):
                self._host._on_return_home()
            self._host.stim_ctrl.on_exit()
            return

        if not self._host._session_guard.confirm_exit_if_session_active():
            return
        if callable(self._host._on_return_home):
            self._host._on_return_home()
        self._host.stim_ctrl.on_exit()

    def on_main_tab_changed(self, index: int) -> None:
        if index == 0:
            sub_tab = get_ui_attr(self.ui, "tabWidget_2")
            if sub_tab:
                sub_tab.setCurrentIndex(0)
            self.sync_preprocess_title_by_sub_tab()

    def on_sub_tab_changed(self, index: int) -> None:
        # 子页标题按对象名同步，避免新增/调整 tab 顺序时出现错图
        self.sync_preprocess_title_by_sub_tab()
        if self._get_current_sub_tab_name() == "tab_5":
            try:
                self._host.training_main_ctrl.on_enter()
            except Exception:
                self._logger.exception("进入训练主屏失败")
        elif self._get_current_sub_tab_name() == "tab_6":
            QTimer.singleShot(0, self._ensure_eval_waves_on_enter_tab6)

    def _get_current_sub_tab_name(self) -> str:
        sub_tab = get_ui_attr(self.ui, "tabWidget_2")
        if sub_tab is None:
            return ""
        try:
            current = sub_tab.currentWidget()
            return current.objectName() if current is not None else ""
        except Exception:
            return ""

    def _set_sub_tab_by_name(self, tab_name: str) -> bool:
        sub_tab = get_ui_attr(self.ui, "tabWidget_2")
        if sub_tab is None:
            return False
        target_tab = get_ui_attr(self.ui, tab_name)
        if target_tab is None:
            return False
        index = sub_tab.indexOf(target_tab)
        if index < 0:
            return False
        sub_tab.setCurrentIndex(index)
        return True

    def _get_threshold1_value(self) -> int:
        """从阈值1滚轮读取当前数值（0-250）。"""
        if self._threshold1_wheel is None:
            return 0
        return self._threshold1_wheel.current_index()

    def _get_threshold2_value(self) -> int:
        """从阈值 2 滚轮读取当前数值（0-500，步长 2），映射到发送值 0-250（00-FA）。
            
        映射逻辑：滚轮值 / 2 = 发送值
        例如：滚轮显示 500 → 发送 250 (0xFA)
             滚轮显示 250 → 发送 125 (0x7D)
             滚轮显示   2 → 发送   1 (0x01)
        """
        if self._threshold2_wheel is None:
            return 1
        return self._threshold2_wheel.value() // self.THRESHOLD2_STEP

    def _save_neu_eval_to_db(self) -> bool:
        """
        将评估结果写入 EvaluationManager 表（EvaluationID 累加）。
        """
        scheme_app = getattr(self._host, "scheme_app", None)
        if scheme_app is None:
            return False

        # 当前患者 ID
        patient = getattr(self._host, "_current_patient", None)
        patient_id: Optional[str] = None
        try:
            if patient is not None and hasattr(self._host, "_extract_patient_id"):
                patient_id = self._host._extract_patient_id(patient)  # type: ignore[attr-defined]
        except Exception:
            patient_id = None
        if not patient_id:
            # 兜底：从 session_app 读取
            session_app = getattr(self._host, "session_app", None)
            if session_app is not None and hasattr(session_app, "get_current_patient_id"):
                try:
                    patient_id = session_app.get_current_patient_id()
                except Exception:
                    patient_id = None
        if not patient_id:
            return False

        threshold1 = self._get_threshold1_value()
        # 阈值2：入库时记录滚轮上的实际显示值（0-500，步长 2）
        if self._threshold2_wheel is not None:
            threshold2 = self._threshold2_wheel.value()
        else:
            threshold2 = self._get_threshold2_value() * self.THRESHOLD2_STEP
        alpha_label = get_ui_attr(self.ui, "label_alpha")
        alpha = (alpha_label.text() if alpha_label is not None else "") or ""
        evalresult_label = get_ui_attr(self.ui, "label_evalresult")
        eval_result = (evalresult_label.text() if evalresult_label is not None else "") or ""
        evaluation_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            return bool(
                scheme_app.add_evaluation_record(
                    patient_id=patient_id,
                    threshold1=threshold1,
                    threshold2=threshold2,
                    alpha=alpha,
                    evaluation_time=evaluation_time,
                    evaluation_result=eval_result,
                )
            )
        except Exception:
            self._logger.exception("保存评估结果到 EvaluationManager 失败")
            return False

    def _save_neu_eval_to_session(self) -> None:
        session_app = getattr(self._host, "session_app", None)
        if session_app is None:
            return
        patient_id = None
        try:
            patient_id = session_app.get_current_patient_id()
        except Exception:
            patient_id = None
        if not patient_id:
            return
        alpha_label = get_ui_attr(self.ui, "label_alpha")
        evalresult_label = get_ui_attr(self.ui, "label_evalresult")
        payload = {
            "threshold1": self._get_threshold1_value(),
            "threshold2": self._get_threshold2_value(),
            "alpha": (alpha_label.text() if alpha_label is not None else "") or "",
            "evalresult": (evalresult_label.text() if evalresult_label is not None else "") or "",
        }
        try:
            if hasattr(session_app, "save_paradigm_params"):
                session_app.save_paradigm_params(patient_id, payload)
        except Exception:
            self._logger.exception("保存神经评估参数到当前会话失败")

    def _checksum_16(self, first_11_bytes: list[int]) -> tuple[int, int]:
        checksum = sum(int(b) & 0xFF for b in first_11_bytes) & 0xFFFF
        return (checksum >> 8) & 0xFF, checksum & 0xFF

    def _send_neu_eval_frame(self) -> bool:
        threshold1 = self._get_threshold1_value()
        packet = self._build_neu_eval_packet(eval_type=0x01, threshold=threshold1)
        return self._send_raw_serial_packet(packet, "神经评估帧")

    def _send_neu_threshold1_realtime_frame(self) -> bool:
        threshold1 = self._get_threshold1_value()
        packet = self._build_neu_eval_packet(eval_type=0x01, threshold=threshold1)
        self._logger.info("阈值1变化并发送评估帧: threshold1=%d(0x%02X)", threshold1, int(threshold1) & 0xFF)
        return self._send_raw_serial_packet(packet, "阈值1实时评估帧")

    def _send_neu_threshold2_realtime_frame(self) -> bool:
        threshold2 = self._get_threshold2_value()
        packet = self._build_neu_eval_packet(eval_type=0x02, threshold=threshold2)
        self._logger.info("阈值2变化并发送评估帧: threshold2=%d(0x%02X)", threshold2, int(threshold2) & 0xFF)
        return self._send_raw_serial_packet(packet, "阈值2实时评估帧")

    def _send_neu_entry_eval_frames(self) -> None:
        packet1 = self._build_neu_eval_packet(eval_type=0x01, threshold=0)
        packet2 = self._build_neu_eval_packet(eval_type=0x02, threshold=0)
        self._send_raw_serial_packet(packet1, "进入范式评估帧-阈值1")
        self._send_raw_serial_packet(packet2, "进入范式评估帧-阈值2")

    def send_neu_reset_eval_frames(self) -> None:
        """用于返回主页/程序退出的固定复位帧（AE01/AE02）。"""
        self._send_neu_entry_eval_frames()

    def _build_neu_eval_packet(self, eval_type: int, threshold: int) -> bytes:
        eval_type = max(0, min(255, int(eval_type)))
        threshold = max(0, min(255, int(threshold)))
        first_11 = [0x55, 0xAA, 0x0D, 0x00, 0xAE, eval_type, threshold, 0x00, 0x00, 0x00, 0x00]
        c1, c2 = self._checksum_16(first_11)
        return bytes(first_11 + [c1, c2])

    def _reset_neu_threshold_spinboxes(self) -> None:
        """重置阈值1/2 滚轮与滑杆（阈值1 归 0，阈值2 归 0）。"""
        if self._threshold1_wheel is not None:
            self._threshold1_wheel.cancel_pending_index_changed()
            self._threshold1_wheel.set_value(0, emit_index_changed=False)
        if self._threshold2_wheel is not None:
            self._threshold2_wheel.cancel_pending_index_changed()
            self._threshold2_wheel.set_value(0, emit_index_changed=False)
        if self._threshold1_slider is not None:
            self._threshold1_slider.set_value(0)
        if self._threshold2_slider is not None:
            self._threshold2_slider.set_value(0)

    def _send_neu_start_command_frame(self) -> bool:
        stim_app = getattr(self._host.stim_ctrl, "stim_app", None)
        if stim_app is None:
            self._logger.warning("发送开始命令失败：stim_app 不可用")
            return False
        try:
            service = getattr(stim_app, "service", None)
            if service and hasattr(service, "start_treatment"):
                ok = self._send_with_dd_retry(lambda: bool(service.start_treatment()), "开始命令帧")
                if not ok:
                    self._logger.warning("发送开始命令帧失败")
                return ok
            ok = self._send_with_dd_retry(
                lambda: bool(stim_app.start_treatment_channel("left")),
                "开始命令帧（回退通道命令）",
            )
            if not ok:
                self._logger.warning("发送开始命令帧失败（回退通道命令）")
            return ok
        except Exception:
            self._logger.exception("发送开始命令帧异常")
            return False

    def _send_neu_stop_command_frame(self) -> bool:
        stim_app = getattr(self._host.stim_ctrl, "stim_app", None)
        if stim_app is None:
            self._logger.warning("发送停止命令失败：stim_app 不可用")
            return False
        try:
            service = getattr(stim_app, "service", None)
            if service and hasattr(service, "stop_treatment"):
                ok = self._send_with_dd_retry(lambda: bool(service.stop_treatment()), "停止命令帧")
                if not ok:
                    self._logger.warning("发送停止命令帧失败")
                return ok
            ok = self._send_with_dd_retry(lambda: bool(stim_app.stop_dual()), "停止命令帧（回退 stop_dual）")
            if not ok:
                self._logger.warning("发送停止命令帧失败（回退 stop_dual）")
            return ok
        except Exception:
            self._logger.exception("发送停止命令帧异常")
            return False

    def _send_raw_serial_packet(self, packet: bytes, desc: str) -> bool:
        stim_app = getattr(self._host.stim_ctrl, "stim_app", None)
        service = getattr(stim_app, "service", None) if stim_app else None
        serial_hw = getattr(service, "serial_hw", None) if service else None
        if serial_hw is None:
            self._logger.warning(f"发送{desc}失败：serial_hw 不可用")
            return False
        try:
            ok = self._send_with_dd_retry(lambda: bool(serial_hw.send_data(packet)), desc)
            if not ok:
                self._logger.warning(f"发送{desc}失败")
            return ok
        except Exception:
            self._logger.exception(f"发送{desc}异常")
            return False

    def _send_with_dd_retry(self, send_callable, desc: str) -> bool:
        service = getattr(getattr(self._host, "stim_ctrl", None), "stim_app", None)
        service = getattr(service, "service", None) if service else None
        serial_hw = getattr(service, "serial_hw", None) if service else None
        return DdAckRetrySender.send_with_retry(
            serial_hw=serial_hw,
            send_callable=lambda: bool(send_callable()),
            logger=self._logger,
            desc=desc,
            timeout_sec=self.ACK_TIMEOUT_SEC,
            max_resends=self.MAX_RESENDS,
        )

    def _update_neu_alpha_eval_result(self) -> None:
        # 阈值1 直接使用滚轮当前真实值（0-250）
        threshold1 = self._get_threshold1_value()

        # 阈值2 使用滚轮「实际显示值」（0-500，步长 2）参与 alpha 计算，
        # 而不是用于串口发送的映射值。
        if self._threshold2_wheel is not None:
            threshold2_real = self._threshold2_wheel.value()
        else:
            threshold2_real = self._get_threshold2_value() * self.THRESHOLD2_STEP

        alpha = (float(threshold2_real) / float(threshold1)) if threshold1 > 0 else 0.0

        alpha_label = get_ui_attr(self.ui, "label_alpha")
        if alpha_label is not None:
            alpha_label.setText(f"{alpha:.2f}")

        evalresult_label = get_ui_attr(self.ui, "label_evalresult")
        if evalresult_label is None:
            return
        if alpha < 1.5:
            evalresult_label.setText("重度失神经（α<1.5）")
        elif alpha <= 2:
            evalresult_label.setText("轻度失神经（1.5<=α<=2）")
        else:
            evalresult_label.setText("正常（α>2）")

    def _get_threshold2_complete_button(self):
        return get_ui_attr(self.ui, "pushButton_threshold2_complete") or get_ui_attr(
            self.ui, "pushButton__threshold2_complete"
        )

    def _apply_eval_widget_visual(self, name: str, enabled: bool) -> None:
        widget = get_ui_attr(self.ui, name)
        if widget is None:
            return
        widget.setEnabled(enabled)
        if name in ("label_eval_threshold1_title", "label_eval_threshold2_title"):
            widget.setStyleSheet(
                _EVAL_TITLE_STYLE_ACTIVE if enabled else _EVAL_TITLE_STYLE_DISABLED
            )
        elif name in ("label_eval_hint1", "label_eval_hint2"):
            widget.setStyleSheet(
                _EVAL_HINT_STYLE_ACTIVE if enabled else _EVAL_HINT_STYLE_DISABLED
            )
        elif name in (
            "label_eval_t1_min",
            "label_eval_t1_max",
            "label_eval_t2_min",
            "label_eval_t2_max",
            "label_eval_t1_max_2",
        ):
            widget.setStyleSheet(
                _EVAL_ACCENT_STYLE_ACTIVE if enabled else _EVAL_ACCENT_STYLE_DISABLED
            )
        elif name in ("label_eval_wave_square_title", "label_eval_wave_sharp_title"):
            widget.setStyleSheet("" if enabled else _EVAL_WAVE_TITLE_STYLE_DISABLED)
        elif name in ("label_6", "label_20"):
            widget.setStyleSheet(
                "color: #333333;" if enabled else _EVAL_WAVE_TITLE_STYLE_DISABLED
            )
        elif name in ("label_squarewave", "label_sharpwave"):
            widget.setStyleSheet(
                _EVAL_WAVE_LABEL_BG_ACTIVE if enabled else _EVAL_WAVE_LABEL_BG_DISABLED
            )
        elif name == "pushButton__threshold2_complete" and isinstance(widget, QPushButton):
            widget.setStyleSheet(
                _THRESHOLD2_COMPLETE_BTN_STYLE_ACTIVE
                if enabled
                else _THRESHOLD2_COMPLETE_BTN_STYLE_DISABLED
            )

    def _set_widgets_enabled(self, names: Iterable[str], enabled: bool) -> None:
        for name in names:
            self._apply_eval_widget_visual(name, enabled)

    def _set_wheel_host_visual(self, host_name: str, enabled: bool) -> None:
        host = get_ui_attr(self.ui, host_name)
        if host is not None:
            host.setEnabled(enabled)
            host.setStyleSheet(
                _EVAL_HOST_STYLE_TRANSPARENT
                if enabled
                else _EVAL_WHEEL_HOST_STYLE_DISABLED
            )

    def _set_slider_host_enabled(self, host_name: str, enabled: bool) -> None:
        """滑杆宿主仅同步 enabled，背景始终透明（置灰由 SliderWidget 自绘轨道体现）。"""
        host = get_ui_attr(self.ui, host_name)
        if host is not None:
            host.setEnabled(enabled)
            host.setStyleSheet(_EVAL_HOST_STYLE_TRANSPARENT)

    def _set_threshold1_column_enabled(self, enabled: bool) -> None:
        """阈值一列：标题、提示、加减器、滑杆、min/max、方波区等（含置灰配色）。"""
        self._set_widgets_enabled(_THRESHOLD1_COLUMN_WIDGETS, enabled)
        self._set_wheel_host_visual("widget_threshold1_wheel", enabled)
        self._set_slider_host_enabled("widget_threshold1_slider", enabled)
        if self._threshold1_wheel is not None:
            self._threshold1_wheel.setEnabled(enabled)
        if self._threshold1_slider is not None:
            self._threshold1_slider.setEnabled(enabled)
        if self._wave_square is not None:
            self._wave_square.setEnabled(enabled)

    def _set_threshold2_column_enabled(self, enabled: bool) -> None:
        """阈值二列：标题、提示、加减器、滑杆、min/max、尖波区、完成按钮等（含置灰配色）。"""
        self._set_widgets_enabled(_THRESHOLD2_COLUMN_WIDGETS, enabled)
        self._set_wheel_host_visual("widget_threshold2_wheel", enabled)
        self._set_slider_host_enabled("widget_threshold2_slider", enabled)
        complete_btn = self._get_threshold2_complete_button()
        if complete_btn is not None:
            complete_btn.setEnabled(enabled)
            complete_btn.setStyleSheet(
                _THRESHOLD2_COMPLETE_BTN_STYLE_ACTIVE
                if enabled
                else _THRESHOLD2_COMPLETE_BTN_STYLE_DISABLED
            )
        if self._threshold2_wheel is not None:
            self._threshold2_wheel.setEnabled(enabled)
        if self._threshold2_slider is not None:
            self._threshold2_slider.setEnabled(enabled)
        if self._wave_sharp is not None:
            self._wave_sharp.setEnabled(enabled)

    def _set_neu_tab_initial_state(self) -> None:
        self._neu_step = 0
        begin_btn = get_ui_attr(self.ui, "pushButton_threshold1_begin")
        reset_btn = get_ui_attr(self.ui, "pushButton_neureset")
        next_btn = get_ui_attr(self.ui, "pushButton_neunext")
        threshold2_complete_btn = self._get_threshold2_complete_button()
        if begin_btn is not None:
            begin_btn.setEnabled(True)
            begin_btn.setText("开始测试")
            begin_btn.setStyleSheet(_THRESHOLD1_BEGIN_BTN_STYLE_INITIAL)
        if reset_btn is not None:
            reset_btn.setEnabled(False)
        if next_btn is not None:
            next_btn.setEnabled(True)
        self._set_threshold1_column_enabled(True)
        self._set_threshold2_column_enabled(False)
        if threshold2_complete_btn is not None:
            threshold2_complete_btn.setEnabled(False)

        self._stop_eval_waves()
        self._hide_neu_mask()

    def _set_neu_tab_eval_step1_state(self) -> None:
        self._neu_step = 1
        begin_btn = get_ui_attr(self.ui, "pushButton_threshold1_begin")
        reset_btn = get_ui_attr(self.ui, "pushButton_neureset")
        next_btn = get_ui_attr(self.ui, "pushButton_neunext")
        threshold2_complete_btn = self._get_threshold2_complete_button()
        if begin_btn is not None:
            begin_btn.setEnabled(True)
            begin_btn.setText("阈值1完成")
            begin_btn.setStyleSheet(_THRESHOLD1_BEGIN_BTN_STYLE_STEP1)
        if reset_btn is not None:
            reset_btn.setEnabled(True)
        if next_btn is not None:
            next_btn.setEnabled(False)
        self._set_threshold1_column_enabled(True)
        self._set_threshold2_column_enabled(False)
        if threshold2_complete_btn is not None:
            threshold2_complete_btn.setEnabled(False)

        self._hide_neu_mask()

    def _set_neu_tab_eval_step2_state(self) -> None:
        self._neu_step = 2
        begin_btn = get_ui_attr(self.ui, "pushButton_threshold1_begin")
        reset_btn = get_ui_attr(self.ui, "pushButton_neureset")
        next_btn = get_ui_attr(self.ui, "pushButton_neunext")
        threshold2_complete_btn = self._get_threshold2_complete_button()
        if begin_btn is not None:
            begin_btn.setEnabled(False)
            begin_btn.setText("阈值1完成")
            begin_btn.setStyleSheet(_THRESHOLD1_BEGIN_BTN_STYLE_DISABLED)
        if reset_btn is not None:
            reset_btn.setEnabled(True)
        if next_btn is not None:
            next_btn.setEnabled(False)
        self._set_threshold1_column_enabled(False)
        self._set_threshold2_column_enabled(True)
        if threshold2_complete_btn is not None:
            threshold2_complete_btn.setEnabled(True)

        self._hide_neu_mask()

    def _set_neu_tab_eval_completed_state(self) -> None:
        """阈值2 完成：阈值1 保持置灰，阈值2 亦锁定；仅「重置」恢复初始。"""
        self._neu_step = 3
        begin_btn = get_ui_attr(self.ui, "pushButton_threshold1_begin")
        reset_btn = get_ui_attr(self.ui, "pushButton_neureset")
        next_btn = get_ui_attr(self.ui, "pushButton_neunext")
        threshold2_complete_btn = self._get_threshold2_complete_button()
        if begin_btn is not None:
            begin_btn.setEnabled(False)
            begin_btn.setText("开始测试")
            begin_btn.setStyleSheet(_THRESHOLD1_BEGIN_BTN_STYLE_DISABLED)
        if reset_btn is not None:
            reset_btn.setEnabled(True)
        if next_btn is not None:
            next_btn.setEnabled(True)
        if threshold2_complete_btn is not None:
            threshold2_complete_btn.setEnabled(False)
        self._set_threshold1_column_enabled(False)
        self._set_threshold2_column_enabled(False)

        self._hide_neu_mask()

    def sync_preprocess_title_by_sub_tab(self) -> None:
        tab_name = self._get_current_sub_tab_name()

        if tab_name == "tab_6":
            # 每次进入评估页都重置 UI：清空 Alpha/结果、重置滚轮与按钮状态
            alpha_label = get_ui_attr(self.ui, "label_alpha")
            evalresult_label = get_ui_attr(self.ui, "label_evalresult")
            if alpha_label is not None:
                alpha_label.setText("")
            if evalresult_label is not None:
                evalresult_label.setText("")
            self._reset_neu_threshold_spinboxes()
            self._set_neu_tab_initial_state()
