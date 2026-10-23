from __future__ import annotations

import asyncio
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Optional

import logging

logger = logging.getLogger(__name__)


def read_proc_starttime(pid: int) -> Optional[int]:
    """Return the starttime (field 22) from /proc/<pid>/stat, or None."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    # The comm field can contain spaces and parentheses; split after the last ')'.
    try:
        rest = raw.rsplit(")", 1)[1].strip().split()
    except IndexError:
        return None
    # rest[0] is state (field 3); starttime is field 22 -> index 19.
    if len(rest) <= 19:
        return None
    try:
        return int(rest[19])
    except ValueError:
        return None


def read_proc_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def is_owned(pid: int, starttime: Optional[int]) -> bool:
    if starttime is None:
        return False
    current = read_proc_starttime(pid)
    return current is not None and current == starttime


@dataclass
class ManagedProcess:
    """A child process owned by this application.

    The child is started in a new session so it does not receive the terminal's
    SIGINT.  Cleanup only targets the recorded PID/PGID and verifies the
    /proc/<pid>/stat starttime before signalling, so a recycled PID is never
    killed by accident.
    """

    cmd: list[str]
    proc: asyncio.subprocess.Process
    pgid: int
    starttime: Optional[int]
    log_path: Optional[Path] = None
    log_file: Optional[IO[bytes]] = None
    stdout_pipe: bool = False
    spawned_at: float = field(default_factory=time.monotonic)
    _stopped: bool = False

    @classmethod
    async def spawn(
        cls,
        cmd: list[str],
        *,
        log_path: Optional[Path] = None,
        stdout_pipe: bool = False,
        stdin_pipe: bool = False,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[Path] = None,
    ) -> "ManagedProcess":
        log_file: Optional[IO[bytes]] = None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "ab", buffering=0)
            stdout = log_file
            stderr = asyncio.subprocess.STDOUT
        elif stdout_pipe:
            stdout = asyncio.subprocess.PIPE
            stderr = asyncio.subprocess.STDOUT
        else:
            stdout = asyncio.subprocess.DEVNULL
            stderr = asyncio.subprocess.DEVNULL

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if stdin_pipe else asyncio.subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            env=env,
            cwd=str(cwd) if cwd else None,
            start_new_session=True,
        )
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, OSError):
            pgid = proc.pid
        starttime = read_proc_starttime(proc.pid)
        return cls(
            cmd=cmd,
            proc=proc,
            pgid=pgid,
            starttime=starttime,
            log_path=log_path,
            log_file=log_file,
            stdout_pipe=stdout_pipe,
        )

    @property
    def pid(self) -> int:
        return self.proc.pid

    def alive(self) -> bool:
        if self.proc.returncode is not None:
            return False
        if self.starttime is None:
            return False
        return is_owned(self.pid, self.starttime)

    def tail_log(self, lines: int = 120) -> str:
        if self.log_path is None:
            return ""
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        rows = text.splitlines()
        return "\n".join(rows[-lines:])

    def _close_log(self) -> None:
        if self.log_file is not None:
            try:
                self.log_file.close()
            except OSError:
                pass
            self.log_file = None

    async def stop(self, grace_s: float = 10.0) -> dict:
        """Stop the owned process group.  Idempotent."""
        if self._stopped:
            return {
                "pid": self.pid,
                "pgid": self.pgid,
                "already_stopped": True,
                "forced": False,
                "exit_code": self.proc.returncode,
            }
        self._stopped = True
        forced = False
        already_exited = self.proc.returncode is not None

        if not already_exited and self.starttime is not None:
            if not is_owned(self.pid, self.starttime):
                logger.warning(
                    "refusing to signal pid %s: ownership check failed (starttime mismatch)",
                    self.pid,
                )
                already_exited = True
            else:
                try:
                    os.killpg(self.pgid, signal.SIGTERM)
                except ProcessLookupError:
                    already_exited = True
                except PermissionError as exc:
                    logger.warning("permission denied signalling pgid %s: %s", self.pgid, exc)
                    already_exited = True

        if not already_exited:
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=grace_s)
            except asyncio.TimeoutError:
                forced = True
                if self.starttime is not None and is_owned(self.pid, self.starttime):
                    try:
                        os.killpg(self.pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.error("pid %s did not exit after SIGKILL", self.pid)

        self._close_log()
        return {
            "pid": self.pid,
            "pgid": self.pgid,
            "already_stopped": already_exited and not forced,
            "forced": forced,
            "exit_code": self.proc.returncode,
        }

    def forget(self) -> None:
        """Close the log without signalling (used when the child exited itself)."""
        self._close_log()