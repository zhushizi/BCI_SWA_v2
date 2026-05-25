"""
硬件应用层（Application Layer）

- 对 UI 暴露“开始/停止治疗”等用例接口，避免 UI 直接依赖基础设施/业务细节
"""

from __future__ import annotations

import logging
from typing import Optional

from service.business.hardware.stim_test_service import StimTestService

class HardwareApp:
    """
    硬件应用层：UI 只和此类交互
    """

    def __init__(self, hardware_service: StimTestService):
        self.hardware_service = hardware_service
        self.logger = logging.getLogger(__name__)

    # --------- 用例：治疗控制 ---------
    def start_treatment_dual(self) -> bool:
        """双通道场景开始：业务层发送保留位为 0x00 的开始命令帧（单帧）。"""
        return self.hardware_service.start_treatment_dual()

    def stop_treatment_dual(self) -> bool:
        """双通道场景停止：业务层发送保留位为 0x00 的停止命令帧（单帧）。"""
        return self.hardware_service.stop_treatment_dual()

    def set_treatment_params(self, scheme: int, frequency: int, current: int, channel: Optional[str] = None) -> bool:
        """
        用例：下发治疗参数

        UI 只调用此方法，不直接依赖 business/service 层。
        """
        return self.hardware_service.set_treatment_params(
            scheme=scheme,
            frequency=frequency,
            current=current,
            channel=channel,
        )

    # --------- 用例：串口端口管理 ---------
    def list_available_ports(self) -> list[str]:
        return self.hardware_service.list_available_ports()

    def set_nes_port(self, next_port: str) -> bool:
        """切换 NES 串口端口。"""
        return self.hardware_service.switch_port(next_port)
