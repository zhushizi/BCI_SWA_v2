from __future__ import annotations

import logging

from application.session_app import SessionApp
from application.stim_test_app import StimTestApp
from service.business.hardware.dd_ack_retry import DdAckRetrySender


class ParadigmActionApp:
    """范式动作指令应用层：编排 session 与刺激指令下发。"""

    TIME_BYTE = 0x06
    ACK_TIMEOUT_SEC = 0.5
    MAX_RESENDS = 15

    def __init__(self, session_app: SessionApp, stim_app: StimTestApp) -> None:
        self._session_app = session_app
        self._stim_app = stim_app
        self._logger = logging.getLogger(__name__)

    def handle_action_command(self, trial_index: int, action: str, channel: str) -> bool:
        # 范式动作指令：step_right 时强度位强制置 0（00）
        patient_id = self._session_app.get_current_patient_id()
        if not patient_id:
            self._logger.warning("未找到当前患者，无法下发动作")
            return False
        treat_params = self._session_app.load_treat_params(patient_id)
        if not treat_params:
            self._logger.warning("未找到当前患者治疗参数，无法下发动作")
            return False

        # 单通道参数：优先用新字段，其次兼容旧字段（right_*）
        freq_idx = getattr(treat_params, "pulsewidth_idx", None)
        if freq_idx is None:
            freq_idx = getattr(treat_params, "right_freq_idx", 0)
        current = getattr(treat_params, "channel_intensity", None)
        if current is None:
            current = getattr(treat_params, "right_grade", 0)

        # 如果是向右步进动作，则将强度位清零再发送
        try:
            if str(action) == "step_right":
                current = 0
        except Exception:
            # action 异常时不额外打断流程，保持原行为
            pass

        scheme = 0x00
        frequency = max(0, min(0x1B, int(freq_idx or 0)))
        current_val = max(0, min(0x32, int(current or 0)))

        try:
            # 单通道模式：命令帧/数据帧保留位固定 0x00
            if not self._send_with_dd_retry(self._stim_app.start_treatment, "start_treatment"):
                return False
            if not self._send_with_dd_retry(
                lambda: self._stim_app.set_treatment_params(
                    scheme=scheme,
                    frequency=frequency,
                    current=current_val,
                    channel=None,
                    time_byte=self.TIME_BYTE,
                ),
                "set_treatment_params(time=0x06)",
            ):
                return False
            return True
        except Exception as exc:
            self._logger.error("下发动作指令失败: %s", exc)
            return False

    def _send_with_dd_retry(self, send_callable, desc: str) -> bool:
        """
        发送命令并等待 DD 应答：500ms 无应答则重发，最多重发 5 次。
        """
        service = getattr(self._stim_app, "service", None)
        serial_hw = getattr(service, "serial_hw", None) if service else None
        return DdAckRetrySender.send_with_retry(
            serial_hw=serial_hw,
            send_callable=lambda: bool(send_callable()),
            logger=self._logger,
            desc=desc,
            timeout_sec=self.ACK_TIMEOUT_SEC,
            max_resends=self.MAX_RESENDS,
        )
