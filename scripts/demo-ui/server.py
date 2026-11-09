#!/usr/bin/env python3
"""Interfaz local para la demo del HPA (solo biblioteca estándar).

    python scripts/demo-ui/server.py        ->  http://localhost:8099

Muestra réplicas, CPU y pods del backend en vivo (consulta kubectl cada 3 s) y
permite lanzar / parar una prueba de carga k6 contra el balanceador de AWS.
Requiere kubectl con acceso al clúster y k6 instalado.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("PORT", "8099"))
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
K6 = shutil.which("k6") or r"C:\Program Files\k6\k6.exe"
NS_APP = "kuber-app"

state = {"hpa": None, "pods": [], "lb": None, "error": None, "t": 0}
history = []  # [(epoch, replicas, cpu)]
load = {"proc": None, "profile": None, "start": None, "vus": None, "log": ""}
lock = threading.Lock()


def kubectl(*args):
    return subprocess.run(["kubectl", *args], capture_output=True, text=True, timeout=20)


def poll():
    while True:
        try:
            if not state["lb"]:
                r = kubectl("-n", "traefik", "get", "svc", "traefik", "-o",
                            "jsonpath={.status.loadBalancer.ingress[0].hostname}")
                state["lb"] = r.stdout.strip() or None
            h = json.loads(kubectl("-n", NS_APP, "get", "hpa", "kuber-backend-hpa", "-o", "json").stdout)
            p = json.loads(kubectl("-n", NS_APP, "get", "pods", "-l", "app.kubernetes.io/name=backend",
                                   "-o", "json").stdout)
            cpu = mem = None
            for m in h["status"].get("currentMetrics", []) or []:
                res = m.get("resource", {})
                if res.get("name") == "cpu":
                    cpu = res["current"].get("averageUtilization")
                if res.get("name") == "memory":
                    mem = res["current"].get("averageUtilization")
            pods = []
            for it in p["items"]:
                cs = it["status"].get("containerStatuses", [{}])[0]
                pods.append({"name": it["metadata"]["name"][-5:], "ready": bool(cs.get("ready")),
                             "phase": it["status"].get("phase"), "terminating": bool(it["metadata"].get("deletionTimestamp"))})
            cur = h["status"].get("currentReplicas", 0)
            with lock:
                state.update(hpa={"current": cur, "desired": h["status"].get("desiredReplicas", 0),
                                  "min": h["spec"]["minReplicas"], "max": h["spec"]["maxReplicas"],
                                  "cpu": cpu, "mem": mem}, pods=pods, error=None, t=time.time())
                history.append((time.time(), cur, cpu))
                del history[:-400]
        except Exception as e:  # noqa: BLE001
            state["error"] = str(e)[:200]
        time.sleep(3)


def read_k6(proc):
    # k6 escribe el progreso en stderr, con \r entre actualizaciones
    buf = ""
    for ch in iter(lambda: proc.stderr.read(1), ""):
        buf += ch
        if ch in "\r\n":
            m = re.search(r"(\d+)/(\d+) VUs", buf)
            if m:
                load["vus"] = int(m.group(1))
            load["log"] = (load["log"] + buf)[-2000:]
            buf = ""


def start_load(profile):
    if load["proc"] and load["proc"].poll() is None:
        return "ya hay una carga en marcha"
    if not state["lb"]:
        return "balanceador desconocido"
    env = dict(os.environ)
    proc = subprocess.Popen(
        [K6, "run", "--quiet=false", "-e", f"BASE_URL=http://{state['lb']}", "-e", f"PROFILE={profile}",
         str(ROOT / "tests" / "load" / "k6-load.js")],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(ROOT))
    load.update(proc=proc, profile=profile, start=time.time(), vus=0, log="")
    threading.Thread(target=read_k6, args=(proc,), daemon=True).start()
    return "ok"


def stop_load():
    p = load["proc"]
    if p and p.poll() is None:
        p.terminate()
    return "ok"


STAGES = {  # (segundos, VUs objetivo): igual que tests/load/k6-load.js
    "ramp": [(60, 30), (120, 150), (120, 300), (60, 300), (120, 0)],
    "spike": [(20, 20), (10, 400), (180, 400), (60, 0)],
}


def vus_at(profile, t):
    cur, prev = 0, 0
    for dur, tgt in STAGES.get(profile, []):
        if t <= dur:
            return round(prev + (tgt - prev) * t / dur)
        t -= dur
        prev = tgt
    return 0


def status():
    p = load["proc"]
    running = bool(p and p.poll() is None)
    with lock:
        return {"hpa": state["hpa"], "pods": state["pods"], "error": state["error"],
                "lb": state["lb"], "history": [(round(t), r, c) for t, r, c in history[-200:]],
                "load": {"log": load["log"][-300:], "running": running, "profile": load["profile"], "vus": vus_at(load["profile"], time.time() - load["start"]) if running else 0,
                         "elapsed": int(time.time() - load["start"]) if load["start"] and running else 0}}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/status":
            self._send(200, json.dumps(status()))
        else:
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        if self.path.startswith("/api/load/start"):
            prof = "ramp" if "ramp" in self.path else "spike"
            self._send(200, json.dumps({"result": start_load(prof)}))
        elif self.path == "/api/load/stop":
            self._send(200, json.dumps({"result": stop_load()}))
        else:
            self._send(404, "{}")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=poll, daemon=True).start()
    print(f"Demo HPA en http://localhost:{PORT}  (k6: {K6})")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
