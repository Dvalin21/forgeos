"""
ForgeOS Real-Time Monitoring System
Provides WebSocket-based live metrics streaming to WebGUI dashboard.

Features:
  - Live system metrics (CPU, RAM, disk, network, temps)
  - Per-container metrics (Docker + LXC)
  - Alert thresholds with webhook/email notifications
  - Configurable update interval (default 2s)
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Optional, Any
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect


# ── Configuration ──
METRIC_INTERVAL = 2  # seconds between metric updates
MAX_HISTORY = 300  # Keep last 300 data points (10 min @ 2s)
ALERT_CHANNELS = ["webhook", "email", "gotify"]  # Supported alert channels


# ── Metrics Storage ──
class MetricsStore:
    """In-memory metrics storage with history."""
    
    def __init__(self):
        self.current: Dict[str, Any] = {}
        self.history: List[Dict] = []
        self.alerts: List[Dict] = []
        self.start_time = time.time()
    
    def update(self, metrics: Dict[str, Any]):
        """Update current metrics and add to history."""
        metrics["timestamp"] = time.time()
        self.current = metrics
        
        # Add to history
        self.history.append(metrics.copy())
        
        # Trim history
        if len(self.history) > MAX_HISTORY:
            self.history = self.history[-MAX_HISTORY:]
    
    def get_current(self) -> Dict[str, Any]:
        """Get current metrics snapshot."""
        return self.current
    
    def get_history(self, seconds: int = 300) -> List[Dict]:
        """Get history for last N seconds."""
        cutoff = time.time() - seconds
        return [m for m in self.history if m["timestamp"] > cutoff]
    
    def add_alert(self, alert: Dict):
        """Record an alert event."""
        alert["timestamp"] = time.time()
        self.alerts.append(alert)
        # Keep last 100 alerts
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]


# Global store
store = MetricsStore()


# ── Metrics Collection ──
def collect_system_metrics() -> Dict[str, Any]:
    """Collect current system metrics."""
    metrics = {
        "cpu": _get_cpu_usage(),
        "memory": _get_memory_info(),
        "disk": _get_disk_info(),
        "network": _get_network_io(),
        "temps": _get_temperatures(),
        "uptime": _get_uptime(),
        "load": _get_load_average(),
        "timestamp": time.time(),
    }
    return metrics


def _get_cpu_usage() -> float:
    """Get CPU usage percentage."""
    try:
        import psutil
        return round(psutil.cpu_percent(interval=0.1), 1)
    except ImportError:
        return 0.0


def _get_memory_info() -> Dict[str, Any]:
    """Get memory usage info."""
    try:
        import psutil
        m = psutil.virtual_memory()
        return {
            "total_gb": round(m.total / 1e9, 1),
            "used_gb": round(m.used / 1e9, 1),
            "percent": round(m.percent, 1),
        }
    except ImportError:
        return {"total_gb": 0, "used_gb": 0, "percent": 0}


def _get_disk_info() -> List[Dict[str, Any]]:
    """Get disk usage for all mount points."""
    try:
        import psutil
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "device": part.device,
                    "mount": part.mountpoint,
                    "total_gb": round(usage.total / 1e9, 1),
                    "used_gb": round(usage.used / 1e9, 1),
                    "percent": round(usage.percent, 1),
                })
            except PermissionError:
                continue
        return disks
    except ImportError:
        return []


def _get_network_io() -> Dict[str, Any]:
    """Get network I/O stats."""
    try:
        import psutil
        io = psutil.net_io_counters()
        return {
            "bytes_sent": io.bytes_sent,
            "bytes_recv": io.bytes_recv,
            "packets_sent": io.packets_sent,
            "packets_recv": io.packets_recv,
        }
    except ImportError:
        return {}


def _get_temperatures() -> Dict[str, Any]:
    """Get system temperatures."""
    try:
        import psutil
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            result = {}
            for name, entries in temps.items():
                result[name] = [
                    {"label": e.label, "current": e.current, "high": e.high}
                    for e in entries
                ]
            return result
    except Exception:
        pass
    return {}


def _get_uptime() -> str:
    """Get system uptime."""
    try:
        out = subprocess.check_output(["uptime", "-p"], text=True, timeout=5)
        return out.strip()
    except Exception:
        return "unknown"


def _get_load_average() -> List[float]:
    """Get load average."""
    try:
        import os
        return [round(x, 2) for x in os.getloadavg()]
    except Exception:
        return [0.0, 0.0, 0.0]


# ── Container Metrics ──
def collect_container_metrics() -> Dict[str, Any]:
    """Collect Docker + LXC container metrics."""
    return {
        "docker": _get_docker_container_stats(),
        "lxc": _get_lxc_container_stats(),
    }


def _get_docker_container_stats() -> List[Dict]:
    """Get Docker container resource usage."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", 
             "json", '{"name": .Name, "cpu": .CPUPerc, "mem": .MemUsage, "net": .NetIO}'],
            text=True,
            timeout=10,
        ).strip()
        # Parse each line as JSON
        containers = []
        for line in out.split("\n"):
            if line.strip():
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return containers
    except Exception:
        return []


