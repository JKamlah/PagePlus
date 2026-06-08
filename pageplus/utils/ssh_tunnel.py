"""SSH tunnel lifecycle manager for remote OpenAI-compatible endpoints.

This module lets the PagePlus GUI open and close SSH tunnels on the user's
behalf, mirroring the pattern from standalone vLLM client scripts::

    ssh -N -L 8082:localhost:8082 root@spark01.bib.uni-mannheim.de

Tunnels are tracked by endpoint name so the GUI can show status and avoid
duplicates.  An :func:`atexit` handler ensures all tunnels are cleaned up
when the Python process exits.

Usage::

    from pageplus.utils.ssh_tunnel import start_tunnel, stop_tunnel, tunnel_status

    start_tunnel("spark", "ssh -N -L 8082:localhost:8082 root@spark01")
    print(tunnel_status("spark"))   # "running"
    stop_tunnel("spark")
"""
from __future__ import annotations

import atexit
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class _TunnelInfo:
    """Internal record of a running tunnel."""

    name: str
    ssh_command: str
    process: subprocess.Popen
    started_at: float = field(default_factory=time.time)


# Module-level registry of active tunnels, keyed by endpoint name.
_active_tunnels: Dict[str, _TunnelInfo] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_tunnel(name: str, ssh_command: str, wait_seconds: float = 2.0) -> str:
    """Start an SSH tunnel for the named endpoint.

    Returns a short status message.  If a tunnel for *name* is already
    running, it is stopped first.
    """
    # Tear down any existing tunnel for this name.
    if name in _active_tunnels:
        stop_tunnel(name)

    cmd_parts = shlex.split(ssh_command)
    try:
        proc = subprocess.Popen(
            cmd_parts,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
    except FileNotFoundError:
        return f"SSH binary not found. Is 'ssh' installed and on PATH?"
    except Exception as exc:
        return f"Failed to start tunnel: {exc}"

    # Give the tunnel a moment to establish (or fail).
    time.sleep(wait_seconds)

    if proc.poll() is not None:
        stderr = (proc.stderr.read() or b"").decode(errors="replace").strip()
        return f"SSH tunnel exited immediately (rc={proc.returncode}): {stderr}"

    _active_tunnels[name] = _TunnelInfo(
        name=name,
        ssh_command=ssh_command,
        process=proc,
    )
    return f"SSH tunnel '{name}' established (PID {proc.pid})."


def stop_tunnel(name: str) -> str:
    """Stop the tunnel for *name*.  No-op if not running."""
    info = _active_tunnels.pop(name, None)
    if info is None:
        return f"No active tunnel for '{name}'."
    try:
        if info.process.poll() is None:
            os.killpg(os.getpgid(info.process.pid), signal.SIGTERM)
            info.process.wait(timeout=5)
    except Exception as exc:
        return f"Error stopping tunnel '{name}': {exc}"
    return f"SSH tunnel '{name}' stopped."


def tunnel_status(name: str) -> str:
    """Return ``'running'``, ``'stopped'``, or ``'not started'``."""
    info = _active_tunnels.get(name)
    if info is None:
        return "not started"
    if info.process.poll() is None:
        return "running"
    # Process exited unexpectedly – clean up.
    _active_tunnels.pop(name, None)
    return "stopped"


def active_tunnel_names() -> list[str]:
    """Return names of all currently active tunnels."""
    # Prune dead tunnels first.
    dead = [n for n, info in _active_tunnels.items() if info.process.poll() is not None]
    for n in dead:
        _active_tunnels.pop(n, None)
    return list(_active_tunnels.keys())


# ---------------------------------------------------------------------------
# atexit cleanup
# ---------------------------------------------------------------------------


def _cleanup_all_tunnels() -> None:
    for name in list(_active_tunnels):
        stop_tunnel(name)


atexit.register(_cleanup_all_tunnels)
