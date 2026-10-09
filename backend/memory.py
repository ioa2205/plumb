"""Physical memory and commit charge, read from Windows (``GlobalMemoryStatusEx``)."""

import ctypes
import sys
from dataclasses import dataclass

import psutil

GIB = 1024**3


@dataclass(frozen=True)
class MemoryStatus:
    total_bytes: int
    available_bytes: int  # free plus standby: what a new allocation can get without paging
    commit_limit_bytes: int
    commit_used_bytes: int


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def read_memory() -> MemoryStatus:
    if sys.platform != "win32":
        vm = psutil.virtual_memory()
        return MemoryStatus(vm.total, vm.available, 0, 0)
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return MemoryStatus(
        total_bytes=status.ullTotalPhys,
        available_bytes=status.ullAvailPhys,
        commit_limit_bytes=status.ullTotalPageFile,
        commit_used_bytes=status.ullTotalPageFile - status.ullAvailPageFile,
    )
