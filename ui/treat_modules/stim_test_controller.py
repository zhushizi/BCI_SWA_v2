from __future__ import annotations

import logging
import time
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QLabel

from ui.dialogs.tips_dialog import TipsDialog
from ui.widgets.circle_level_widget import CircleLevelWidget
from ui.widgets.wheel_widget import WheelWidget
from ui.widgets.slider_widget import SliderWidget
from application.session_app import (
    SessionApp,
    PatientTreatParams,
    PULSEWIDTH_VALUES,
    pulsewidth_default_index,
)
from application.stim_test_app import StimTestApp
from service.business.hardware.dd_ack_retry import DdAckRetrySender
from ui.core.utils import get_ui_attr, safe_call, safe_connect


class _StimSerialAckBridge(QObject):
    """串口接收线程 -> Qt 主线程：应答后启停定时器/改 UI 须经此转发。"""

    start_command_acked = Signal()
    stop_command_acked = Signal()
    right_grade_acked = Signal()


class StimTestController:
    """
    电刺激测试模块（tabWidget_2 index=0 / tab_3）。

    目标：把电刺激相关的 UI 逻辑从 `TreatPageController` 剥离出来，
    让上层只负责导航与页面编排。
    """

    # pushButton_right_turnbig / pushButton_right_turnsmall 最小触发间隔（毫秒）
    _RIGHT_GRADE_BUTTON_MIN_INTERVAL_MS = 1000
    # 右通道加减档：未收到应答时 500ms 后重发一次
    _RIGHT_GRADE_ACK_TIMEOUT_MS = 500
    # 右通道加减档：最多重发次数（不包含初始点击发送）
    # “点击后500ms无应答，则再发一次”的过程重复五次 => 重发 5 次，初始发送 1 次，总计 6 次发送
    _RIGHT_GRADE_MAX_RESENDS = 5
    _ACK_RECV_BUFFER_MAX = 256
    _ACK_FRAME_LEN = 13
    _ACK_FRAME_TYPE = 0xDD
    _DD_ACK_TIMEOUT_SEC = 0.5
    # 开始命令收到 0xDD 应答后，延迟再下发参数数据帧
    _START_PARAM_DELAY_MS = 1000

    def __init__(self, ui, session_app: Optional[SessionApp] = None, stim_app: Optional[StimTestApp] = None):
        self.ui = ui
        self.session_app = session_app
        self.stim_app = stim_app
        self._logger = logging.getLogger(__name__)
        self._max_stim_grade = 50

        # 右侧脉冲宽度当前索引（0 ~ len(PULSEWIDTH_VALUES)-1）
        self._pulsewidth_index: int = 0

        # 控件联动保护：避免左右下拉框/脉冲宽度控件互相设置时触发递归回调
        self._is_syncing_scheme_freq = False

        # True=开始状态（stop可用/start不可用/next不可用）；False=停止状态（start可用/stop不可用/next可用）
        self._test_running = False
        # 设备在线状态（影响控件可用性）
        self._hardware_online = True

        # 频率默认第五档（index=4）。这里在绑定信号前设置，避免触发下发指令。
        self._set_default_freq_to_fifth()
        # 脉冲宽度：10–100 步长 10，100–1000 步长 50，默认 800，对应协议索引。
        self._init_pulsewidth_combo()

        # 记录 UI 初始默认的方案/频率索引（用于患者第一次进入时初始化）
        self._default_params = {
            "left_scheme_idx": self._get_combo_index("comboBox_left_scheme") or 0,
            "left_freq_idx": self._get_combo_index("comboBox_left_freq") or 0,
            "pulsewidth_idx": self._pulsewidth_index,
        }

        self._current_patient_id: Optional[str] = None
        self._left_circle_widget: Optional[CircleLevelWidget] = None
        self._right_circle_widget: Optional[CircleLevelWidget] = None
        self._pulsewidth_wheel: Optional[WheelWidget] = None
        self._pulsewidth_slider: Optional[SliderWidget] = None
        # 脉冲宽度滚轮防抖：仅在停止在某个值后发送指令
        self._pulsewidth_commit_timer = QTimer()
        self._pulsewidth_commit_timer.setSingleShot(True)
        # 右通道加/减档按钮节流（两键共用）
        self._last_right_grade_button_monotonic: float = 0.0
        # 右通道加/减档按钮应答重发状态
        self._right_grade_ack_timer = QTimer()
        self._right_grade_ack_timer.setSingleShot(True)
        self._right_grade_ack_timer.timeout.connect(self._on_right_grade_ack_timeout)
        self._waiting_right_grade_ack = False
        self._right_grade_retry_count: int = 0
        self._pending_right_grade_current: Optional[int] = None
        self._right_grade_ack_callback_registered = False
        self._right_grade_recv_buffer = bytearray()

        # pushButton_start_test：未收到应答帧则重复重发（最多 5 次）
        self._start_ack_timer = QTimer()
        self._start_ack_timer.setSingleShot(True)
        self._start_ack_timer.timeout.connect(self._on_start_ack_timeout)
        self._waiting_start_ack = False
        self._start_retry_count = 0
        self._start_recv_buffer = bytearray()
        self._start_param_delay_timer = QTimer()
        self._start_param_delay_timer.setSingleShot(True)
        self._start_param_delay_timer.timeout.connect(self._on_start_param_delay_timeout)

        # pushButton_start_test 在“停止态->点击停止”分支：未收到应答帧则重复重发（最多 5 次）
        self._stop_ack_timer = QTimer()
        self._stop_ack_timer.setSingleShot(True)
        self._stop_ack_timer.timeout.connect(self._on_stop_ack_timeout)
        self._waiting_stop_ack = False
        self._stop_retry_count = 0
        self._stop_recv_buffer = bytearray()

        bridge_parent = ui if isinstance(ui, QObject) else None
        self._serial_ack_bridge = _StimSerialAckBridge(bridge_parent)
        self._serial_ack_bridge.start_command_acked.connect(self._on_start_command_ack_received)
        self._serial_ack_bridge.stop_command_acked.connect(self._on_stop_command_ack_received)
        self._serial_ack_bridge.right_grade_acked.connect(self._clear_right_grade_ack_state)

    def _dialog_parent(self):
        return self.ui.window() if self.ui is not None else None

    @property
    def is_test_running(self) -> bool:
        return bool(self._test_running)

    def bind_signals(self) -> None:
        # 开始/停止合并到同一按钮：点击切换
        start_btn = get_ui_attr(self.ui, "pushButton_start_test")
        safe_connect(self._logger, getattr(start_btn, "clicked", None), self._on_start_stop_test_clicked)
        stop_btn = get_ui_attr(self.ui, "pushButton_stop_test")
        if stop_btn is not None:
            stop_btn.setVisible(False)

        # 左通道等级调整按钮
        left_big = get_ui_attr(self.ui, "pushButton_left_turnbig")
        safe_connect(self._logger, getattr(left_big, "clicked", None), self._on_left_grade_increase)
        left_small = get_ui_attr(self.ui, "pushButton_left_turnsmall")
        safe_connect(self._logger, getattr(left_small, "clicked", None), self._on_left_grade_decrease)

        # 左通道频率/方案选择
        left_freq = get_ui_attr(self.ui, "comboBox_left_freq")
        safe_connect(self._logger, getattr(left_freq, "currentIndexChanged", None), self._on_left_freq_changed)
        left_scheme = get_ui_attr(self.ui, "comboBox_left_scheme")
        safe_connect(self._logger, getattr(left_scheme, "currentIndexChanged", None), self._on_left_scheme_changed)

        # 右通道等级调整按钮
        right_big = get_ui_attr(self.ui, "pushButton_right_turnbig")
        safe_connect(self._logger, getattr(right_big, "clicked", None), self._on_right_grade_increase)
        right_small = get_ui_attr(self.ui, "pushButton_right_turnsmall")
        safe_connect(self._logger, getattr(right_small, "clicked", None), self._on_right_grade_decrease)

        self._init_left_circle_widget()
        self._init_right_circle_widget()
        self._init_pulsewidth_wheel()
        self._init_pulsewidth_slider()
        self._ensure_right_grade_ack_callback()

    def _is_left_channel_ui_available(self) -> bool:
        return (
            get_ui_attr(self.ui, "label_left_grade") is not None
            and get_ui_attr(self.ui, "comboBox_left_scheme") is not None
            and get_ui_attr(self.ui, "comboBox_left_freq") is not None
        )

    def _init_left_circle_widget(self) -> None:
        """在 widget_circle_level_left 中放入只读圆环，与 label_left_grade 联动，并裁剪为圆形区域。"""
        host = get_ui_attr(self.ui, "widget_circle_level_left")
        if host is None:
            return
        layout = host.layout()
        if layout is None:
            layout = QVBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
        self._left_circle_widget = CircleLevelWidget(host)
        self._left_circle_widget.set_level_range(0, self._max_stim_grade)
        self._left_circle_widget.set_read_only(True)
        self._left_circle_widget.set_level(self._get_left_grade())
        layout.addWidget(self._left_circle_widget)

        host.installEventFilter(_CircleMaskResizeFilter(host))
        QTimer.singleShot(0, lambda: self._apply_circle_mask_to_host(host))

    def _init_right_circle_widget(self) -> None:
        """在 widget_circle_level_right 中放入只读圆环（参考 HW 分段仪表盘样式）。"""
        host = get_ui_attr(self.ui, "widget_circle_level_right")
        if host is None:
            return
        layout = host.layout()
        if layout is None:
            layout = QVBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
        self._right_circle_widget = CircleLevelWidget(host)
        self._right_circle_widget.set_level_range(0, self._max_stim_grade)
        self._right_circle_widget.set_read_only(True)
        self._right_circle_widget.set_level(self._get_right_grade())
        layout.addWidget(self._right_circle_widget)

        label = get_ui_attr(self.ui, "label_stim_intensity")
        if label is not None:
            label.hide()

        host.installEventFilter(_CircleMaskResizeFilter(host))
        QTimer.singleShot(0, lambda: self._apply_circle_mask_to_host(host))

    def _init_pulsewidth_wheel(self) -> None:
        """
        脉冲宽度滚轮：在 widget_pulsewidth 中绘制类似苹果时间选择器的拨轮。
        """
        if self._pulsewidth_wheel is not None:
            return

        host = get_ui_attr(self.ui, "widget_pulsewidth")
        if host is None:
            # 注意：位置完全由 .ui 中名为 widget_pulsewidth 的控件决定；
            # 若未在 Designer 中创建该控件，则不绘制拨轮。
            return

        # 优先支持在 .ui 中直接将 widget_pulsewidth 提升为 WheelWidget：
        # 这种情况下 host 本身就是滚轮控件，严格使用设计器设定的位置和大小。
        if isinstance(host, WheelWidget):
            wheel = host
        else:
            # 否则在 widget_pulsewidth 内部创建一个滚轮，并让其铺满该区域，
            # 以 widget_pulsewidth 在 .ui 中的 geometry 作为最终位置。
            wheel = WheelWidget(host)
            wheel.setGeometry(host.rect())

        # 使用实际脉冲宽度值（ms）作为显示文本，例如 "800 ms"
        labels = [f"{v} ms" for v in PULSEWIDTH_VALUES]
        wheel.set_values(labels)

        idx = max(0, min(len(PULSEWIDTH_VALUES) - 1, int(self._pulsewidth_index)))
        wheel.set_current_index(idx)

        # 滚轮防抖：调整过程中只更新索引和滑杆，停止在该值后才下发参数
        _COMMIT_MS = 500

        def on_wheel_index_changing(row: int) -> None:
            clamped = max(0, min(len(PULSEWIDTH_VALUES) - 1, int(row)))
            self._pulsewidth_index = clamped
            if self._pulsewidth_slider is not None:
                try:
                    self._pulsewidth_slider.set_value(clamped)
                except Exception:
                    pass
            self._pulsewidth_commit_timer.stop()
            self._pulsewidth_commit_timer.start(_COMMIT_MS)

        def on_pulsewidth_commit() -> None:
            self._on_right_freq_changed(self._pulsewidth_index)

        self._pulsewidth_commit_timer.timeout.connect(on_pulsewidth_commit)
        wheel.currentIndexChanged.connect(on_wheel_index_changing)
        self._pulsewidth_wheel = wheel

    def _init_pulsewidth_slider(self) -> None:
        """
        脉冲宽度竖直滑杆：在 widget_pulsewidth_silder 中绘制自定义滑块控件。
        """
        if self._pulsewidth_slider is not None:
            return

        host = get_ui_attr(self.ui, "widget_pulsewidth_silder")
        if host is None:
            return

        if isinstance(host, SliderWidget):
            slider = host
        else:
            slider = SliderWidget(host)
            slider.setGeometry(host.rect())

        max_index = max(0, len(PULSEWIDTH_VALUES) - 1)
        slider.set_range(0, max_index)

        idx_int = max(0, min(max_index, int(self._pulsewidth_index)))
        slider.set_value(idx_int)

        def on_slider_value_changed(v: int) -> None:
            # 滑杆控制拨轮的当前索引
            row = max(0, min(max_index, int(v)))
            self._pulsewidth_index = row
            if self._pulsewidth_wheel is not None:
                try:
                    self._pulsewidth_wheel.set_current_index(row)
                    return
                except Exception:
                    pass
            # 直接下发参数 + 保存
            self._on_right_freq_changed(row)

        slider.valueChanged.connect(on_slider_value_changed)

        self._pulsewidth_slider = slider

    def _apply_circle_mask_to_host(self, host) -> None:
        """将 host 裁剪为圆形显示与点击区域（以短边为直径居中）。"""
        w, h = host.width(), host.height()
        if w <= 0 or h <= 0:
            return
        d = min(w, h)
        x = (w - d) // 2
        y = (h - d) // 2
        region = QRegion(x, y, d, d, QRegion.Ellipse)
        host.setMask(region)

    def set_current_patient(self, patient: dict | None) -> None:
        """设置当前患者并恢复缓存参数（患者绑定）。"""
        self._current_patient_id = self._extract_patient_id(patient)
        if self.session_app and self._current_patient_id:
            try:
                self.session_app.set_current_patient(self._current_patient_id)
            except Exception:
                self._logger.exception("设置当前患者失败")
        self._apply_cached_params()

    def on_enter(self) -> None:
        """进入电刺激页：强制回到停止态。"""
        self._ensure_right_grade_ack_callback()
        self._apply_cached_params()
        self._set_running_state(running=False)

    def on_exit(self) -> None:
        """离开电刺激页：保存当前档位并停止。"""
        self._clear_right_grade_ack_state()
        self._clear_start_ack_state()
        self._clear_stop_ack_state()
        self._save_current_params()
        self._stop_treatment_safe()

    def on_exit_without_stop(self) -> None:
        """离开电刺激页：仅保存当前档位并回到停止态，不下发停止命令。"""
        self._clear_right_grade_ack_state()
        self._clear_start_ack_state()
        self._clear_stop_ack_state()
        self._save_current_params()
        self._set_running_state(running=False)

    def reset_stimulus_grades(self) -> None:
        """清零左右刺激强度（0级）并同步到硬件与 session。从主页面进入新 session 时调用。"""
        if self._is_left_channel_ui_available():
            self._set_left_grade(0)
        self._set_right_grade(0)
        if self._is_left_channel_ui_available():
            self._send_left_channel_params(current_value=0)
        self._send_right_channel_params(current_value=0)
        self._save_current_params()

    def reset_stimulus_grades_local(self) -> None:
        """仅清零左右刺激强度并保存，不向下位机发送 DA 参数帧。"""
        if self._is_left_channel_ui_available():
            self._set_left_grade(0)
        self._set_right_grade(0)
        # 重置脉冲宽度到默认 800 ms 对应的索引，并同步到滚轮/滑杆
        try:
            self._pulsewidth_index = int(pulsewidth_default_index())
        except Exception:
            self._pulsewidth_index = 0
        try:
            self._pulsewidth_index = max(0, min(len(PULSEWIDTH_VALUES) - 1, int(self._pulsewidth_index)))
        except Exception:
            self._pulsewidth_index = 0
        if self._pulsewidth_wheel is not None:
            try:
                self._pulsewidth_wheel.set_current_index(self._pulsewidth_index)
            except Exception:
                pass
        if self._pulsewidth_slider is not None:
            try:
                self._pulsewidth_slider.set_value(self._pulsewidth_index)
            except Exception:
                pass
        self._save_current_params()

    # ----------------- UI 状态管理 -----------------
    def _set_default_freq_to_fifth(self) -> None:
        """将左通道频率下拉框默认设置为第五档（index=4）；脉冲宽度由 _init_pulsewidth_combo 单独处理。"""
        combo = get_ui_attr(self.ui, "comboBox_left_freq")
        if combo is None:
            return
        try:
            if int(combo.count()) >= 5:
                old_block = combo.blockSignals(True)
                combo.setCurrentIndex(4)
                combo.blockSignals(old_block)
        except Exception:
            self._logger.exception("设置默认频率失败: comboBox_left_freq")

    def _init_pulsewidth_combo(self) -> None:
        """
        初始化脉冲宽度默认索引（只做逻辑，不再依赖 comboBox_pulsewidth）。

        脉冲宽度：10–100 步长 10，100–1000 步长 50，默认 800。
        """
        try:
            self._pulsewidth_index = int(pulsewidth_default_index())
        except Exception:
            self._pulsewidth_index = 0

    def _set_running_state(self, running: bool) -> None:
        self._test_running = bool(running)

        start_btn = get_ui_attr(self.ui, "pushButton_start_test")
        if start_btn is not None:
            safe_call(self._logger, getattr(start_btn, "setEnabled", None), self._hardware_online)
            safe_call(
                self._logger,
                getattr(start_btn, "setText", None),
                "停止测试" if self._test_running else "开始测试",
            )
            # 开始测试：背景 #789EFF、白色字体；停止测试：背景 #F48438、白色字体；保留倒角与 .ui 一致
            bg = "#F48438" if self._test_running else "#789EFF"
            safe_call(
                self._logger,
                getattr(start_btn, "setStyleSheet", None),
                f"QPushButton {{ background-color: {bg}; color: white; border-radius: 12.6px; }} "
                f"QPushButton:disabled {{ background-color: #707070; color: white; border-radius: 12.6px; }}",
            )

        # 左右通道档位调节按钮：在线即可点，未开始测试时点击会弹提示
        for btn_name in (
            "pushButton_left_turnbig",
            "pushButton_left_turnsmall",
            "pushButton_right_turnbig",
            "pushButton_right_turnsmall",
        ):
            button = get_ui_attr(self.ui, btn_name)
            safe_call(self._logger, getattr(button, "setEnabled", None), self._hardware_online)

    def set_hardware_online(self, is_online: bool) -> None:
        """根据下位机在线状态更新控件可用性"""
        self._hardware_online = bool(is_online)
        self._update_device_dependent_controls()

    def _update_device_dependent_controls(self) -> None:
        """更新依赖下位机在线状态的控件"""
        enabled = bool(self._hardware_online)

        if not enabled:
            # 离线：重置档位为 0，恢复默认下拉框
            if self._is_left_channel_ui_available():
                self._set_left_grade(0)
            self._set_right_grade(0)
            if self._is_left_channel_ui_available():
                self._set_combo_index("comboBox_left_scheme", self._default_params.get("left_scheme_idx", 0))
            if self._is_left_channel_ui_available():
                self._set_combo_index("comboBox_left_freq", self._default_params.get("left_freq_idx", 0))
            # 右通道脉冲宽度索引恢复默认，并同步到滚轮/滑杆
            self._pulsewidth_index = int(self._default_params.get("pulsewidth_idx", 0) or 0)
            try:
                self._pulsewidth_index = max(0, min(len(PULSEWIDTH_VALUES) - 1, self._pulsewidth_index))
            except Exception:
                self._pulsewidth_index = 0
            if self._pulsewidth_wheel is not None:
                try:
                    self._pulsewidth_wheel.set_current_index(self._pulsewidth_index)
                except Exception:
                    pass
            if self._pulsewidth_slider is not None:
                try:
                    self._pulsewidth_slider.set_value(self._pulsewidth_index)
                except Exception:
                    pass

        # 方案/频率下拉框：离线时不可选
        for name in (
            "comboBox_left_freq",
            "comboBox_left_scheme",
        ):
            combo = get_ui_attr(self.ui, name)
            safe_call(self._logger, getattr(combo, "setEnabled", None), enabled)

        # 档位增减按钮：在线即可点，未开始测试时点击会弹提示
        for btn_name in (
            "pushButton_left_turnbig",
            "pushButton_left_turnsmall",
            "pushButton_right_turnbig",
            "pushButton_right_turnsmall",
        ):
            button = get_ui_attr(self.ui, btn_name)
            safe_call(self._logger, getattr(button, "setEnabled", None), enabled)

        # 开始/停止合一按钮：在线即可点，点击在开始/停止间切换
        if hasattr(self.ui, "pushButton_start_test"):
            safe_call(
                self._logger,
                getattr(self.ui.pushButton_start_test, "setEnabled", None),
                enabled,
            )


    # ----------------- 开始/停止测试（同一按钮切换）-----------------
    def _on_start_stop_test_clicked(self) -> None:
        """点击开始测试按钮：当前运行则停止，当前停止则开始。"""
        # 点击开始/停止按钮时，先终止并重置所有正在进行的应答重发循环
        self._clear_right_grade_ack_state()
        self._clear_start_ack_state()
        self._clear_stop_ack_state()
        if self._test_running:
            self._on_stop_test_clicked()
        else:
            self._on_start_test_clicked()

    def _on_start_test_clicked(self) -> None:
        try:
            # 进入开始测试时：左右通道档位重置为 0
            if self._is_left_channel_ui_available():
                self._set_left_grade(0)
            self._set_right_grade(0)
            # 同步保存（当前患者）
            self._save_current_params()
            self._ensure_right_grade_ack_callback()
            if self.stim_app:
                # 先发开始命令帧，收到 0xDD 应答后间隔 1s 再发参数数据帧
                if not self._send_start_command_once():
                    self._logger.warning("开始测试命令下发失败")
                else:
                    self._begin_start_ack_watch()
        finally:
            self._set_running_state(running=True)

    def _on_stop_test_clicked(self) -> None:
        # 关键行为：停止流程不立即切按钮状态，收到停止应答后再切为“停止态”。
        # 若超时重发 5 次仍无应答，保持当前“运行态”不变。
        if not self.stim_app:
            self._logger.warning("停止测试失败：stim_app 不可用，保持当前状态不变")
            return
        ok = self._send_stop_command_once()
        if not ok:
            self._logger.warning("停止测试命令下发失败，保持当前状态不变")
            return
        # 等待“停止”应答帧：500ms 无应答则重发（最多 5 次）
        self._begin_stop_ack_watch()

    def stop_safe(self) -> None:
        self._stop_treatment_safe()

    def _stop_treatment_safe(self) -> None:
        try:
            if self.stim_app:
                if hasattr(self.stim_app, "stop_treatment"):
                    self.stim_app.stop_treatment()
                elif hasattr(self.stim_app, "service") and hasattr(self.stim_app.service, "stop_treatment"):
                    self.stim_app.service.stop_treatment()
                else:
                    self.stim_app.stop_dual()
        except Exception:
            self._logger.exception("停止治疗失败")

    # ----------------- 档位/参数下发 -----------------
    def _get_first_char(self, text: str) -> str:
        if not text:
            return ""
        first_char = text[0]
        if "\u4e00" <= first_char <= "\u9fff":
            return first_char
        if first_char.isalnum():
            return first_char
        return first_char

    def _get_left_grade(self) -> int:
        label = get_ui_attr(self.ui, "label_left_grade")
        if label is None:
            return 0
        text = label.text()
        try:
            grade_str = text.replace("级", "").strip()
            return int(grade_str)
        except (ValueError, AttributeError):
            return 0

    def _set_left_grade(self, grade: int) -> None:
        label = get_ui_attr(self.ui, "label_left_grade")
        if label is None:
            return
        grade = max(0, min(self._max_stim_grade, grade))
        safe_call(self._logger, getattr(label, "setText", None), f"{grade}级")
        if self._left_circle_widget is not None:
            self._left_circle_widget.set_level(grade)

    def _get_right_grade(self) -> int:
        if self._right_circle_widget is not None:
            return max(0, min(self._max_stim_grade, int(self._right_circle_widget.level())))
        label = get_ui_attr(self.ui, "label_stim_intensity")
        if label is None:
            return 0
        text = label.text()
        try:
            grade_str = text.replace("级", "").strip()
            return int(grade_str)
        except (ValueError, AttributeError):
            return 0

    def _set_right_grade(self, grade: int) -> None:
        grade = max(0, min(self._max_stim_grade, grade))
        label = get_ui_attr(self.ui, "label_stim_intensity")
        if label is not None:
            safe_call(self._logger, getattr(label, "setText", None), f"{grade}级")
        if self._right_circle_widget is not None:
            self._right_circle_widget.set_level(grade)

    def _send_left_channel_params(self, current_value: int) -> None:
        if not self._is_left_channel_ui_available():
            return
        if not self.stim_app:
            return
        scheme_idx = self._get_combo_index("comboBox_left_scheme") or 0
        scheme = 1 if scheme_idx <= 0 else 2
        freq_idx = self._get_combo_index("comboBox_left_freq") or 0
        frequency = int(freq_idx)
        current = max(0, min(0x32, int(current_value)))
        try:
            self.stim_app.set_params(scheme=scheme, frequency=frequency, current=current, channel="left")
        except Exception:
            self._logger.exception("下发左通道参数失败")

    def _send_right_channel_params(self, current_value: int) -> None:
        if not self.stim_app:
            return
        try:
            freq_idx = max(0, min(0x1B, int(self._pulsewidth_index)))
        except Exception:
            freq_idx = 0
        frequency = freq_idx
        current = max(0, min(0x32, int(current_value)))
        try:
            # 单通道模式下数据帧保留位固定 0x00，不再使用右通道 0x0B
            self.stim_app.set_params(scheme=0x00, frequency=frequency, current=current, channel=None)
        except Exception:
            self._logger.exception("下发右通道参数失败")

    # ----------------- UI 事件：下拉框/按钮 -----------------
    def _on_left_freq_changed(self, index: int) -> None:
        if not self._is_syncing_scheme_freq:
            self._is_syncing_scheme_freq = True
            try:
                # 左通道频率变化时，同步右通道脉冲宽度索引，并更新滚轮/滑杆
                try:
                    idx = max(0, min(len(PULSEWIDTH_VALUES) - 1, int(index)))
                except Exception:
                    idx = 0
                self._pulsewidth_index = idx
                if self._pulsewidth_wheel is not None:
                    try:
                        self._pulsewidth_wheel.set_current_index(idx)
                    except Exception:
                        pass
                if self._pulsewidth_slider is not None:
                    try:
                        self._pulsewidth_slider.set_value(idx)
                    except Exception:
                        pass
                # 下发右通道参数
                self._on_right_freq_changed(idx)
            finally:
                self._is_syncing_scheme_freq = False
        current_grade = self._get_left_grade()
        self._send_left_channel_params(current_value=current_grade)
        self._save_current_params()

    def _on_left_scheme_changed(self, index: int) -> None:
        current_grade = self._get_left_grade()
        self._send_left_channel_params(current_value=current_grade)
        self._save_current_params()

    def _on_right_freq_changed(self, index: int) -> None:
        # 更新右通道脉冲宽度索引（不再依赖 comboBox_pulsewidth）
        try:
            self._pulsewidth_index = max(0, min(len(PULSEWIDTH_VALUES) - 1, int(index)))
        except Exception:
            self._pulsewidth_index = 0
        if not self._is_syncing_scheme_freq:
            self._is_syncing_scheme_freq = True
            try:
                if self._is_left_channel_ui_available():
                    self._set_combo_index("comboBox_left_freq", index)
            finally:
                self._is_syncing_scheme_freq = False
        current_grade = self._get_right_grade()
        self._send_right_channel_params_with_dd_retry(current_value=current_grade, desc="脉冲宽度滚轮参数帧")
        self._save_current_params()

    def _send_right_channel_params_with_dd_retry(self, current_value: int, desc: str) -> bool:
        service = getattr(self.stim_app, "service", None) if self.stim_app else None
        serial_hw = getattr(service, "serial_hw", None) if service else None
        ok = DdAckRetrySender.send_with_retry(
            serial_hw=serial_hw,
            send_callable=lambda: self._send_right_channel_params_once(current_value),
            logger=self._logger,
            desc=desc,
            timeout_sec=self._DD_ACK_TIMEOUT_SEC,
            max_resends=self._RIGHT_GRADE_MAX_RESENDS,
            ack_frame_len=self._ACK_FRAME_LEN,
            ack_frame_type=self._ACK_FRAME_TYPE,
            recv_buffer_max=self._ACK_RECV_BUFFER_MAX,
        )
        if not ok:
            self._logger.warning("%s 超时未收到应答", desc)
        return ok

    def _send_right_channel_params_once(self, current_value: int) -> bool:
        if not self.stim_app:
            return False
        try:
            freq_idx = max(0, min(0x1B, int(self._pulsewidth_index)))
        except Exception:
            freq_idx = 0
        current = max(0, min(0x32, int(current_value)))
        try:
            return bool(self.stim_app.set_params(scheme=0x00, frequency=freq_idx, current=current, channel=None))
        except Exception:
            self._logger.exception("下发右通道参数失败")
            return False

    def _on_left_grade_increase(self) -> None:
        if not self._test_running:
            TipsDialog.show_tips(self._dialog_parent(), "请先点击“开始测试”按钮")
            return
        current_grade = self._get_left_grade()
        new_grade = current_grade + 1
        self._set_left_grade(new_grade)
        self._send_left_channel_params(current_value=new_grade)
        self._save_current_params()

    def _on_left_grade_decrease(self) -> None:
        if not self._test_running:
            TipsDialog.show_tips(self._dialog_parent(), "请先点击“开始测试”按钮")
            return
        current_grade = self._get_left_grade()
        new_grade = current_grade - 1
        self._set_left_grade(new_grade)
        self._send_left_channel_params(current_value=new_grade)
        self._save_current_params()

    def _on_right_grade_increase(self) -> None:
        if not self._test_running:
            TipsDialog.show_tips(self._dialog_parent(), "请先点击“开始测试”按钮")
            return
        if not self._allow_right_grade_button_fire():
            return
        current_grade = self._get_right_grade()
        new_grade = current_grade + 1
        self._set_right_grade(new_grade)
        self._send_right_channel_params(current_value=new_grade)
        self._begin_right_grade_ack_watch(new_grade)
        self._save_current_params()

    def _on_right_grade_decrease(self) -> None:
        if not self._test_running:
            TipsDialog.show_tips(self._dialog_parent(), "请先点击“开始测试”按钮")
            return
        if not self._allow_right_grade_button_fire():
            return
        current_grade = self._get_right_grade()
        new_grade = current_grade - 1
        self._set_right_grade(new_grade)
        self._send_right_channel_params(current_value=new_grade)
        self._begin_right_grade_ack_watch(new_grade)
        self._save_current_params()

    def _allow_right_grade_button_fire(self) -> bool:
        """右通道加/减档：距上次有效触发不足最小间隔则忽略。"""
        now = time.monotonic()
        min_sec = self._RIGHT_GRADE_BUTTON_MIN_INTERVAL_MS / 1000.0
        if self._last_right_grade_button_monotonic > 0.0 and (now - self._last_right_grade_button_monotonic) < min_sec:
            return False
        self._last_right_grade_button_monotonic = now
        return True

    def _ensure_right_grade_ack_callback(self) -> None:
        if self._right_grade_ack_callback_registered:
            return
        service = getattr(self.stim_app, "service", None) if self.stim_app else None
        serial_hw = getattr(service, "serial_hw", None) if service else None
        if serial_hw is None or not hasattr(serial_hw, "add_data_received_callback"):
            return
        try:
            serial_hw.add_data_received_callback(self._on_right_grade_serial_data)
            self._right_grade_ack_callback_registered = True
        except Exception:
            self._logger.exception("注册右通道加减档应答回调失败")

    def _begin_right_grade_ack_watch(self, current_value: int) -> None:
        self._pending_right_grade_current = max(0, min(0x32, int(current_value)))
        self._waiting_right_grade_ack = True
        self._right_grade_retry_count = 0
        self._right_grade_recv_buffer.clear()
        self._right_grade_ack_timer.stop()
        self._right_grade_ack_timer.start(self._RIGHT_GRADE_ACK_TIMEOUT_MS)

    def _on_right_grade_ack_timeout(self) -> None:
        if not self._waiting_right_grade_ack:
            return
        if self._right_grade_retry_count >= self._RIGHT_GRADE_MAX_RESENDS:
            self._logger.warning(
                "右通道加减档指令超时未收到 0xDD 应答帧（已重发 %s 次，停止）",
                self._right_grade_retry_count,
            )
            self._clear_right_grade_ack_state()
            return
        self._right_grade_retry_count += 1
        current = self._pending_right_grade_current
        if current is not None:
            self._send_right_channel_params(current_value=current)
        self._right_grade_ack_timer.start(self._RIGHT_GRADE_ACK_TIMEOUT_MS)

    def _on_right_grade_serial_data(self, data: bytes) -> None:
        if not data:
            return
        self._right_grade_recv_buffer.extend(data)
        if len(self._right_grade_recv_buffer) > self._ACK_RECV_BUFFER_MAX:
            self._right_grade_recv_buffer = self._right_grade_recv_buffer[-self._ACK_RECV_BUFFER_MAX:]

        self._start_recv_buffer.extend(data)
        if len(self._start_recv_buffer) > self._ACK_RECV_BUFFER_MAX:
            self._start_recv_buffer = self._start_recv_buffer[-self._ACK_RECV_BUFFER_MAX:]

        self._stop_recv_buffer.extend(data)
        if len(self._stop_recv_buffer) > self._ACK_RECV_BUFFER_MAX:
            self._stop_recv_buffer = self._stop_recv_buffer[-self._ACK_RECV_BUFFER_MAX:]

        if self._waiting_right_grade_ack and self._contains_dd_ack_frame(bytes(self._right_grade_recv_buffer)):
            self._serial_ack_bridge.right_grade_acked.emit()
        # 开始流程：收到 DD 应答后停止重发开始命令，并延迟 1s 下发参数帧（须在主线程启定时器）
        if self._waiting_start_ack and self._contains_dd_ack_frame(bytes(self._start_recv_buffer)):
            self._serial_ack_bridge.start_command_acked.emit()
        # 停止流程：收到 DD 应答后在主线程切 UI
        if self._waiting_stop_ack and self._contains_dd_ack_frame(bytes(self._stop_recv_buffer)):
            self._serial_ack_bridge.stop_command_acked.emit()

    def _contains_dd_ack_frame(self, data: bytes) -> bool:
        """
        应答判定：固定帧长 13 字节，且第 5 位（index=4）为 0xDD。
        额外约束帧头与长度字段，减少误判。
        """
        if len(data) < self._ACK_FRAME_LEN:
            return False
        last_start = len(data) - self._ACK_FRAME_LEN
        for i in range(last_start + 1):
            if data[i] != 0x55 or data[i + 1] != 0xAA:
                continue
            if data[i + 2] != 0x0D:
                continue
            if data[i + 4] == self._ACK_FRAME_TYPE:
                return True
        return False

    def _clear_right_grade_ack_state(self) -> None:
        self._right_grade_ack_timer.stop()
        self._waiting_right_grade_ack = False
        self._right_grade_retry_count = 0
        self._pending_right_grade_current = None
        self._right_grade_recv_buffer.clear()

    def _begin_start_ack_watch(self) -> None:
        """
        pushButton_start_test：开始命令发出后等待 DD 应答。
        500ms 无应答则仅重发开始命令（最多 5 次）；收到应答后间隔 1s 再发参数数据帧。
        """
        self._clear_start_ack_state()
        # 如果刚好之前也在等待右通道应答，开始后优先满足开始应答
        self._clear_right_grade_ack_state()
        self._waiting_start_ack = True
        self._start_retry_count = 0
        self._start_recv_buffer.clear()
        self._start_ack_timer.start(self._RIGHT_GRADE_ACK_TIMEOUT_MS)

    def _on_start_command_ack_received(self) -> None:
        """开始命令收到 DD 应答（主线程）：停止重发，1s 后下发 current=0 的参数帧。"""
        self._start_ack_timer.stop()
        self._waiting_start_ack = False
        self._start_retry_count = 0
        self._start_recv_buffer.clear()
        self._start_param_delay_timer.stop()
        self._start_param_delay_timer.start(self._START_PARAM_DELAY_MS)
        self._logger.info(
            "开始测试：已收到 0xDD 应答，%sms 后下发参数数据帧",
            self._START_PARAM_DELAY_MS,
        )

    def _on_stop_command_ack_received(self) -> None:
        """停止命令收到 DD 应答（主线程）。"""
        self._clear_stop_ack_state()
        self._set_running_state(running=False)

    def _on_start_param_delay_timeout(self) -> None:
        """开始测试：延迟后下发参数数据帧（电流归零）。"""
        if not self._test_running:
            return
        try:
            if self._is_left_channel_ui_available():
                self._send_left_channel_params(current_value=0)
            self._send_right_channel_params(current_value=0)
            self._logger.info("开始测试：已下发参数数据帧（电流=0）")
        except Exception:
            self._logger.exception("开始测试延迟下发参数帧失败")

    def _on_start_ack_timeout(self) -> None:
        if not self._waiting_start_ack:
            return
        if self._start_retry_count >= self._RIGHT_GRADE_MAX_RESENDS:
            self._logger.warning(
                "pushButton_start_test 开始命令超时未收到 0xDD 应答帧（已重发 %s 次，停止；不下发参数帧）",
                self._start_retry_count,
            )
            self._clear_start_ack_state()
            return

        self._start_retry_count += 1
        try:
            self._send_start_command_once()
        except Exception:
            self._logger.exception("重发开始命令失败")

        self._start_ack_timer.start(self._RIGHT_GRADE_ACK_TIMEOUT_MS)

    def _clear_start_ack_state(self) -> None:
        self._start_ack_timer.stop()
        self._waiting_start_ack = False
        self._start_retry_count = 0
        self._start_recv_buffer.clear()
        self._start_param_delay_timer.stop()

    def _begin_stop_ack_watch(self) -> None:
        """停止后等待应答帧（固定），500ms 无应答则重发停止命令，最多 5 次。"""
        self._clear_stop_ack_state()
        self._waiting_stop_ack = True
        self._stop_retry_count = 0
        self._stop_recv_buffer.clear()
        self._stop_ack_timer.start(self._RIGHT_GRADE_ACK_TIMEOUT_MS)

    def _on_stop_ack_timeout(self) -> None:
        if not self._waiting_stop_ack:
            return
        if self._stop_retry_count >= self._RIGHT_GRADE_MAX_RESENDS:
            self._logger.warning(
                "pushButton_start_test(停止) 指令超时未收到应答帧（已重发 %s 次，保持当前状态不变）",
                self._stop_retry_count,
            )
            self._clear_stop_ack_state()
            return

        self._stop_retry_count += 1
        # 重发“停止命令”
        try:
            self._send_stop_command_once()
        except Exception:
            self._logger.exception("重发停止命令失败")

        self._stop_ack_timer.start(self._RIGHT_GRADE_ACK_TIMEOUT_MS)

    def _clear_stop_ack_state(self) -> None:
        self._stop_ack_timer.stop()
        self._waiting_stop_ack = False
        self._stop_retry_count = 0
        self._stop_recv_buffer.clear()

    def _send_start_command_once(self) -> bool:
        """发送一次开始治疗命令帧；返回是否下发成功。"""
        if not self.stim_app:
            return False
        if self._is_left_channel_ui_available():
            return bool(self.stim_app.start_dual())
        if hasattr(self.stim_app, "start_treatment_channel"):
            return bool(self.stim_app.start_treatment_channel("right"))
        return bool(self.stim_app.start_treatment())

    def _send_stop_command_once(self) -> bool:
        """发送一次停止命令；返回是否下发成功。"""
        if not self.stim_app:
            return False
        if self._is_left_channel_ui_available():
            return bool(self.stim_app.stop_dual())
        if hasattr(self.stim_app, "stop_treatment_channel"):
            return bool(self.stim_app.stop_treatment_channel("right"))
        return bool(self.stim_app.stop_treatment())

    # ----------------- 缓存：患者绑定 -----------------
    def _get_combo_index(self, name: str) -> int | None:
        combo = get_ui_attr(self.ui, name)
        if combo is None:
            return None
        try:
            return int(combo.currentIndex())
        except Exception:
            return None

    def _set_combo_index(self, name: str, idx: int | None) -> None:
        combo = get_ui_attr(self.ui, name)
        if idx is None or combo is None:
            return
        try:
            count = int(combo.count())
            if count <= 0:
                return
            idx = max(0, min(count - 1, int(idx)))
            old_block = combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(old_block)
        except Exception:
            self._logger.exception("设置下拉框索引失败: %s", name)

    def _extract_patient_id(self, patient: dict | None) -> str | None:
        if not patient:
            return None
        return str(patient.get("PatientId") or patient.get("Name") or "")

    def _apply_cached_params(self) -> None:
        pid = self._current_patient_id
        if not pid:
            if self._is_left_channel_ui_available():
                self._set_left_grade(0)
            self._set_right_grade(0)
            return
        params = None
        if self.session_app:
            try:
                params = self.session_app.load_treat_params(pid)
            except Exception:
                self._logger.exception("加载治疗参数失败: %s", pid)
                params = None

        if params is None:
            params = PatientTreatParams(
                patient_id=pid,
                channel_intensity=0,
                pulsewidth_idx=self._default_params.get("pulsewidth_idx", 0),
                left_grade=0,
                left_scheme_idx=self._default_params.get("left_scheme_idx", 0),
                right_scheme_idx=0,
                left_freq_idx=self._default_params.get("left_freq_idx", 0),
            )
            if self.session_app:
                try:
                    self.session_app.save_treat_params(params)
                except Exception:
                    self._logger.exception("初始化治疗参数失败: %s", pid)

        if self._is_left_channel_ui_available():
            self._set_left_grade(getattr(params, "left_grade", 0))
        self._set_right_grade(getattr(params, "right_grade", 0))
        if self._is_left_channel_ui_available():
            self._set_combo_index("comboBox_left_scheme", getattr(params, "left_scheme_idx", 0))
        if self._is_left_channel_ui_available():
            self._set_combo_index("comboBox_left_freq", getattr(params, "left_freq_idx", 0))
        # 恢复右通道脉冲宽度索引，并同步滚轮/滑杆
        idx = getattr(params, "right_freq_idx", getattr(params, "pulsewidth_idx", 0)) or 0
        try:
            self._pulsewidth_index = max(0, min(len(PULSEWIDTH_VALUES) - 1, int(idx)))
        except Exception:
            self._pulsewidth_index = 0
        if self._pulsewidth_wheel is not None:
            try:
                self._pulsewidth_wheel.set_current_index(self._pulsewidth_index)
            except Exception:
                pass
        if self._pulsewidth_slider is not None:
            try:
                self._pulsewidth_slider.set_value(self._pulsewidth_index)
            except Exception:
                pass

    def _save_current_params(self) -> None:
        pid = self._current_patient_id
        if not pid or not self.session_app:
            return
        try:
            self.session_app.save_treat_params(
                PatientTreatParams(
                    patient_id=pid,
                    channel_intensity=self._get_right_grade(),
                    pulsewidth_idx=int(self._pulsewidth_index or 0),
                    left_grade=self._get_left_grade(),
                    left_scheme_idx=self._get_combo_index("comboBox_left_scheme") or 0,
                    right_scheme_idx=0,
                    left_freq_idx=self._get_combo_index("comboBox_left_freq") or 0,
                )
            )
        except Exception:
            self._logger.exception("保存治疗参数失败: %s", pid)

    # ----------------- 对外：用于上层导航判断 -----------------
    def ensure_stopped_before_next(self) -> bool:
        """若仍在运行，弹提示并返回 False。"""
        # 下位机离线：允许直接进入下一步（避免被运行态卡住）
        if not self._hardware_online:
            return True
        if not self._test_running:
            return True
        try:
            TipsDialog.show_tips(self._dialog_parent(), "请先点击“停止测试”，停止后才能进入下一步")
        except Exception:
            self._logger.exception("弹出提示失败")
        return False


class _CircleMaskResizeFilter(QObject):
    """Resize 时重新为 host 设置圆形 mask。"""

    def __init__(self, host):
        super().__init__(host)
        self._host = host

    def eventFilter(self, obj, event) -> bool:
        if obj == self._host and event.type() == QEvent.Resize:
            w, h = self._host.width(), self._host.height()
            if w > 0 and h > 0:
                d = min(w, h)
                x, y = (w - d) // 2, (h - d) // 2
                self._host.setMask(QRegion(x, y, d, d, QRegion.Ellipse))
        return False
