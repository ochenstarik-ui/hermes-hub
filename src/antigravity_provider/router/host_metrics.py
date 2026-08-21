"""Hermes Hub — System Host Metrics Service using psutil.

Collects empirical host hardware indicators:
- CPU utilization percentage
- RAM (used/total MB, percent)
- Disk (used/total GB, percent for system root)
- Network I/O (bytes sent/recv)
Source: 'host_measurement'.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("hermes.router.host_metrics")


@dataclass
class HostMetricsSnapshot:
    """Empirical hardware telemetry of the host system."""
    timestamp: float
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    memory_used_mb: Optional[float] = None
    memory_total_mb: Optional[float] = None
    disk_percent: Optional[float] = None
    disk_used_gb: Optional[float] = None
    disk_total_gb: Optional[float] = None
    net_bytes_sent: Optional[int] = None
    net_bytes_recv: Optional[int] = None
    source: str = "host_measurement"
    has_data: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HostMetricsService:
    """Safe, non-blocking collector for host performance indicators."""

    @classmethod
    def collect(cls) -> HostMetricsSnapshot:
        now = time.time()
        try:
            import psutil
        except ImportError:
            return HostMetricsSnapshot(
                timestamp=now,
                source="host_measurement",
                has_data=False,
            )

        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()

            # Disk usage of root drive / partition
            root_path = os.path.abspath(os.sep)
            disk = psutil.disk_usage(root_path)

            net = None
            try:
                net = psutil.net_io_counters()
            except Exception:
                pass

            return HostMetricsSnapshot(
                timestamp=now,
                cpu_percent=round(float(cpu), 1),
                memory_percent=round(float(mem.percent), 1),
                memory_used_mb=round(float(mem.used) / (1024 * 1024), 1),
                memory_total_mb=round(float(mem.total) / (1024 * 1024), 1),
                disk_percent=round(float(disk.percent), 1),
                disk_used_gb=round(float(disk.used) / (1024 * 1024 * 1024), 1),
                disk_total_gb=round(float(disk.total) / (1024 * 1024 * 1024), 1),
                net_bytes_sent=int(net.bytes_sent) if net else None,
                net_bytes_recv=int(net.bytes_recv) if net else None,
                source="host_measurement",
                has_data=True,
            )
        except Exception as exc:
            logger.debug("Failed to collect host metrics via psutil: %s", exc)
            return HostMetricsSnapshot(
                timestamp=now,
                source="host_measurement",
                has_data=False,
            )
