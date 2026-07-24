"""Apply-with-confirmation rollback engine for network changes.

This host runs ifupdown (no `netplan try` to lean on), and the interface the
web UI answers on (ens18) is the one most likely to be reconfigured — so a bad
address change would silently drop a headless box off the network with no way
back in. This engine is the safeguard:

    snapshot current config  ->  apply new config  ->  arm a revert timer
        -> client reconfirms from the new address within the window  -> commit
        -> OR the timer fires (client never made it back)            -> revert

It is deliberately GENERIC and side-effect-free on its own: the caller injects
`snapshot`, `apply`, and `revert` callables. That lets the engine — the part
that must not have bugs — be unit-tested with in-memory fakes and a simulated
"client never confirms" path, with zero real `ifreload`/`ip` calls. The real
network wiring plugs in when the write endpoints land.

State machine (one pending change at a time; a second apply is rejected while
one is armed, because two overlapping reverts would corrupt the config):

    IDLE ──apply()──▶ ARMED ──confirm(token)──▶ IDLE (committed)
                       │
                       └──timer fires / cancel()──▶ IDLE (reverted)
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("forgeos-api")


@dataclass
class _Pending:
    token: str
    snapshot: Any                 # opaque handle returned by the snapshot fn
    label: str                    # human description e.g. "ens18 -> static 10.0.0.5/24"
    deadline: float               # monotonic time the timer will fire
    timer: threading.Timer
    reverted: bool = field(default=False)
    committed: bool = field(default=False)


class RollbackError(RuntimeError):
    """Raised when apply/confirm is called in an invalid state."""


class RollbackEngine:
    """Serialises network changes behind an apply→confirm→auto-revert timer.

    Thread-safe: the revert timer fires on a background thread and races the
    confirm/cancel request; all state transitions hold `_lock`.
    """

    def __init__(
        self,
        snapshot: Callable[[], Any],
        apply: Callable[[Any], None],
        revert: Callable[[Any], None],
        window_seconds: int = 60,
    ) -> None:
        # snapshot() -> handle ; apply(new) ; revert(handle)
        self._snapshot = snapshot
        self._apply = apply
        self._revert = revert
        self._window = int(window_seconds)
        self._lock = threading.Lock()
        self._pending: Optional[_Pending] = None
        # keeps the last resolution so the UI/tests can inspect what happened
        self._last_result: Optional[str] = None   # "committed" | "reverted" | None

    # ── introspection ──
    @property
    def window_seconds(self) -> int:
        return self._window

    def status(self) -> dict:
        """Current engine state — safe to call any time."""
        with self._lock:
            p = self._pending
            if p is None:
                return {"pending": False, "last_result": self._last_result}
            remaining = max(0, int(round(p.deadline - time.monotonic())))
            return {
                "pending": True,
                "label": p.label,
                "seconds_remaining": remaining,
                "last_result": self._last_result,
            }

    def pending_token(self) -> Optional[str]:
        """Token of the current pending change, if any (admin-only callers)."""
        with self._lock:
            return self._pending.token if self._pending else None

    # ── the three transitions ──
    def apply(self, new_config: Any, label: str) -> dict:
        """Snapshot, apply `new_config`, and arm the revert timer.

        Returns a confirm token + the window. Raises RollbackError if a change
        is already pending (only one at a time).
        """
        with self._lock:
            if self._pending is not None:
                raise RollbackError("a network change is already pending confirmation")
            snap = self._snapshot()
            # Apply BEFORE arming so an apply failure never leaves a dangling
            # timer. If apply raises, we've taken the snapshot but changed
            # nothing to arm against — surface the error, stay IDLE.
            try:
                self._apply(new_config)
            except Exception as e:
                # best-effort restore in case apply was partial
                try:
                    self._revert(snap)
                except Exception:
                    pass
                raise RollbackError(f"apply failed, restored previous config: {e}") from e

            token = secrets.token_urlsafe(16)
            timer = threading.Timer(self._window, self._on_timeout, args=(token,))
            timer.daemon = True
            self._pending = _Pending(
                token=token,
                snapshot=snap,
                label=label,
                deadline=time.monotonic() + self._window,
                timer=timer,
            )
            self._last_result = None
            timer.start()
            return {"token": token, "window_seconds": self._window, "label": label}

    def confirm(self, token: str) -> dict:
        """Client reached us on the new config — cancel the revert, commit."""
        with self._lock:
            p = self._pending
            if p is None:
                raise RollbackError("no network change is pending")
            if not secrets.compare_digest(token, p.token):
                # wrong/stale token: do NOT touch the pending change
                raise RollbackError("invalid confirmation token")
            p.timer.cancel()
            p.committed = True
            self._pending = None
            self._last_result = "committed"
            return {"result": "committed", "label": p.label}

    def cancel(self) -> dict:
        """Manually revert now (user clicked 'discard', or an explicit rollback)."""
        with self._lock:
            p = self._pending
            if p is None:
                raise RollbackError("no network change is pending")
            p.timer.cancel()
            res = self._do_revert_locked(p)
            if res.get("result") == "revert-failed":
                raise RollbackError(f"revert failed: {res.get('error')}")
            return res

    # ── timer callback (runs on the Timer thread) ──
    def _on_timeout(self, token: str) -> None:
        with self._lock:
            p = self._pending
            # If confirm/cancel already resolved this (or a newer change exists),
            # the token won't match — do nothing.
            if p is None or not secrets.compare_digest(token, p.token):
                return
            self._do_revert_locked(p)

    def _do_revert_locked(self, p: _Pending) -> dict:
        """Restore the snapshot. Caller must hold _lock.

        A revert that throws must NOT be reported as success: the box is very
        likely still on the applied (possibly unreachable) config, and the old
        `finally` block recorded "reverted" regardless while the traceback died
        unread on the Timer thread. Fail loudly instead.
        """
        try:
            self._revert(p.snapshot)
        except Exception as e:
            logger.exception(
                "network revert FAILED for %s — host may still be on the "
                "applied config", p.label)
            p.reverted = False
            self._pending = None
            self._last_result = "revert-failed"
            return {"result": "revert-failed", "label": p.label, "error": str(e)}
        p.reverted = True
        self._pending = None
        self._last_result = "reverted"
        return {"result": "reverted", "label": p.label}
