"""Lightweight HTTP server for health checks and web dashboard."""

import json
import os
import sqlite3
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Super Agent Dashboard</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0d1117; color:#c9d1d9; padding:20px; }}
  .container {{ max-width:960px; margin:0 auto; }}
  h1 {{ color:#58a6ff; margin-bottom:8px; font-size:1.5rem; }}
  .time {{ color:#8b949e; font-size:0.85rem; margin-bottom:20px; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; margin-bottom:16px; }}
  .card h2 {{ color:#f0f6fc; font-size:1.1rem; margin-bottom:12px; border-bottom:1px solid #30363d; padding-bottom:8px; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
  th {{ text-align:left; color:#8b949e; padding:6px 8px; border-bottom:1px solid #30363d; font-weight:500; }}
  td {{ padding:6px 8px; border-bottom:1px solid #21262d; }}
  .status-running {{ color:#3fb950; }}
  .status-stopped {{ color:#f85149; }}
  .status-idle {{ color:#d29922; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:600; }}
  .badge-green {{ background:#1b4126; color:#3fb950; }}
  .badge-red {{ background:#4e1a1a; color:#f85149; }}
  .badge-yellow {{ background:#4d3a0f; color:#d29922; }}
  .log-msg {{ font-family:'SF Mono',monospace; font-size:0.8rem; color:#8b949e; }}
  .revenue {{ color:#d2a8ff; font-size:1.2rem; font-weight:600; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  @media (max-width:640px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
  .footer {{ text-align:center; color:#484f58; font-size:0.8rem; margin-top:24px; }}
  .refresh {{ color:#58a6ff; cursor:pointer; font-size:0.85rem; }}
</style>
</head>
<body>
<div class="container">
  <h1>Super Agent Dashboard</h1>
  <p class="time">{timestamp}</p>

  <div class="card">
    <h2>Agent Status</h2>
    <table>
      <tr><th>Agent</th><th>Status</th><th>Errors</th><th>Revenue</th></tr>
      {agent_rows}
    </table>
  </div>

  <div class="grid2">
    <div class="card">
      <h2>Revenue</h2>
      <p class="revenue">${total_revenue:.2f}</p>
      <p>Last 24h: <strong>${revenue_24h:.2f}</strong> | Last 7d: <strong>${revenue_7d:.2f}</strong></p>
    </div>
    <div class="card">
      <h2>Resources (24h)</h2>
      <p>Memory: {memory_mb:.0f} MB | Tokens: {tokens:,}</p>
      <p>API Calls: {api_calls:,}</p>
    </div>
  </div>

  <div class="card">
    <h2>Budget</h2>
    {budget_html}
  </div>

  <div class="card">
    <h2>Recent Activity</h2>
    <table>
      <tr><th>Time</th><th>Agent</th><th>Level</th><th>Message</th></tr>
      {log_rows}
    </table>
  </div>

  <div class="card">
    <h2>SuperAgent Actions</h2>
    <table>
      <tr><th>Time</th><th>Action</th><th>Details</th></tr>
      {action_rows}
    </table>
  </div>

  <p class="footer">Auto-refreshes every 30s &middot; <span class="refresh" onclick="location.reload()">Refresh now</span></p>
</div>
<script>setTimeout(function(){{ location.reload(); }}, 30000);</script>
</body>
</html>"""

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._send_text("OK")
        elif self.path == "/api/status":
            self._send_json(self._build_status_json())
        elif self.path in ("/", "/dashboard"):
            self._send_html(self._render_dashboard())
        else:
            self.send_response(404)
            self.end_headers()

    def _send_text(self, text):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(text.encode())

    def _send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _send_html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _query(self, db_path, sql, params=()):
        if not os.path.exists(db_path):
            return []
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception:
            return []

    def _build_status_json(self):
        agents = self._query("data/system.db",
            "SELECT agent_name, status, error_count, COALESCE(total_revenue,0) as rev FROM agent_registry")
        logs = self._query("data/logs/central_log.db",
            "SELECT agent_name, level, message, timestamp FROM central_log ORDER BY id DESC LIMIT 20")
        rev_rows = self._query("data/revenue.db",
            "SELECT COALESCE(SUM(amount),0) as total FROM revenue_events")
        total_rev = rev_rows[0]["total"] if rev_rows else 0
        return {
            "status": "alive",
            "timestamp": datetime.utcnow().isoformat(),
            "agents": agents,
            "recent_logs": logs,
            "total_revenue": total_rev,
        }

    def _render_dashboard(self):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        agents = self._query("data/system.db",
            "SELECT agent_name, status, error_count, COALESCE(total_revenue,0) as rev FROM agent_registry ORDER BY created_at ASC")
        logs = self._query("data/logs/central_log.db",
            "SELECT agent_name, level, message, timestamp FROM central_log ORDER BY id DESC LIMIT 15")
        rev_all = self._query("data/revenue.db",
            "SELECT COALESCE(SUM(amount),0) as t FROM revenue_events")
        rev_24h = self._query("data/revenue.db",
            "SELECT COALESCE(SUM(amount),0) as t FROM revenue_events WHERE timestamp >= datetime('now', '-24 hours')")
        rev_7d = self._query("data/revenue.db",
            "SELECT COALESCE(SUM(amount),0) as t FROM revenue_events WHERE timestamp >= datetime('now', '-7 days')")
        resources = self._query("data/system.db",
            "SELECT COALESCE(SUM(memory_mb),0) as mem, COALESCE(SUM(tokens_used),0) as tok, COALESCE(SUM(api_calls),0) as api FROM resource_usage WHERE timestamp >= datetime('now', '-24 hours')")
        budgets = self._query("data/system.db",
            "SELECT * FROM budget ORDER BY id DESC LIMIT 1")
        actions = self._query("data/system.db",
            "SELECT action_type, target, details, timestamp FROM auto_actions ORDER BY id DESC LIMIT 5")

        agent_rows = ""
        for a in agents:
            s = a["status"]
            cls = {"running":"badge-green","idle":"badge-yellow","stopped":"badge-red"}.get(s, "badge-yellow")
            agent_rows += f"<tr><td>{a['agent_name'][:24]}</td><td><span class='badge {cls}'>{s}</span></td><td>{a['error_count']}</td><td>${a['rev']:.2f}</td></tr>"

        log_rows = ""
        lvl_map = {10:"DEBUG",20:"INFO",25:"ACTION",30:"WARN",40:"ERROR",45:"REVENUE",50:"CTA"}
        for l in logs:
            lvl = lvl_map.get(l["level"], str(l["level"]))
            msg = l["message"][:60]
            ts_l = (l["timestamp"] or "")[:19]
            log_rows += f"<tr><td>{ts_l}</td><td>{l['agent_name'][:18]}</td><td>{lvl}</td><td class='log-msg'>{msg}</td></tr>"

        r = resources[0] if resources else {"mem":0,"tok":0,"api":0}
        b = budgets[0] if budgets else None
        if b:
            net = b["total_revenue"] - b["total_expenses"]
            budget_html = f"""
            <table>
              <tr><td>Total Revenue</td><td><strong>${b['total_revenue']:.2f}</strong></td></tr>
              <tr><td>Total Expenses</td><td><strong>${b['total_expenses']:.2f}</strong></td></tr>
              <tr><td>Net</td><td><strong>${net:.2f}</strong></td></tr>
              <tr><td>Auto-Buy</td><td><strong>{'ON' if b['auto_buy_enabled'] else 'OFF'}</strong> (${b['max_monthly_budget']:.0f}/mo, ${b['monthly_spent']:.2f} spent)</td></tr>
            </table>
            """
        else:
            budget_html = "<p>No budget data yet</p>"

        action_rows = ""
        for a in actions:
            ts_a = (a["timestamp"] or "")[:19]
            tgt = a.get("target","")[:30]
            det = str(a.get("details",""))[:40]
            action_rows += f"<tr><td>{ts_a}</td><td>{a['action_type']}</td><td>{tgt} — {det}</td></tr>"

        total_rev = rev_all[0]["t"] if rev_all else 0
        rev24 = rev_24h[0]["t"] if rev_24h else 0
        rev7 = rev_7d[0]["t"] if rev_7d else 0

        return HTML_TEMPLATE.format(
            timestamp=ts,
            agent_rows=agent_rows,
            log_rows=log_rows,
            total_revenue=total_rev,
            revenue_24h=rev24,
            revenue_7d=rev7,
            memory_mb=r["mem"],
            tokens=r["tok"],
            api_calls=r["api"],
            budget_html=budget_html,
            action_rows=action_rows,
        )

    def log_message(self, format, *args):
        pass

def run_health_server(port: int = 8080):
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.timeout = 0.5
    print(f"Health server running on port {port}")
    server.serve_forever()

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_health_server(port)