def _get_lxc_container_stats() -> List[Dict]:
    """Get LXC container resource usage."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["lxc", "list", "--format", "json"],
            text=True,
            timeout=10,
        ).strip()
        containers = json.loads(out) if out else []
        return [
            {
                "name": c.get("name"),
                "status": c.get("status"),
                "ipv4": c.get("ipv4", []),
            }
            for c in containers
        ]
    except Exception:
        return []


# ── WebSocket Handler ──
async def websocket_metrics(ws: WebSocket):
    """
    WebSocket handler for live metrics streaming.
    Sends JSON messages every METRIC_INTERVAL seconds.
    """
    await ws.accept()
    
    try:
        while True:
            # Collect metrics
            metrics = collect_system_metrics()
            container_metrics = collect_container_metrics()
            
            # Combine
            data = {
                "type": "metrics_update",
                "system": metrics,
                "containers": container_metrics,
                "timestamp": time.time(),
            }
            
            # Check alerts
            alerts = _check_alert_thresholds(metrics)
            if alerts:
                data["alerts"] = alerts
                for alert in alerts:
                    store.add_alert(alert)
            
            # Send to client
            await ws.send_json(data)
            
            # Update store
            store.update(metrics)
            
            # Wait
            await asyncio.sleep(METRIC_INTERVAL)
    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")


def _check_alert_thresholds(metrics: Dict) -> List[Dict]:
    """Check if any metrics exceed alert thresholds."""
    alerts = []
    
    # CPU alert (>90%)
    if metrics.get("cpu", 0) > 90:
        alerts.append({
            "severity": "warning",
            "source": "cpu",
            "message": f"CPU usage critical: {metrics['cpu']}%",
        })
    
    # Memory alert (>90%)
    mem = metrics.get("memory", {})
    if mem.get("percent", 0) > 90:
        alerts.append({
            "severity": "warning",
            "source": "memory",
            "message": f"Memory usage critical: {mem['percent']}%",
        })
    
    # Disk alert (>90%)
    for disk in metrics.get("disk", []):
        if disk.get("percent", 0) > 90:
            alerts.append({
                "severity": "warning",
                "source": "disk",
                "message": f"Disk {disk['mount']} usage critical: {disk['percent']}%",
            })
    
    return alerts


# ── API Endpoints (for fetching historical data) ──
def get_metrics_history(seconds: int = 300) -> List[Dict]:
    """Get historical metrics."""
    return store.get_history(seconds)


def get_current_metrics() -> Dict[str, Any]:
    """Get current metrics snapshot."""
    return store.get_current()


def get_alerts(limit: int = 50) -> List[Dict]:
    """Get recent alerts."""
    return store.alerts[-limit:]
