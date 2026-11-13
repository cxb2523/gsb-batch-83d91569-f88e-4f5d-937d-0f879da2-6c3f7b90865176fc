"""
High-quality test server for transport layer testing.

Provides a flexible HTTP server that can simulate various scenarios
for testing the transport layer with configurable responses.
"""

from __future__ import annotations

import socket
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event, Thread
from typing import Any, Callable


@dataclass
class ServerResponse:
    """Configuration for server response behavior."""
    status_code: int = 200
    headers: dict[str, str] | None = None
    body: str = ""
    content_type: str = "application/json"
    delay: float = 0.0
    should_timeout: bool = False
    custom_handler: Callable[[BaseHTTPRequestHandler], None] | None = None


class StubHTTPRequestHandler(BaseHTTPRequestHandler):
    """Flexible HTTP request handler for testing with configurable responses."""
    
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
    
    def do_GET(self) -> None:
        """Handle GET requests."""
        self._handle_request("GET")
    
    def do_POST(self) -> None:
        """Handle POST requests."""
        self._handle_request("POST")
    
    def do_PUT(self) -> None:
        """Handle PUT requests."""
        self._handle_request("PUT")
    
    def do_DELETE(self) -> None:
        """Handle DELETE requests."""
        self._handle_request("DELETE")
    
    def do_PATCH(self) -> None:
        """Handle PATCH requests."""
        self._handle_request("PATCH")
    
    def _handle_request(self, method: str) -> None:
        """Handle any HTTP request with configurable response."""
        # Get the current response from the test server instance
        server = self.server
        test_server = getattr(server, 'test_server_instance', None)
        if test_server and hasattr(test_server, 'current_response') and test_server.current_response:
            response = test_server.current_response
            self._send_configured_response(response)
        else:
            # Default 404 response
            self._send_response(404, '{"error": "Not found"}', "application/json")
    
    def _send_configured_response(self, response: ServerResponse) -> None:
        """Send response based on configuration."""
        if response.custom_handler:
            response.custom_handler(self)
            return
        
        if response.should_timeout:
            # Simulate timeout by not responding
            return
        
        if response.delay > 0:
            time.sleep(response.delay)
        
        headers = response.headers or {}
        self._send_response(
            response.status_code,
            response.body,
            response.content_type,
            headers
        )
    
    def _send_response(self, status_code: int, body: str, content_type: str, extra_headers: dict[str, str] | None = None) -> None:
        """Send HTTP response with optional extra headers."""
        try:
            self.send_response(status_code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body.encode('utf-8'))))
            
            # Add extra headers
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            
            self.end_headers()
            self.wfile.write(body.encode('utf-8'))
            self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            # Client disconnected, ignore
            pass
    
    def log_message(self, format: str, *args: Any) -> None:
        """Suppress log messages."""
        pass


class StubServer:
    """High-quality test server that runs once and provides programmatic response control."""
    
    def __init__(self) -> None:
        self.server: HTTPServer | None = None
        self.thread: Thread | None = None
        self.port: int = 0
        self.current_response: ServerResponse | None = None
        self._lock = threading.Lock()
        self._shutdown_event = Event()
    
    def _find_free_port(self) -> int:
        """Find a free port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port
    
    def start(self) -> None:
        """Start the test server."""
        if self.server is not None:
            return  # Already started
        
        self.port = self._find_free_port()
        self.server = HTTPServer(('localhost', self.port), StubHTTPRequestHandler)
        
        # Make the StubServer instance accessible to the handler
        self.server.test_server_instance = self
        
        # Start server in a separate thread
        self.thread = Thread(target=self._run_server, daemon=True)
        self.thread.start()
        
        # Wait a moment for server to start
        time.sleep(0.1)
    
    def _run_server(self) -> None:
        """Run the server in a separate thread."""
        if self.server:
            self.server.serve_forever()
    
    def stop(self) -> None:
        """Stop the test server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1.0)
        self.server = None
        self.thread = None
    
    @asynccontextmanager
    async def programmatic_response(self, response: ServerResponse):
        """Context manager for setting a programmatic response."""
        with self._lock:
            self.current_response = response
            try:
                yield f"http://localhost:{self.port}"
            finally:
                self.current_response = None
    
    @property
    def base_url(self) -> str:
        """Get the base URL of the running server."""
        if self.server is None:
            raise RuntimeError("Server not started")
        return f"http://localhost:{self.port}"


# Global test server instance
_test_server: StubServer | None = None


def get_test_server() -> StubServer:
    """Get the global test server instance."""
    global _test_server
    if _test_server is None:
        _test_server = StubServer()
        _test_server.start()
    return _test_server


def cleanup_test_server() -> None:
    """Cleanup the global test server instance."""
    global _test_server
    if _test_server is not None:
        _test_server.stop()
        _test_server = None

