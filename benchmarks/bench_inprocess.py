#!/usr/bin/env python3
"""Time the benchmark functions *inside* a container, without HTTP.

Separates the sandbox's effect on the function body from its effect on the
network path (gVisor's netstack + rproxy). Uses the same Python base image as
the tinyFaaS python3 runtime. Writes <out>/inprocess.csv.

    sudo python3 benchmarks/bench_inprocess.py --out benchmarks/results
"""

import argparse
import csv
import os
import platform
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The python3 runtime's build image (FROM python:3.11-alpine3.19), produced by
# `make build`, so no registry pull is needed.
IMAGE = "tf-build-{arch}-python3"

# Runs inside the container; prints "<workload> <i> <ms>" per iteration.
INNER = r"""
import importlib.util, sys, time

def load(name):
    spec = importlib.util.spec_from_file_location(name, f"/fns/{name}/fn.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def arith(_a, _b):
    # no allocation, no system calls: pure interpreter work
    x = 0
    for i in range(300000):
        x = (x + i * i) % 1000003
    return str(x)

work = {"cpu": load("cpu").fn, "io": load("io").fn, "arith": arith}
n, warm = int(sys.argv[1]), int(sys.argv[2])
for name, f in work.items():
    for i in range(warm + n):
        t0 = time.perf_counter(); f(None, None); t1 = time.perf_counter()
        if i >= warm:
            print(name, i - warm, f"{(t1 - t0) * 1e3:.3f}")
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "benchmarks", "results"))
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()
    ap_arch = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "arm"}[platform.machine()]
    image = IMAGE.format(arch=ap_arch)
    with open(os.path.join(args.out, "inprocess.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["runtime", "round", "workload", "i", "ms"])
        for rnd in range(args.rounds):
            for rt in (["runc", "runsc"] if rnd % 2 == 0 else ["runsc", "runc"]):
                out = subprocess.run(
                    ["docker", "run", "--rm", "--runtime", rt,
                     "-v", os.path.join(REPO, "benchmarks", "fns") + ":/fns:ro",
                     image, "python3", "-c", INNER, str(args.n), str(args.warmup)],
                    check=True, capture_output=True, text=True).stdout
                for line in out.split("\n"):
                    if line:
                        name, i, ms = line.split()
                        w.writerow([rt, rnd, name, i, ms])


if __name__ == "__main__":
    main()
