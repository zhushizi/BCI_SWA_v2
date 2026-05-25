from __future__ import annotations

import logging
from threading import Event
from typing import Any, Callable


class DdAckRetrySender:
    """串口 DD 应答重发工具：统一“发送-等待应答-超时重发”流程。"""

    @staticmethod
    def contains_dd_ack_frame(
        data: bytes,
        ack_frame_len: int = 13,
        ack_frame_type: int = 0xDD,
    ) -> bool:
        if len(data) < int(ack_frame_len):
            return False
        frame_len = int(ack_frame_len)
        last_start = len(data) - frame_len
        for i in range(last_start + 1):
            if data[i] != 0x55 or data[i + 1] != 0xAA:
                continue
            if data[i + 2] != 0x0D:
                continue
            if data[i + 4] == int(ack_frame_type):
                return True
        return False

    @classmethod
    def send_with_retry(
        cls,
        serial_hw: Any,
        send_callable: Callable[[], bool],
        logger: logging.Logger,
        desc: str,
        timeout_sec: float = 0.5,
        max_resends: int = 5,
        ack_frame_len: int = 13,
        ack_frame_type: int = 0xDD,
        recv_buffer_max: int = 256,
    ) -> bool:
        if serial_hw is None or not hasattr(serial_hw, "add_data_received_callback"):
            return bool(send_callable())

        recv_buffer = bytearray()
        ack_event = Event()

        def on_serial_data(data: bytes) -> None:
            if not data:
                return
            recv_buffer.extend(data)
            if len(recv_buffer) > int(recv_buffer_max):
                del recv_buffer[:-int(recv_buffer_max)]
            if cls.contains_dd_ack_frame(
                bytes(recv_buffer),
                ack_frame_len=ack_frame_len,
                ack_frame_type=ack_frame_type,
            ):
                ack_event.set()

        serial_hw.add_data_received_callback(on_serial_data)
        try:
            total_attempts = 1 + max(0, int(max_resends))
            ack_event.clear()
            for attempt in range(total_attempts):
                if ack_event.is_set():
                    return True
                if not bool(send_callable()):
                    logger.warning("%s 下发失败: attempt=%s/%s", desc, attempt + 1, total_attempts)
                if ack_event.wait(float(timeout_sec)):
                    return True
            logger.warning("%s 超时未收到 DD 应答（已重发 %s 次）", desc, max(0, int(max_resends)))
            return False
        finally:
            if hasattr(serial_hw, "remove_data_received_callback"):
                serial_hw.remove_data_received_callback(on_serial_data)
