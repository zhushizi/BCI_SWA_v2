from __future__ import annotations
'''
设置页（tabWidget 的 tab4）管理
'''
import logging
import ctypes
import re
from typing import Optional

from PySide6.QtWidgets import QWidget, QLineEdit

from ui.core.utils import get_ui_attr, safe_call, safe_connect
from ui.dialogs.tips_dialog import TipsDialog


class SetPageController:
    """设置页（tabWidget 的 tab4）管理"""

    def __init__(
        self,
        parent: QWidget,
        ui,
        logger: Optional[logging.Logger] = None,
        decoder_port: Optional[str] = None,
        hardware_config_app=None,
        user_app=None,
    ):
        self.parent = parent
        self.ui = ui
        self.logger = logger or logging.getLogger(__name__)
        self.decoder_port = str(decoder_port or "").strip() or None
        self.nes_port = None
        self.hardware_config_app = hardware_config_app
        self.user_app = user_app
        self._endpoint_volume = None
        self._muted = False
        self._volume_before_mute = None
        self._init_audio_endpoint()

    def bind_signals(self):
        combo = get_ui_attr(self.ui, "comboBox_decoder_port")
        safe_connect(self.logger, getattr(combo, "currentTextChanged", None), self._on_decoder_port_changed)
        nes_combo = get_ui_attr(self.ui, "comboBox_NES_port")
        safe_connect(self.logger, getattr(nes_combo, "currentTextChanged", None), self._on_nes_port_changed)
        slider = get_ui_attr(self.ui, "horizontalSlider_volume")
        if slider is None:
            self.logger.warning("未找到音量滑条: horizontalSlider_volume")
        safe_connect(self.logger, getattr(slider, "valueChanged", None), self._on_volume_changed)
        btn_minus = get_ui_attr(self.ui, "pushButton_vol_minus")
        if btn_minus is None:
            self.logger.warning("未找到音量减按钮: pushButton_vol_minus")
        safe_connect(self.logger, getattr(btn_minus, "clicked", None), self._on_volume_minus)
        btn_add = get_ui_attr(self.ui, "pushButton_vol_add")
        if btn_add is None:
            self.logger.warning("未找到音量加按钮: pushButton_vol_add")
        safe_connect(self.logger, getattr(btn_add, "clicked", None), self._on_volume_add)
        btn_toggle = get_ui_attr(self.ui, "pushButton_vol_shutopen")
        if btn_toggle is None:
            self.logger.warning("未找到静音按钮: pushButton_vol_shutopen")
        safe_connect(self.logger, getattr(btn_toggle, "clicked", None), self._on_volume_toggle)
        self._bind_account_controls()

    def init_ui(self):
        if self.hardware_config_app:
            self.decoder_port = self.hardware_config_app.get_decoder_port() or self.decoder_port
            self.nes_port = self.hardware_config_app.get_nes_port()

        combo = get_ui_attr(self.ui, "comboBox_decoder_port")
        nes_combo = get_ui_attr(self.ui, "comboBox_NES_port")
        detected_decoder_port, detected_nes_port, display_ports = self._build_detected_port_displays()

        # 规则优先：CH340 -> 电刺激设备(NES)；串行设备 -> 头环(decoder)
        if detected_decoder_port:
            self.decoder_port = detected_decoder_port
        if detected_nes_port:
            self.nes_port = detected_nes_port

        if combo:
            prev_block = combo.blockSignals(True)
            ports = list(display_ports)
            if self.decoder_port and self.decoder_port not in ports:
                ports.insert(0, self.decoder_port)
            combo.clear()
            if ports:
                for port in ports:
                    combo.addItem(self._format_decoder_display(port), port)
            if self.decoder_port:
                idx = combo.findData(self.decoder_port)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(prev_block)

        if nes_combo:
            prev_block = nes_combo.blockSignals(True)
            nes_ports = list(display_ports)
            if self.nes_port and self.nes_port not in nes_ports:
                nes_ports.insert(0, self.nes_port)
            nes_combo.clear()
            if nes_ports:
                for port in nes_ports:
                    nes_combo.addItem(self._format_nes_display(port), port)
            if self.nes_port:
                idx = nes_combo.findData(self.nes_port)
                if idx >= 0:
                    nes_combo.setCurrentIndex(idx)
            nes_combo.blockSignals(prev_block)

        # 自动连接到识别出的对应设备串口
        if detected_decoder_port:
            self._on_decoder_port_changed(detected_decoder_port)
        if detected_nes_port:
            self._on_nes_port_changed(detected_nes_port)
        self._init_volume_controls()
        self._init_account_controls()

    def refresh(self):
        pass

    def _init_volume_controls(self) -> None:
        slider = get_ui_attr(self.ui, "horizontalSlider_volume")
        if not slider:
            return
        try:
            slider.setMinimum(0)
            slider.setMaximum(100)
            slider.setSingleStep(5)
            slider.setPageStep(10)
            slider.setTracking(True)
        except Exception:
            pass
        current = self._get_system_volume_percent()
        if current is not None:
            prev = slider.blockSignals(True)
            slider.setValue(current)
            slider.blockSignals(prev)
            self._muted = current == 0
            if not self._muted:
                self._volume_before_mute = current
        else:
            self.logger.warning("未能读取系统音量，滑条保持默认值")
        self._sync_volume_icon()

    def _init_audio_endpoint(self) -> None:
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        self._ensure_audio_endpoint()

    def _ensure_audio_endpoint(self) -> bool:
        if self._endpoint_volume is not None:
            return True
        try:
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            device = AudioUtilities.GetSpeakers()
            if hasattr(device, "Activate"):
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            else:
                interface = device._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            self._endpoint_volume = interface.QueryInterface(IAudioEndpointVolume)
            return True
        except Exception as exc:
            self.logger.warning("初始化系统音量接口失败: %s", exc)
            return False

    def _get_system_volume_percent(self) -> int | None:
        try:
            if self._ensure_audio_endpoint():
                scalar = self._endpoint_volume.GetMasterVolumeLevelScalar()
                return int(round(float(scalar) * 100))
        except Exception as exc:
            self.logger.warning("读取系统音量失败: %s", exc)
        try:
            winmm = ctypes.windll.winmm
            vol = ctypes.c_uint()
            res = winmm.waveOutGetVolume(0, ctypes.byref(vol))
            if res != 0:
                return None
            left = vol.value & 0xFFFF
            right = (vol.value >> 16) & 0xFFFF
            avg = (left + right) / 2.0
            return int(round(avg / 0xFFFF * 100))
        except Exception:
            return None

    def _set_system_volume_percent(self, value: int) -> bool:
        try:
            if self._ensure_audio_endpoint():
                pct = max(0, min(100, int(value)))
                self._endpoint_volume.SetMasterVolumeLevelScalar(pct / 100.0, None)
                return True
        except Exception as exc:
            self.logger.warning("设置系统音量失败(CoreAudio): %s", exc)
        try:
            winmm = ctypes.windll.winmm
            pct = max(0, min(100, int(value)))
            vol = int(pct / 100 * 0xFFFF)
            winmm.waveOutSetVolume(0, vol | (vol << 16))
            return True
        except Exception as exc:
            self.logger.debug("设置系统音量失败: %s", exc)
        return False

    def _on_volume_changed(self, value: int) -> None:
        ok = self._set_system_volume_percent(value)
        if not ok:
            self.logger.warning("设置系统音量失败，目标值: %s", value)
            return
        current = self._get_system_volume_percent()
        if current is not None and abs(current - int(value)) >= 3:
            self.logger.warning("系统音量未同步，目标=%s 实际=%s", value, current)
        self._muted = int(value) == 0
        if not self._muted:
            self._volume_before_mute = int(value)
        self._sync_volume_icon()

    def _set_volume_slider(self, value: int) -> None:
        slider = get_ui_attr(self.ui, "horizontalSlider_volume")
        if not slider:
            return
        prev = slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(prev)

    def _sync_volume_icon(self) -> None:
        btn = get_ui_attr(self.ui, "pushButton_vol_shutopen")
        if not btn:
            return
        if self._muted:
            btn.setStyleSheet("border-image: url(:/set/pic/set_volumeshut.png);")
        else:
            btn.setStyleSheet("border-image: url(:/set/pic/set_volumeopen.png);")

    def _on_volume_toggle(self) -> None:
        if not self._muted:
            current = self._get_system_volume_percent()
            if current is not None:
                self._volume_before_mute = current
            self._set_system_volume_percent(0)
            self._set_volume_slider(0)
            self._muted = True
        else:
            restore = self._volume_before_mute if self._volume_before_mute is not None else 50
            self._set_system_volume_percent(restore)
            self._set_volume_slider(restore)
            self._muted = False
        self._sync_volume_icon()

    def _on_volume_add(self) -> None:
        slider = get_ui_attr(self.ui, "horizontalSlider_volume")
        if not slider:
            return
        step = slider.singleStep() or 5
        slider.setValue(min(slider.maximum(), slider.value() + step))

    def _on_volume_minus(self) -> None:
        slider = get_ui_attr(self.ui, "horizontalSlider_volume")
        if not slider:
            return
        step = slider.singleStep() or 5
        slider.setValue(max(slider.minimum(), slider.value() - step))

    def _on_decoder_port_changed(self, text: str) -> None:
        next_port = self._extract_port_device(text)
        if not next_port:
            return
        if self.decoder_port == next_port:
            return
        self.decoder_port = next_port
        if self.hardware_config_app:
            ok = self.hardware_config_app.set_decoder_port(next_port)
            if not ok:
                self.logger.warning("切换解码器端口失败: %s", next_port)

    def _on_nes_port_changed(self, text: str) -> None:
        next_port = self._extract_port_device(text)
        if not next_port:
            return
        if self.nes_port == next_port:
            return
        self.nes_port = next_port
        if self.hardware_config_app:
            ok = self.hardware_config_app.set_nes_port(next_port)
            if not ok:
                self.logger.warning("切换串口失败: %s", next_port)

    def _init_account_controls(self) -> None:
        """密码相关输入框统一使用掩码显示，避免明文输入。"""
        for name in (
            "lineEdit_resetpwd",
            "lineEdit_set_oldpwd",
            "lineEdit_set_newpwd",
            "lineEdit_set_confirmpwd",
        ):
            field = get_ui_attr(self.ui, name)
            if field is not None:
                safe_call(self.logger, getattr(field, "setEchoMode", None), QLineEdit.EchoMode.Password)

    def _bind_account_controls(self) -> None:
        save_btn = get_ui_attr(self.ui, "pushButton_resetpwdcomfirm")
        cancel_btn = get_ui_attr(self.ui, "pushButton_set_cancel")
        safe_connect(self.logger, getattr(save_btn, "clicked", None), self._on_account_save)
        safe_connect(self.logger, getattr(cancel_btn, "clicked", None), self._on_account_cancel)

    def _clear_account_fields(self) -> None:
        for name in (
            "lineEdit_resetpwd",
            "lineEdit_set_oldpwd",
            "lineEdit_set_newpwd",
            "lineEdit_set_confirmpwd",
        ):
            field = get_ui_attr(self.ui, name)
            safe_call(self.logger, getattr(field, "clear", None))

    def _account_field_text(self, name: str) -> str:
        field = get_ui_attr(self.ui, name)
        if field is None:
            return ""
        try:
            return field.text().strip()
        except Exception:
            return ""

    def _on_account_cancel(self) -> None:
        self._clear_account_fields()

    def _on_account_save(self) -> None:
        if not self.user_app:
            TipsDialog.show_tips(self.parent, "用户服务未就绪，无法修改密码")
            return

        admin_password = self._account_field_text("lineEdit_resetpwd")
        old_password = self._account_field_text("lineEdit_set_oldpwd")
        new_password = self._account_field_text("lineEdit_set_newpwd")
        confirm_password = self._account_field_text("lineEdit_set_confirmpwd")

        if not admin_password:
            TipsDialog.show_tips(self.parent, "请输入管理员密码")
            return
        if not old_password:
            TipsDialog.show_tips(self.parent, "请输入旧密码")
            return
        if not new_password:
            TipsDialog.show_tips(self.parent, "请输入新密码")
            return
        if not confirm_password:
            TipsDialog.show_tips(self.parent, "请确认新密码")
            return

        from service.user.user_login_service import ADMIN_PASSWORD
        if admin_password != ADMIN_PASSWORD:
            TipsDialog.show_tips(self.parent, "管理员密码不正确")
            return

        old_password_error = self.user_app.verify_current_password(old_password)
        if old_password_error:
            TipsDialog.show_tips(self.parent, old_password_error)
            return

        if new_password != confirm_password:
            TipsDialog.show_tips(self.parent, "两次输入的新密码不一致")
            return

        password_error = self.user_app.validate_password(new_password)
        if password_error:
            TipsDialog.show_tips(self.parent, password_error)
            return

        if new_password == old_password:
            TipsDialog.show_tips(self.parent, "新密码不能与旧密码相同")
            return

        result = self.user_app.change_password(admin_password, old_password, new_password)
        if result.get("success"):
            TipsDialog.show_tips(self.parent, str(result.get("message") or "密码修改成功"))
            self._clear_account_fields()
        else:
            TipsDialog.show_tips(self.parent, str(result.get("message") or "密码修改失败"))

    def _list_available_ports(self) -> list[str]:
        if not self.hardware_config_app:
            self.logger.warning("hardware_config_app 未注入，无法读取串口列表")
            return []
        try:
            return list(self.hardware_config_app.list_available_ports())
        except Exception:
            return []

    @staticmethod
    def _extract_port_device(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        # 兼容 "COM3（头环）" / "COM3 (电刺激设备)" 等展示文案
        match = re.match(r"^\s*([A-Za-z]+[0-9]+)\b", raw)
        if match:
            return match.group(1).upper()
        return raw

    def _scan_port_descriptions(self) -> dict[str, str]:
        try:
            from serial.tools import list_ports
            mapping: dict[str, str] = {}
            for p in list_ports.comports():
                dev = str(getattr(p, "device", "") or "").strip().upper()
                desc = str(getattr(p, "description", "") or "").strip()
                if dev:
                    mapping[dev] = desc
            return mapping
        except Exception:
            return {}

    def _build_detected_port_displays(self) -> tuple[Optional[str], Optional[str], list[str]]:
        ports = [str(p).strip().upper() for p in self._list_available_ports() if str(p).strip()]
        desc_map = self._scan_port_descriptions()
        detected_decoder_port: Optional[str] = None
        detected_nes_port: Optional[str] = None

        for port in ports:
            desc = (desc_map.get(port) or "").lower()
            if ("ch340" in desc) and (detected_nes_port is None):
                detected_nes_port = port
            if (("串行设备" in desc) or ("serial device" in desc)) and (detected_decoder_port is None):
                detected_decoder_port = port

        return detected_decoder_port, detected_nes_port, ports

    def _format_decoder_display(self, port: str) -> str:
        target = self._extract_port_device(port)
        if target and self.decoder_port and target == self.decoder_port:
            return f"{target}（头环）"
        return target or str(port or "").strip()

    def _format_nes_display(self, port: str) -> str:
        target = self._extract_port_device(port)
        if target and self.nes_port and target == self.nes_port:
            return f"{target}（电刺激设备）"
        return target or str(port or "").strip()
