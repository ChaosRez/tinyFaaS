#!/usr/bin/env python3
"""Benchmark tinyFaaS function handlers under runc vs gVisor (runsc).

Stdlib only. Must run on a Linux host with Docker and runsc registered as a
Docker runtime (see README "Sandboxed handlers with gVisor"). Run from the
repository root after `make build`:

    sudo python3 benchmarks/bench_gvisor.py --out benchmarks/results

For every round the script starts the tinyFaaS binary once per runtime, in
alternating order (runc, runsc, runsc, runc, ...) so slow drift on the host
does not favour one runtime. It measures:

  cold.csv       upload of a fresh function until its first successful
                 invocation, through tinyFaaS (manager + rproxy)
  container.csv  the same handler image started directly with `docker run
                 --runtime X`, polling /health every 5 ms; isolates the
                 sandbox start cost from tinyFaaS' 1 s readiness poll
  warm.csv       per-request latency of warm handlers (echo, cpu, io)

Every handler container is inspected and its HostConfig.Runtime recorded,
so each row proves which runtime actually served it.
"""

import argparse
import base64
import csv
import http.client
import io
import json
import os
import platform
import signal
import subprocess
import sys
import time
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FNS = os.path.join(REPO, "benchmarks", "fns")
MGMT = ("127.0.0.1", 8080)
HTTP = ("127.0.0.1", 8000)

# runtime label -> value of TF_CONTAINER_RUNTIME ("" = Docker default, runc)
RUNTIMES = {"runc": "", "runsc": "runsc"}


