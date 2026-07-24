"""Create a public SSH tunnel to expose the dashboard."""
import subprocess, sys, re, os

port = sys.argv[1] if len(sys.argv) > 1 else "8080"
out_file = "tunnel_url.txt"
result_file = "tunnel_result.txt"

if os.path.exists(out_file):
    os.remove(out_file)

proc = subprocess.Popen(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=30",
     "-R", f"80:localhost:{port}", "nokey@localhost.run"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NO_WINDOW,
)

for line in iter(proc.stdout.readline, b""):
    text = line.decode("utf-8", errors="replace").strip()
    print(text)
    m = re.search(r'(https://[\w.-]+\.localhost\.run)', text)
    if m:
        url = m.group(1)
        with open(out_file, "w") as f:
            f.write(url)
        with open(result_file, "w") as f:
            f.write(f"URL: {url}\nPID: {proc.pid}\n")

proc.wait()
