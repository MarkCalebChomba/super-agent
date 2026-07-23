"""Lightweight HTTP health server for cron-job.org uptime monitoring.

Deployed alongside the main agent system to:
1. Keep the Hugging Face Space alive (responds to pings)
2. Expose a health endpoint for cron-job.org
3. Provide a simple status dashboard
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status = {
                "status": "alive",
                "timestamp": datetime.utcnow().isoformat(),
                "agents_running": True,
            }
            self.wfile.write(json.dumps(status).encode())
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress logs

def run_health_server(port: int = 8080):
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health server running on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_health_server(port)
