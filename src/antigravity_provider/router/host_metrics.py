"""Hermes Hub — System Host Metrics Service using psutil.

Collects empirical host hardware indicators:
- CPU utilization percentage (warmed up on initial sample)
- RAM (used/total MB, percent)
- Disk (used/total GB, percent for system root)
- Network live speed (Mbps) and cumulative I/O counters (bytes sent/recv since boot)
Source: 'host_measurement'.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("hermes.router.host_metrics")

# Prime psutil internal CPU timer on module import
try:
    import psutil
    psutil.cpu_percent(interval=None)
except Exception:
    pass


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
    net_speed_mbps: Optional[float] = None       # Live total network speed (Mbps) between samples
    net_sent_mbps: Optional[float] = None        # Live upload speed (Mbps)
    net_recv_mbps: Optional[float] = None        # Live download speed (Mbps)
    net_bytes_sent: Optional[int] = None         # Cumulative bytes sent since host boot
    net_bytes_recv: Optional[int] = None         # Cumulative bytes received since host boot
    source: str = "host_measurement"
    has_data: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HostMetricsService:
    """Safe, non-blocking collector for host performance indicators."""

    _last_cpu_time: float = 0.0
    _last_net_time: float = 0.0
    _last_net_bytes_sent: int = 0
    _last_net_bytes_recv: int = 0
    _lock = threading.Lock()

    @classmethod
    def reset_state(cls) -> None:
        """Reset internal sampling baselines (useful for testing)."""
        with cls._lock:
            cls._last_cpu_time = 0.0
            cls._last_net_time = 0.0
            cls._last_net_bytes_sent = 0
            cls._last_net_bytes_recv = 0

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
            with cls._lock:
                if cls._last_cpu_time == 0.0:
                    # Warm up CPU baseline with short interval to prevent cold start 0.0%
                    cpu = psutil.cpu_percent(interval=0.05)
                    cls._last_cpu_time = time.time()
                else:
                    cpu = psutil.cpu_percent(interval=None)
                    cls._last_cpu_time = now

            mem = psutil.virtual_memory()

            # Disk usage of root drive / partition
            root_path = os.path.abspath(os.sep)
            disk = psutil.disk_usage(root_path)

            net = None
            net_speed_mbps = None
            net_sent_mbps = None
            net_recv_mbps = None

            try:
                net = psutil.net_io_counters()
                if net:
                    with cls._lock:
                        if cls._last_net_time > 0.0 and now > cls._last_net_time:
                            dt = now - cls._last_net_time
                            if dt >= 0.05:  # Valid time delta
                                d_sent = max(0, net.bytes_sent - cls._last_net_bytes_sent)
                                d_recv = max(0, net.bytes_recv - cls._last_net_bytes_recv)
                                # Convert bytes/sec to Megabits/sec (Mbps)
                                net_sent_mbps = round((d_sent * 8.0) / (dt * 1_000_000.0), 2)
                                net_recv_mbps = round((d_recv * 8.0) / (dt * 1_000_000.0), 2)
                                net_speed_mbps = round(((d_sent + d_recv) * 8.0) / (dt * 1_000_000.0), 2)

                        cls._last_net_time = now
                        cls._last_net_bytes_sent = net.bytes_sent
                        cls._last_net_bytes_recv = net.bytes_recv
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
                net_speed_mbps=net_speed_mbps,
                net_sent_mbps=net_sent_mbps,
                net_recv_mbps=net_recv_mbps,
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
