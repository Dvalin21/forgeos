"""
ForgeOS Audit Logging Module
Logs all security events, privileged actions, and API calls for compliance/debugging.

Storage: /var/log/forgeos/audit.log (JSON format, rotated daily)
"""

import json
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any


# ── Configuration ──
AUDIT_LOG_DIR = Path("/var/log/forgeos")
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit.log"
MAX_LOG_SIZE = 50 * 1024 * 1024  # 50MB rotation


# ── Event Types ──
class AuditEventType:
    # Authentication events
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOGOUT = "auth.logout"
    TOTP_VERIFY_SUCCESS = "auth.totp.success"
    TOTP_VERIFY_FAILURE = "auth.totp.failure"
    TOTP_ENABLE = "auth.totp.enable"
    TOTP_DISABLE = "auth.totp.disable"
    PASSWORD_CHANGE = "auth.password.change"
    
    # OAuth events
    OAUTH_LINK = "auth.oauth.link"
    OAUTH_UNLINK = "auth.oauth.unlink"
    
    # API key events
    APIKEY_CREATE = "auth.apikey.create"
    APIKEY_REVOKE = "auth.apikey.revoke"
    
    # Container operations
    CONTAINER_START = "container.start"
    CONTAINER_STOP = "container.stop"
    CONTAINER_RESTART = "container.restart"
    CONTAINER_DELETE = "container.delete"
    CONTAINER_EXEC = "container.exec"
    
    # File operations
    FILE_UPLOAD = "file.upload"
    FILE_DELETE = "file.delete"
    FILE_DOWNLOAD = "file.download"
    
    # Settings changes
    SETTINGS_CHANGE = "settings.change"
    
    # System events
    SYSTEM_BACKUP = "system.backup"
    SYSTEM_RESTORE = "system.restore"
    SYSTEM_UPDATE = "system.update"


# ── Audit Logger ──
def _ensure_log_dir():
    """Ensure audit log directory exists."""
    if not AUDIT_LOG_DIR.exists():
        AUDIT_LOG_DIR.mkdir(parents=True, mode=0o750)


def _rotate_log_if_needed():
    """Rotate log file if it exceeds MAX_LOG_SIZE."""
    if AUDIT_LOG_FILE.exists() and AUDIT_LOG_FILE.stat().st_size > MAX_LOG_SIZE:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = AUDIT_LOG_DIR / f"audit_{timestamp}.log"
        AUDIT_LOG_FILE.rename(backup)


def log_event(
    event_type: str,
    username: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    success: bool = True,
):
    """
    Log an audit event.
    
    Args:
        event_type: Type of event (use AuditEventType constants)
        username: Username associated with event
        ip_address: Client IP address
        user_agent: Client user agent string
        details: Additional key-value details about the event
        success: Whether the action succeeded
    """
    _ensure_log_dir()
    _rotate_log_if_needed()
    
    event = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,
        "username": username,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "success": success,
        "details": details or {},
    }
    
    # Append to log file
    with open(AUDIT_LOG_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")
    
    # Also print to stdout for development
    if os.environ.get("FORGEOS_DEBUG"):
        print(f"[AUDIT] {event_type}: {username} - {success}")


def get_audit_logs(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    event_type: Optional[str] = None,
    username: Optional[str] = None,
    limit: int = 100,
) -> list:
    """
    Retrieve audit logs with optional filtering.
    
    Args:
        start_time: ISO format start time filter
        end_time: ISO format end time filter
        event_type: Filter by event type
        username: Filter by username
        limit: Maximum number of records to return
        
    Returns:
        List of audit event dictionaries
    """
    if not AUDIT_LOG_FILE.exists():
        return []
    
    results = []
    with open(AUDIT_LOG_FILE, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                
                # Apply filters
                if start_time and event["timestamp"] < start_time:
                    continue
                if end_time and event["timestamp"] > end_time:
                    continue
                if event_type and event["event_type"] != event_type:
                    continue
                if username and event["username"] != username:
                    continue
                
                results.append(event)
                
                if len(results) >= limit:
                    break
            except json.JSONDecodeError:
                continue
    
    return results


def export_audit_logs(format: str = "json") -> str:
    """
    Export audit logs in specified format.
    
    Args:
        format: "json" or "csv"
        
    Returns:
        Formatted string of audit logs
    """
    logs = get_audit_logs(limit=10000)
    
    if format == "csv":
        import csv
        from io import StringIO
        
        output = StringIO()
        if logs:
            writer = csv.DictWriter(output, fieldnames=logs[0].keys())
            writer.writeheader()
            writer.writerows(logs)
        return output.getvalue()
    else:  # JSON
        return json.dumps(logs, indent=2)
