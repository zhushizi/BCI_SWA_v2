from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from infrastructure.hardware import SerialHardware
from service.business.protocol.stim_frame import StimFrame


class _Channel(Enum):
    LEFT = "left"
    RIGHT = "right"
    UNKNOWN = "unknown"

    @classmethod
    def from_value(cls, value: Optional[str]) -> "_Channel":
        if value is None:
            return cls.UNKNOWN
        v = str(value).lower()
        if v == "left":
            return cls.LEFT
        if v == "right":
            return cls.RIGHT
        return cls.UNKNOWN


class StimTestService:
    """
    电刺激/治疗指令服务（业务层）。

    说明：
    - 这里承载原 `HardwareTreatmentService` 的协议构帧与发送逻辑（已迁移到本文件）
    - 上层（App/UI）只调用本服务暴露的用例接口，不直接依赖串口/协议细节
    """

    # 协议常量
    FRAME_HEADER = StimFrame.FRAME_HEADER
    FRAME_LENGTH = StimFrame.FRAME_LENGTH
    RESERVED_BYTE = StimFrame.RESERVED_BYTE
    RESERVED_LEFT = StimFrame.RESERVED_LEFT
    RESERVED_RIGHT = StimFrame.RESERVED_RIGHT
    FRAME_DATA_SIZE = StimFrame.FRAME_DATA_SIZE

    # 帧类型
    FRAME_TYPE_COMMAND = StimFrame.FRAME_TYPE_COMMAND
    FRAME_TYPE_DATA = StimFrame.FRAME_TYPE_DATA

    # 命令类型
    CMD_START_TREATMENT = 0x01  # 开始治疗
    CMD_STOP_TREATMENT = 0x10   # 停止治疗

    # 方案位固定为 0x00（保留常量供上层兼容传参）
    SCHEME_FIXED = 0x00

    def __init__(self, serial_hardware: SerialHardware):
        self.serial_hw = serial_hardware
        self.logger = logging.getLogger(__name__)
        self.log_send_enabled = False  # 不打印发送给 hardware 的指令

    # --------- 串口管理（供应用层调用） ---------
    def list_available_ports(self) -> list[str]:
        try:
            return [port.device for port in SerialHardware.list_available_ports()]
        except Exception as exc:
            self.logger.warning("获取串口列表失败: %s", exc)
            return []

    def switch_port(self, next_port: str) -> bool:
        """切换串口端口并重连。"""
        port = str(next_port or "").strip()
        if not port:
            return False
        if self.serial_hw.port == port and self.serial_hw.is_connected():
            return True
        try:
            self.serial_hw.disconnect()
        except Exception:
            pass
        self.serial_hw.port = port
        return bool(self.serial_hw.connect())

    # --------- 兼容接口（原 HardwareTreatmentService） ---------
    def start_treatment(self) -> bool:
        """开始治疗（发送命令帧）"""
        return self._send_command(self.CMD_START_TREATMENT, desc="开始治疗命令")

    def start_treatment_channel(self, channel: str) -> bool:
        """
        按通道语义发送开始治疗命令帧。

        下位机约定：开始命令的保留位固定为 0x00（与数据帧参数下发的 0x0A/0x0B 区分）。
        channel 仅用于日志，不参与构帧。
        """
        return self._send_command(
            self.CMD_START_TREATMENT,
            reserved_byte=self.RESERVED_BYTE,
            desc=f"开始治疗命令 channel={channel}, reserved=0x{self.RESERVED_BYTE:02X}",
        )

    def start_treatment_dual(self) -> bool:
        """双通道开始：单帧保留位 0x00，避免重复发送两帧相同开始命令。"""
        return self.start_treatment()

    def stop_treatment(self) -> bool:
        """停止治疗（发送命令帧）"""
        return self._send_command(self.CMD_STOP_TREATMENT, desc="停止治疗命令")

    def stop_treatment_channel(self, channel: str) -> bool:
        """
        按通道语义发送停止治疗命令帧。

        下位机约定：停止命令的保留位固定为 0x00（与数据帧参数下发的 0x0A/0x0B 区分）。
        channel 仅用于日志，不参与构帧。
        """
        return self._send_command(
            self.CMD_STOP_TREATMENT,
            reserved_byte=self.RESERVED_BYTE,
            desc=f"停止治疗命令 channel={channel}, reserved=0x{self.RESERVED_BYTE:02X}",
        )

    def stop_treatment_dual(self) -> bool:
        """双通道停止：单帧保留位 0x00，避免重复发送两帧相同停止命令。"""
        return self.stop_treatment()

    def set_treatment_params(
        self,
        scheme: int,
        frequency: int,
        current: int,
        channel: Optional[str] = None,
        time_byte: Optional[int] = None,
    ) -> bool:
        """
        设置治疗参数（发送数据帧）

        scheme: 固定 0x00（参数保留仅为兼容）
        frequency: 脉冲宽度档位 0x00~0x1B
        current: 0~0x32
        """
        # 参数验证
        if not (0 <= frequency <= 0x1B):
            raise ValueError(f"脉冲宽度档位无效: {frequency}，应为 0x00~0x1B")
        if not (0 <= current <= 0x32):
            raise ValueError(f"电流无效: {current}，应为 0~50 (0x00~0x32)")

        reserved = self._channel_reserved(channel) if channel else self.RESERVED_BYTE
        time_desc = f", time=0x{int(time_byte):02X}" if time_byte is not None else ""
        return self._send_data(
            scheme=self.SCHEME_FIXED,
            frequency=frequency,
            current=current,
            reserved_byte=reserved,
            time_byte=time_byte,
            desc=f"治疗参数 方案=0x00, 脉冲宽度={frequency}, 电流={current}, reserved=0x{reserved:02X}{time_desc}",
        )

    def start_dual(self) -> bool:
        """电刺激测试：双通道开始（兼容旧接口）"""
        return self.start_treatment_dual()

    def stop_dual(self) -> bool:
        """电刺激测试：双通道停止（兼容旧接口）"""
        return self.stop_treatment_dual()

    def set_params(
        self,
        scheme: int,
        frequency: int,
        current: int,
        channel: Optional[str] = None,
        time_byte: Optional[int] = None,
    ) -> bool:
        """电刺激测试：设置参数（兼容旧接口）"""
        return self.set_treatment_params(
            scheme=scheme,
            frequency=frequency,
            current=current,
            channel=channel,
            time_byte=time_byte,
        )

    # ------------------ 协议构帧 ------------------
    def _build_command_frame(self, command: int, reserved_byte: int = None) -> bytes:
        """
        帧格式：
        [帧头(2)] [长度(1)] [保留(1)] [帧类型(1)] [命令(1)] [保留(5)] [校验和(2)]
        """
        rb = self.RESERVED_BYTE if reserved_byte is None else reserved_byte
        return StimFrame.build_command(command, rb)

    def _build_data_frame(
        self,
        scheme: int,
        frequency: int,
        current: int,
        reserved_byte: int = None,
        time_byte: Optional[int] = None,
    ) -> bytes:
        """
        帧格式：
        [帧头(2)] [长度(1)] [保留(1)] [帧类型(1)] [方案(1)] [频率(1)] [电流(1)] [时间(1)] [保留(2)] [校验和(2)]
        """
        rb = self.RESERVED_BYTE if reserved_byte is None else reserved_byte
        return StimFrame.build_data(
            scheme=scheme,
            frequency=frequency,
            current=current,
            reserved_byte=rb,
            time_byte=time_byte,
        )

    def _channel_reserved(self, channel: Optional[str]) -> int:
        ch = _Channel.from_value(channel)
        if ch is _Channel.LEFT:
            return self.RESERVED_LEFT
        if ch is _Channel.RIGHT:
            return self.RESERVED_RIGHT
        return self.RESERVED_BYTE

    def _calculate_checksum(self, data: bytearray) -> bytes:
        return StimFrame._calculate_checksum(data)

    # ------------------ 内部工具 ------------------
    def _log_send(self, packet: bytes, success: bool, desc: str = "") -> None:
        if not self.log_send_enabled:
            return
        status = "成功" if success else "失败"
        hex_str = packet.hex()
        if desc:
            self.logger.info(f"[发送{status}] {desc} | data={hex_str}")
        else:
            self.logger.info(f"[发送{status}] data={hex_str}")

    def _send_command(self, command: int, reserved_byte: int = None, desc: str = "") -> bool:
        packet = self._build_command_frame(command, reserved_byte=reserved_byte)
        success = self.serial_hw.send_data(packet)
        self._log_send(packet, success, desc=desc)
        return success

    def _send_data(
        self,
        *,
        scheme: int,
        frequency: int,
        current: int,
        reserved_byte: int,
        time_byte: Optional[int],
        desc: str,
    ) -> bool:
        packet = self._build_data_frame(
            scheme,
            frequency,
            current,
            reserved_byte=reserved_byte,
            time_byte=time_byte,
        )
        success = self.serial_hw.send_data(packet)
        self._log_send(packet, success, desc=desc)
        return success
