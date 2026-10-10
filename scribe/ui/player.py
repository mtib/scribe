"""Playback of a recording by driving mpv over its JSON IPC socket.

GStreamer on this system lacks the base/good plugins, and mpv decodes Opus
directly, seeks accurately and reports its own position.
"""
import atexit
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path


class Player:
    def __init__(self, rec_audio):
        self.src = Path(rec_audio)
        self.proc = None
        self.sock = None
        self.buf = b""
        self.req = 0
        self.sock_dir = None

    def prepare(self):
        """Blocking (call from a worker thread): start mpv paused and connect."""
        self.sock_dir = tempfile.mkdtemp(prefix="scribe-mpv-")
        path = os.path.join(self.sock_dir, "ipc")
        self.proc = subprocess.Popen(
            ["mpv", "--no-video", "--no-terminal", "--idle=yes", "--pause", "--keep-open=yes",
             f"--input-ipc-server={path}", str(self.src)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if os.path.exists(path):
                break
            if self.proc.poll() is not None:
                raise RuntimeError("mpv exited")
            time.sleep(0.05)
        else:
            raise RuntimeError("mpv did not start")
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(1.0)
        s.connect(path)
        self.sock = s
        atexit.register(self.close)

    def _cmd(self, *args):
        """Send a command; return its data (None on error). Skips async events."""
        if not self.sock:
            return None
        self.req += 1
        rid = self.req
        try:
            self.sock.sendall(json.dumps({"command": list(args), "request_id": rid}).encode() + b"\n")
            while True:
                while b"\n" not in self.buf:
                    chunk = self.sock.recv(65536)
                    if not chunk:
                        return None
                    self.buf += chunk
                line, self.buf = self.buf.split(b"\n", 1)
                msg = json.loads(line)
                if msg.get("request_id") == rid:
                    return msg.get("data") if msg.get("error") == "success" else None
        except (OSError, ValueError):
            return None

    @property
    def playing(self):
        return self._cmd("get_property", "pause") is False

    def toggle(self):
        self._cmd("cycle", "pause")

    def play(self):
        self._cmd("set_property", "pause", False)

    def position(self):
        return float(self._cmd("get_property", "time-pos") or 0.0)

    def duration(self):
        return float(self._cmd("get_property", "duration") or 0.0)

    def seek(self, sec):
        self._cmd("seek", max(0.0, float(sec)), "absolute+exact")

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        if self.sock:
            self.sock.close()
        if self.sock_dir:
            for f in Path(self.sock_dir).glob("*"):
                f.unlink(missing_ok=True)
            Path(self.sock_dir).rmdir()
        self.proc = self.sock = None
