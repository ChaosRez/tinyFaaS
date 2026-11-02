#!/usr/bin/env python3
"""Summarise the CSVs written by bench_gvisor.py as Markdown tables (stdlib only).

    python3 benchmarks/summarize.py benchmarks/results
"""

import csv
import os
import sys
from collections import defaultdict


def pct(xs, p):
    """Nearest-rank percentile."""
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, -(-p * len(xs) // 100) - 1))
    return xs[int(k)]


def stats(xs):
    return len(xs), pct(xs, 50), pct(xs, 95), min(xs), max(xs)


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def check_runtime(rows):
    for r in rows:
        want = r["runtime"]
        if r["inspected_runtime"] != want:
            sys.exit(f"row ran under {r['inspected_runtime']!r}, labelled {want!r}: {r}")


def table(title, groups, unit="ms"):
    print(f"\n### {title}\n")
    print(f"| | n | p50 ({unit}) | p95 ({unit}) | min | max |")
    print("|---|---:|---:|---:|---:|---:|")
    for key, xs in groups:
        n, p50, p95, lo, hi = stats(xs)
        print(f"| {key} | {n} | {p50:.2f} | {p95:.2f} | {lo:.2f} | {hi:.2f} |")


def ratio_line(name, a, b):
    print(f"- {name}: p50 runsc/runc = {pct(b, 50) / pct(a, 50):.2f}x, "
          f"p95 runsc/runc = {pct(b, 95) / pct(a, 95):.2f}x")


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "results")
    cold, cont, warm = (load(os.path.join(d, f)) for f in ("cold.csv", "container.csv", "warm.csv"))
    for rows in (cold, cont, warm):
        check_runtime(rows)
    rts = ["runc", "runsc"]

    def col(rows, c, **flt):
        return [float(r[c]) for r in rows if all(r[k] == v for k, v in flt.items())]

    table("Cold start via tinyFaaS (upload -> first successful invocation)",
          [(f"{rt} total", col(cold, "cold_start_ms", runtime=rt)) for rt in rts]
          + [(f"{rt} upload call", col(cold, "upload_ms", runtime=rt)) for rt in rts]
          + [(f"{rt} upload return -> first OK", col(cold, "upload_to_first_ok_ms", runtime=rt)) for rt in rts])
    table("Direct handler container start (docker run -> /health OK)",
          [(f"{rt} run -> healthy", col(cont, "run_to_healthy_ms", runtime=rt)) for rt in rts]
          + [(f"{rt} docker run returns", col(cont, "docker_run_ms", runtime=rt)) for rt in rts]
          + [(f"{rt} docker rm -f", col(cont, "remove_ms", runtime=rt)) for rt in rts])
    fns = ["echo", "cpu", "io"]
    table("Warm request latency (sequential, keep-alive, via rproxy)",
          [(f"{fn} {rt}", col(warm, "latency_ms", runtime=rt, function=fn)) for fn in fns for rt in rts])

    ip_path = os.path.join(d, "inprocess.csv")
    inproc = load(ip_path) if os.path.exists(ip_path) else []
    if inproc:
        wls = ["arith", "cpu", "io"]
        table("Function body timed inside the container (no HTTP)",
              [(f"{wl} {rt}", col(inproc, "ms", runtime=rt, workload=wl)) for wl in wls for rt in rts])

    print("\n### Ratios\n")
    ratio_line("cold start total", col(cold, "cold_start_ms", runtime="runc"), col(cold, "cold_start_ms", runtime="runsc"))
    ratio_line("container run -> healthy", col(cont, "run_to_healthy_ms", runtime="runc"),
               col(cont, "run_to_healthy_ms", runtime="runsc"))
    for fn in fns:
        ratio_line(f"warm {fn}", col(warm, "latency_ms", runtime="runc", function=fn),
                   col(warm, "latency_ms", runtime="runsc", function=fn))

    for wl in (["arith", "cpu", "io"] if inproc else []):
        ratio_line(f"in-process {wl}", col(inproc, "ms", runtime="runc", workload=wl),
                   col(inproc, "ms", runtime="runsc", workload=wl))

    print("\n### Per-round p50 (drift check)\n")
    per = defaultdict(list)
    for r in warm:
        per[(r["function"], r["runtime"], r["round"])].append(float(r["latency_ms"]))
    for r in cont:
        per[("container", r["runtime"], r["round"])].append(float(r["run_to_healthy_ms"]))
    for r in cold:
        per[("cold", r["runtime"], r["round"])].append(float(r["cold_start_ms"]))
    print("| series | runtime | round | n | p50 (ms) |")
    print("|---|---|---:|---:|---:|")
    for k in sorted(per):
        print(f"| {k[0]} | {k[1]} | {k[2]} | {len(per[k])} | {pct(per[k], 50):.2f} |")


if __name__ == "__main__":
    main()
