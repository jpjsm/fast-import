# control_server.py
"""
FastImport Control Server
-------------------------

This module provides a lightweight HTTP control plane for the FastImport
runtime. It exposes operational endpoints such as:

    /stop                      - request graceful shutdown
    /pause[?length=<minutes>]  - pause long-running operations (default: 0.5)
    /resume                    - resume paused operations
    /status                    - return basic runtime status
    /stats                     - return current statistics (if provided by caller)

The server runs in a background thread and communicates with the main
pipeline through shared threading.Event flags.
"""

import inspect
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PAUSE_LENGTH = 0.5  # default pause length in minutes

# ---------------------------------------------------------------------------
# Shared control flags
# ---------------------------------------------------------------------------

stop_requested = threading.Event()
pause_requested = threading.Event()

# Optional: a callable the main program can set to provide live stats
stats_provider = None
status_provider = None


# ---------------------------------------------------------------------------
# HTTP Request Handler
# ---------------------------------------------------------------------------


class ControlHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path

        # --- STOP -----------------------------------------------------------
        if path == "/stop":
            stop_requested.set()
            self._reply(200, b"Stopping FastImport gracefully...\n")
            return

        # --- PAUSE ----------------------------------------------------------
        if path == "/pause":
            pause_requested.set()
            self._reply(200, b"Pausing FastImport...\n")
            return

        # --- RESUME ---------------------------------------------------------
        if path == "/resume":
            pause_requested.clear()
            self._reply(200, b"Resuming FastImport...\n")
            return

        # --- STATUS ---------------------------------------------------------
        if path == "/status":
            if status_provider:
                payload = status_provider().encode("utf-8")
            else:
                payload = b"No status provider registered.\n"
            self._reply(200, payload)
            return

        # --- STATS ----------------------------------------------------------
        if path == "/stats":
            if stats_provider:
                payload = stats_provider().encode("utf-8")
            else:
                payload = b"No stats provider registered.\n"
            self._reply(200, payload)
            return

        # --- HELP (404) -----------------------------------------------------
        help_text = inspect.cleandoc(__doc__)
        help_text = "FastImport Control Server\n\n" + help_text
        help_text += f"\n\nYou requested: {self.path}"
        self._reply(404, help_text.encode("utf-8"))

    # -----------------------------------------------------------------------
    # Helper: send response
    # -----------------------------------------------------------------------
    def _reply(self, code, payload: bytes):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(payload)


# ---------------------------------------------------------------------------
# Server starter
# ---------------------------------------------------------------------------


def start_control_server(host="localhost", port=8765):
    """
    Starts the FastImport control server in the current thread.
    Typically invoked inside a background thread from fastimport.py.
    """
    server = HTTPServer((host, port), ControlHandler)
    server.serve_forever()


# ---------------------------------------------------------------------------
# Thread launcher
# ---------------------------------------------------------------------------


def launch_control_server(host="localhost", port=8765):
    """
    Launch the control server in a daemon thread.
    """
    thread = threading.Thread(
        target=start_control_server, args=(host, port), daemon=True
    )
    thread.start()
    return thread
