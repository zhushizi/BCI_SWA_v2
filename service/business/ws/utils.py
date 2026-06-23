from __future__ import annotations

from typing import Optional

from service.business.config.config_service import ConfigService


def load_countdown_minutes() -> Optional[float]:
    try:
        service = ConfigService()
        value = service.get("Countdown_time_minutes")
        return float(value) if value is not None else None
    except Exception:
        return None


def load_treat_ok_timeout_sec(default: float = 6.0) -> float:
    """训练模式下等待 Treat_OK 的超时秒数；超时后主动发送 main.exo_action_complete。"""
    try:
        service = ConfigService()
        value = service.get("treat_ok_timeout_sec", default)
        if value is None:
            return float(default)
        timeout = float(value)
        return timeout if timeout > 0 else float(default)
    except Exception:
        return float(default)
