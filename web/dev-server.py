#!/usr/bin/env python3
"""
ForgeOS Development Server - No-cache version for previewing worktree changes.
Serves files with Cache-Control: no-cache headers to prevent browser caching.
"""

import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from functools import partial

class NoCacheHTTPRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler that sends Cache-Control: no-cache headers."""
    
    def end_headers(self):
        # Send cache-busting headers
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()
    
    def log_message(self, format, *args):
        # Custom log format with timestamp
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

def run_server(port=5080, directory=None):
    """Start the HTTP server with no-cache headers."""
    if directory is None:
        directory = os.getcwd()
    
    handler = partial(NoCacheHTTPRequestHandler, directory=directory)
    
    server = HTTPServer(('0.0.0.0', port), handler)
    server.timeout = 1
    
    print(f"✅ ForgeOS Dev Server started")
    print(f"   URL: http://localhost:{port}/desktop/index.html")
    print(f"   Serving from: {directory}")
    print(f"   Cache-Control: no-cache (browser caching disabled)")
    print(f"   Press Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped")
        server.shutdown()

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5080
    directory = sys.argv[2] if len(sys.argv) > 2 else None
    
    run_server(port, directory)