def sh(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def zip_dir(path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in sorted(os.listdir(path)):
            z.write(os.path.join(path, f), f)
    return base64.b64encode(buf.getvalue()).decode()


def post(addr, path, body, timeout=300):
    c = http.client.HTTPConnection(*addr, timeout=timeout)
    try:
        c.request("POST", path, body=body)
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


def upload(name, fn_dir):
    body = json.dumps({"name": name, "env": "python3", "threads": 1, "zip": zip_dir(fn_dir)})
    st, out = post(MGMT, "/upload", body)
    if st != 200:
        raise RuntimeError(f"upload {name} failed: {st} {out!r}")


def delete(name):
    post(MGMT, "/delete", json.dumps({"name": name}))


def handler_runtime(name):
    ids = sh("docker", "ps", "-q", "--filter", f"label=tinyfaas-function={name}").split()
    if len(ids) != 1:
        raise RuntimeError(f"expected 1 container for {name}, got {ids}")
    return sh("docker", "inspect", "-f", "{{.HostConfig.Runtime}}", ids[0])


class TinyFaaS:
    def __init__(self, binary, runtime_env, log_path):
        env = dict(os.environ)
        env.pop("TF_CONTAINER_RUNTIME", None)
        if runtime_env:
            env["TF_CONTAINER_RUNTIME"] = runtime_env
        env["coap_PORT"] = "-1"
        self.log = open(log_path, "a")
        self.p = subprocess.Popen([binary], cwd=REPO, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                c = http.client.HTTPConnection(*MGMT, timeout=1)
                c.request("GET", "/list")
                c.getresponse().read()
                c.close()
                return
            except OSError:
                if self.p.poll() is not None:
                    raise RuntimeError(f"tinyFaaS exited with {self.p.returncode}, see {log_path}")
                time.sleep(0.1)
        raise RuntimeError("tinyFaaS did not come up")

    def stop(self):
        try:
            post(MGMT, "/wipe", "")
        except OSError:
            pass
        self.p.send_signal(signal.SIGINT)
        try:
            self.p.wait(30)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()
        self.log.close()


def cold_start(label, rnd, i, writer):
    name = f"cold{rnd}x{i}{label}"
    t0 = time.perf_counter()
    upload(name, os.path.join(FNS, "echo"))
    t_up = time.perf_counter()
    while True:
        try:
            st, body = post(HTTP, "/" + name, "ping", timeout=10)
            if st == 200 and body == b"ping":
                break
        except OSError:
            pass
        time.sleep(0.005)
    t1 = time.perf_counter()
    rt = handler_runtime(name)
    writer.writerow([label, rnd, i, f"{(t_up - t0) * 1e3:.2f}", f"{(t1 - t_up) * 1e3:.2f}",
                     f"{(t1 - t0) * 1e3:.2f}", rt])
    delete(name)


def warm(label, rnd, fn, n, warmup, writer):
    name = f"warm{rnd}{fn}{label}"
    upload(name, os.path.join(FNS, fn))
    rt = handler_runtime(name)
    c = http.client.HTTPConnection(*HTTP, timeout=60)
    for k in range(warmup + n):
        t0 = time.perf_counter()
        c.request("POST", "/" + name, body="ping" if fn == "echo" else "")
        r = c.getresponse()
        body = r.read()
        t1 = time.perf_counter()
        if r.status != 200:
            raise RuntimeError(f"{name}: {r.status} {body!r}")
        if k >= warmup:
            writer.writerow([label, rnd, fn, k - warmup, f"{(t1 - t0) * 1e3:.3f}", rt])
    c.close()
    delete(name)


def build_handler_image(tag):
    """Build the exact image tinyFaaS builds for the echo function."""
    import shutil
    import tempfile

    d = tempfile.mkdtemp(prefix="tf-bench-")
    arch = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "arm"}[platform.machine()]
    src = os.path.join(REPO, "pkg", "docker", f"runtimes-{arch}", "python3")
    for f in os.listdir(src):
        shutil.copy(os.path.join(src, f), d)
    shutil.copytree(os.path.join(FNS, "echo"), os.path.join(d, "fn"))
    sh("docker", "build", "-q", "-t", tag, d)
    shutil.rmtree(d)


def container_start(label, rnd, i, image, net, writer):
    rt = RUNTIMES[label] or "runc"
    t0 = time.perf_counter()
    cid = sh("docker", "run", "-d", "--runtime", rt, "--network", net, image)
    ip = sh("docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", cid)
    t_run = time.perf_counter()
    while True:
        try:
            c = http.client.HTTPConnection(ip, 8000, timeout=1)
            c.request("GET", "/health")
            if c.getresponse().status == 200:
                c.close()
                break
        except OSError:
            pass
        time.sleep(0.005)
    t1 = time.perf_counter()
    real = sh("docker", "inspect", "-f", "{{.HostConfig.Runtime}}", cid)
    t2 = time.perf_counter()
    sh("docker", "rm", "-f", cid)
    t3 = time.perf_counter()
    writer.writerow([label, rnd, i, f"{(t_run - t0) * 1e3:.2f}", f"{(t1 - t0) * 1e3:.2f}",
                     f"{(t3 - t2) * 1e3:.2f}", real])


def record_env(path):
    def tryrun(*c):
        try:
            return sh(*c)
        except Exception as e:  # noqa: BLE001
            return f"unavailable ({e})"

    cpu = ""
    try:
        with open("/proc/cpuinfo") as f:
            cpu = next(line.split(":", 1)[1].strip() for line in f if line.startswith("model name"))
    except (OSError, StopIteration):
        pass
    mem = ""
    with open("/proc/meminfo") as f:
        mem = f.readline().split(":", 1)[1].strip()
    info = {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": platform.machine(),
        "cpu_model": cpu,
        "cpus": os.cpu_count(),
        "mem_total": mem,
        "kernel": platform.release(),
        "os": tryrun("sh", "-c", ". /etc/os-release && echo $PRETTY_NAME"),
        "virtualization": tryrun("systemd-detect-virt"),
        "kvm_available": os.path.exists("/dev/kvm"),
        "cpu_hypervisor_flag": " hypervisor" in open("/proc/cpuinfo").read(),
        "docker_server": tryrun("docker", "version", "-f", "{{.Server.Version}}"),
        "docker_runtimes": tryrun("docker", "info", "-f", "{{range $k, $v := .Runtimes}}{{$k}} {{end}}"),
        "docker_storage_driver": tryrun("docker", "info", "-f", "{{.Driver}}"),
        "docker_cgroup": tryrun("docker", "info", "-f", "{{.CgroupDriver}} v{{.CgroupVersion}}"),
        "runc": tryrun("runc", "--version").splitlines()[0],
        "runsc": tryrun("runsc", "--version").replace("\n", "; "),
        "runsc_platform": tryrun("docker", "run", "--rm", "--runtime", "runsc", "alpine:3.20",
                                 "sh", "-c", "dmesg | head -1; uname -r"),
        "python": sys.version.split()[0],
    }
    with open(path, "w") as f:
        json.dump(info, f, indent=2)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "benchmarks", "results"))
    ap.add_argument("--binary", default=None, help="tinyFaaS binary (default tinyfaas-linux-<arch>)")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--cold", type=int, default=15, help="cold starts per runtime per round")
    ap.add_argument("--container", type=int, default=15, help="direct container starts per runtime per round")
    ap.add_argument("--warm", type=int, default=200, help="measured warm requests per function per round")
    ap.add_argument("--warmup", type=int, default=20)
    args = ap.parse_args()

    arch = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "arm"}[platform.machine()]
    binary = args.binary or os.path.join(REPO, f"tinyfaas-linux-{arch}")
    os.makedirs(args.out, exist_ok=True)
    print(json.dumps(record_env(os.path.join(args.out, "env.json")), indent=2))

    fc = open(os.path.join(args.out, "cold.csv"), "w", newline="")
    fk = open(os.path.join(args.out, "container.csv"), "w", newline="")
    fw = open(os.path.join(args.out, "warm.csv"), "w", newline="")
    cold_w, cont_w, warm_w = csv.writer(fc), csv.writer(fk), csv.writer(fw)
    cold_w.writerow(["runtime", "round", "i", "upload_ms", "upload_to_first_ok_ms", "cold_start_ms", "inspected_runtime"])
    cont_w.writerow(["runtime", "round", "i", "docker_run_ms", "run_to_healthy_ms", "remove_ms", "inspected_runtime"])
    warm_w.writerow(["runtime", "round", "function", "i", "latency_ms", "inspected_runtime"])

    image, net = "tf-bench-echo:latest", "tf-bench-net"
    build_handler_image(image)
    subprocess.run(["docker", "network", "rm", net], capture_output=True)
    sh("docker", "network", "create", net)

    try:
        for rnd in range(args.rounds):
            order = ["runc", "runsc"] if rnd % 2 == 0 else ["runsc", "runc"]
            for label in order:
                print(f"round {rnd}: {label}", flush=True)
                for i in range(args.container):
                    container_start(label, rnd, i, image, net, cont_w)
                fk.flush()
                tf = TinyFaaS(binary, RUNTIMES[label], os.path.join(args.out, f"tinyfaas-{label}.log"))
                try:
                    for i in range(args.cold):
                        cold_start(label, rnd, i, cold_w)
                    fc.flush()
                    for fn in ("echo", "cpu", "io"):
                        warm(label, rnd, fn, args.warm, args.warmup, warm_w)
                    fw.flush()
                finally:
                    tf.stop()
    finally:
        for f in (fc, fk, fw):
            f.close()
        subprocess.run(["docker", "network", "rm", net], capture_output=True)
        subprocess.run(["docker", "rmi", image], capture_output=True)


if __name__ == "__main__":
    main()
