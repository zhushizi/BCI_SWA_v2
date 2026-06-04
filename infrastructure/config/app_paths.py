"""应用根目录与 config.json 中可执行文件路径解析（开发 / PyInstaller 打包通用）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, Optional

# 本机首次登录标记（空文件，与 config.json 分离）
LOCAL_DEVICE_MARKER_FILENAME = "local_device.initialized"

_EXE_PATH_KEYS = frozenset(
    {
        "decoder_exe",
        "ssmvep_exe_up",
        "ssvep_exe_up",
        "mi_exe_up",
        "websocket_exe",
    }
)


def _frozen_bundle_roots() -> list[Path]:
    """PyInstaller onedir 下可能放置 datas 的根目录（exe 旁或 _internal）。"""
    exe_dir = Path(sys.executable).resolve().parent
    roots: list[Path] = [exe_dir]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        mp = Path(meipass).resolve()
        if mp not in roots:
            roots.append(mp)
    internal = exe_dir / "_internal"
    if internal.is_dir() and internal not in roots:
        roots.append(internal)
    return roots


def application_base_dir() -> Path:
    """项目根（开发）；打包后优先含 runtime/ 的 bundle 根（多为 _internal）。"""
    if getattr(sys, "frozen", False):
        for base in _frozen_bundle_roots():
            if (base / "runtime").is_dir():
                return base
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    return Path(__file__).resolve().parent


def local_device_marker_path() -> Path:
    return config_dir() / LOCAL_DEVICE_MARKER_FILENAME


def is_local_device_initialized() -> bool:
    return local_device_marker_path().is_file()


def mark_local_device_initialized() -> None:
    path = local_device_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def resolve_app_path(path: Optional[str]) -> Optional[str]:
    """将 config 中的相对路径解析为绝对路径；已是绝对路径则原样返回。"""
    raw = str(path or "").strip()
    if not raw:
        return None
    p = Path(raw)
    if p.is_absolute():
        return str(p) if p.is_file() else str(p.resolve())

    if getattr(sys, "frozen", False):
        for base in _frozen_bundle_roots():
            candidate = (base / p).resolve()
            if candidate.is_file():
                return str(candidate)
        return str((application_base_dir() / p).resolve())

    return str((application_base_dir() / p).resolve())


def resolve_config_exe_paths(data: Mapping[str, Any]) -> dict[str, Any]:
    """解析配置里与 runtime 相关的 *_exe 路径，供启动子进程使用。"""
    out = dict(data)
    for key in _EXE_PATH_KEYS:
        if key not in out:
            continue
        value = out.get(key)
        if value is None:
            continue
        resolved = resolve_app_path(str(value))
        if resolved is not None:
            out[key] = resolved
    return out
