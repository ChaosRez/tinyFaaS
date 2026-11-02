# gVisor (runsc) vs runc for tinyFaaS function handlers

This report measures what it costs to run tinyFaaS function handlers in a gVisor sandbox
(`TF_CONTAINER_RUNTIME=runsc`) instead of Docker's default runc.
Every number below was measured on the host described under [Host](#host).
The raw data is in [`results/`](./results) and the summary tables are produced by
[`summarize.py`](./summarize.py).

## Summary

| Metric (p50) | runc | runsc | runsc − runc | runsc / runc |
| --- | ---: | ---: | ---: | ---: |
| Cold start via tinyFaaS (upload → first OK) | 1923.86 ms | 1960.71 ms | +36.85 ms | 1.02× |
| Handler container start (`docker run` → `/health` OK) | 320.81 ms | 524.33 ms | +203.52 ms | 1.63× |
| Warm `echo` (request path only) | 1.38 ms | 2.87 ms | +1.49 ms | 2.08× |
| Warm `cpu` (sieve, allocation-heavy) | 7.74 ms | 13.63 ms | +5.89 ms | 1.76× |
| Warm `io` (file-system work) | 22.49 ms | 57.53 ms | +35.04 ms | 2.56× |
| In-container pure arithmetic loop (no syscalls) | 24.81 ms | 25.06 ms | +0.25 ms | 1.01× |

- Code that stays in user space runs at native speed under gVisor (1.01×).
- Anything that crosses into the kernel gets slower: system calls, page faults and network I/O.
  The filesystem-heavy function is 2.6× slower end to end and 3.0× slower measured inside the container.
- The sandbox adds about 200 ms to handler start on this host.
  Measured through tinyFaaS, almost all of that is hidden by tinyFaaS' fixed 1 s readiness poll (see [Cold start](#cold-start)).

Results come from one host and one configuration: a nested VM without KVM, using gVisor's default `systrap` platform.
They show where the overhead comes from, not what it would be on other hardware.

## Host

The benchmark ran in a Linux cloud VM (the Claude Code remote environment), not on Reza's Raspberry Pi or GCP VM.
It is a real Linux kernel with a real Docker daemon, not Docker Desktop.
Values are from [`results/env.json`](./results/env.json), recorded by the benchmark script, plus the gVisor defaults read with `runsc flags`.

| | |
| --- | --- |
| Date | 2026-11-02 (UTC) |
| CPU | Intel(R) Xeon(R) Processor @ 2.10GHz, 4 vCPUs (CPU `hypervisor` flag set) |
| Memory | 16 GB (16477352 kB) |
| Kernel | Linux 6.18.44-fc-v185 (x86_64), a Firecracker guest kernel; `/dev/kvm` not available |
| OS | Ubuntu 24.04.5 LTS |
| Docker | Engine 29.9.2, storage driver overlayfs (containerd snapshotter), cgroupfs, cgroup v1 |
| runc | 1.5.2 |
| gVisor | runsc release-20261026.0 (OCI spec 1.2.1), installed from the release tarball with a verified SHA-512 checksum, registered with `runsc install` |
| gVisor config | defaults, no `runtimeArgs`: platform `systrap`, rootfs `overlay2=root:self`, gVisor's netstack |
| Handler runtime | tinyFaaS `python3` runtime (python:3.11-alpine3.19), `threads: 1` |
| Benchmark driver | Python 3.13.18 on the same host, talking to `127.0.0.1` |

Because there is no KVM, gVisor uses `systrap`, its default platform.
Page faults and system calls in the sandbox are trapped and handed to the Sentry, gVisor's user-space kernel.
On bare metal, or with the `kvm` platform, absolute overheads will differ.
Rerun the scripts on the target host before quoting numbers for it.

## Method

All scripts use only the Python standard library and are in this directory.

1. **Code under test.** This branch adds `TF_CONTAINER_RUNTIME`, which sets Docker `HostConfig.Runtime` on every handler container.
   When the variable is unset, behaviour is unchanged.
2. **Driver.** [`bench_gvisor.py`](./bench_gvisor.py) runs two rounds.
   In each round it starts the tinyFaaS binary once per runtime, alternating the order (round 0: runc then runsc; round 1: runsc then runc) so host drift doesn't favour either runtime.
   After every sample it runs `docker inspect` on the handler container and records `HostConfig.Runtime` in the CSV.
   `summarize.py` refuses to produce numbers if any row's inspected runtime differs from its label.
3. **(a) Cold start through tinyFaaS**, 30 per runtime (2 rounds × 15):
   - The clock starts just before `POST /upload` of a fresh, uniquely named `echo` function.
   - It stops when `POST :8000/<name>` first returns 200 with the echoed body (polled every 5 ms).
   - Columns: `upload_ms` is the time until `/upload` returns (image build, network, container create and start, readiness wait, rproxy registration). `upload_to_first_ok_ms` is the rest.
   - Each function is deleted after its sample.
4. **(a′) Direct handler container start**, 30 per runtime:
   - The exact image tinyFaaS builds for `echo` is started with `docker run -d --runtime X` on a bridge network.
   - The clock stops when `GET <ip>:8000/health` returns 200, polled every 5 ms.
   - This isolates the sandbox's start cost from tinyFaaS' own readiness loop.
5. **(b) Warm latency**, 400 requests per runtime and function (2 rounds × 200, after 20 discarded warm-up requests):
   - Requests are sequential over one keep-alive HTTP connection through tinyFaaS' rproxy.
   - Each latency is the client's `perf_counter` time from sending the request to reading the full response.
   - Functions are in [`fns/`](./fns):
     - `echo`: returns its input; measures only the request path.
     - `cpu`: pure-Python sieve of Eratosthenes up to 200000 (17984 primes). It allocates bytearrays, so it page-faults (about 130 minor faults per call, measured with `getrusage` under runc), but it makes almost no system calls (`strace -c`: 6 extra syscalls over 10 calls).
     - `io`: 200 × (create, write 4 KiB, close, stat, unlink), then write 4 MiB in 64 KiB chunks, `fsync`, read it back, unlink. `strace -c` counts about 1,744 syscalls per call (18013 for 10 calls vs 572 for interpreter start-up alone).
6. **In-container timing.** [`bench_inprocess.py`](./bench_inprocess.py) runs the same `cpu` and `io` function bodies, plus a pure arithmetic loop (`arith`, no allocation and no syscalls), inside a container under each runtime with no HTTP. It records 200 iterations per runtime (2 rounds × 100, after 10 warm-up iterations). Comparing this with (b) separates the cost to the function body from the cost on the network path.

Percentiles are nearest-rank.
The `strace` counts were taken on the host's Python 3.13, not inside the Python 3.11 container.
They show the syscall profile of the function bodies and were not used in any timing.

Reproduce on a Linux host with Docker and runsc registered:

```bash
make build
sudo python3 benchmarks/bench_gvisor.py --out benchmarks/results
sudo python3 benchmarks/bench_inprocess.py --out benchmarks/results
python3 benchmarks/summarize.py benchmarks/results
```

## Results

All times in milliseconds.

### Cold start

Cold start via tinyFaaS (upload → first successful invocation):

| | n | p50 | p95 | min | max |
|---|---:|---:|---:|---:|---:|
| runc total | 30 | 1923.86 | 2421.96 | 1859.61 | 2456.42 |
| runsc total | 30 | 1960.71 | 2464.50 | 1873.26 | 2488.80 |
| runc `/upload` call | 30 | 1921.60 | 2419.16 | 1856.93 | 2453.80 |
| runsc `/upload` call | 30 | 1955.39 | 2460.67 | 1869.07 | 2484.64 |
| runc upload return → first OK | 30 | 2.21 | 3.75 | 1.85 | 4.01 |
| runsc upload return → first OK | 30 | 4.24 | 5.64 | 3.42 | 7.76 |

Direct handler container start (`docker run` → `/health` OK):

| | n | p50 | p95 | min | max |
|---|---:|---:|---:|---:|---:|
| runc run → healthy | 30 | 320.81 | 364.09 | 276.30 | 369.01 |
| runsc run → healthy | 30 | 524.33 | 546.05 | 480.36 | 573.64 |
| runc `docker run -d` returns | 30 | 263.13 | 287.84 | 226.92 | 325.67 |
| runsc `docker run -d` returns | 30 | 265.87 | 289.59 | 244.58 | 294.33 |
| runc `docker rm -f` | 30 | 189.50 | 217.93 | 158.27 | 243.23 |
| runsc `docker rm -f` | 30 | 195.88 | 221.20 | 165.63 | 236.07 |

### Warm latency through tinyFaaS

| | n | p50 | p95 | min | max |
|---|---:|---:|---:|---:|---:|
| echo runc | 400 | 1.38 | 1.77 | 1.06 | 3.39 |
| echo runsc | 400 | 2.87 | 3.96 | 2.09 | 12.58 |
| cpu runc | 400 | 7.74 | 10.30 | 6.25 | 30.57 |
| cpu runsc | 400 | 13.63 | 17.36 | 9.47 | 31.72 |
| io runc | 400 | 22.49 | 34.25 | 16.89 | 377.07 |
| io runsc | 400 | 57.53 | 69.51 | 41.98 | 97.14 |

The 377 ms maximum for `io`/runc is a single outlier. It doesn't move p50 or p95.

### Function body inside the container (no HTTP)

| | n | p50 | p95 | min | max |
|---|---:|---:|---:|---:|---:|
| arith runc | 200 | 24.81 | 31.45 | 23.81 | 39.72 |
| arith runsc | 200 | 25.06 | 32.20 | 24.11 | 43.80 |
| cpu runc | 200 | 5.23 | 8.32 | 4.93 | 11.14 |
| cpu runsc | 200 | 10.94 | 17.52 | 7.31 | 47.49 |
| io runc | 200 | 18.71 | 23.53 | 14.92 | 29.70 |
| io runsc | 200 | 56.29 | 87.70 | 36.96 | 175.41 |

### Drift check (p50 per round)

| series | runtime | round 0 | round 1 |
|---|---|---:|---:|
| cold start | runc | 1956.21 | 1908.29 |
| cold start | runsc | 2018.25 | 1956.01 |
| container start | runc | 320.82 | 320.81 |
| container start | runsc | 525.19 | 524.33 |
| echo | runc | 1.42 | 1.35 |
| echo | runsc | 2.80 | 2.95 |
| cpu | runc | 7.58 | 7.96 |
| cpu | runsc | 13.96 | 13.25 |
| io | runc | 24.86 | 21.29 |
| io | runsc | 58.25 | 57.12 |

Both rounds agree closely, with the run order reversed between them.

### Raw data

| File | Rows | Content |
| --- | ---: | --- |
| [`results/cold.csv`](./results/cold.csv) | 60 | cold starts via tinyFaaS |
| [`results/container.csv`](./results/container.csv) | 60 | direct container starts |
| [`results/warm.csv`](./results/warm.csv) | 2400 | warm request latencies |
| [`results/inprocess.csv`](./results/inprocess.csv) | 1200 | in-container function timings |
| [`results/env.json`](./results/env.json) | | host, kernel, Docker and gVisor versions |
| [`results/summary.md`](./results/summary.md) | | output of `summarize.py` |
| `results/tinyfaas-{runc,runsc}.log.gz` | | full tinyFaaS manager logs of the run |

## Interpretation

**Where gVisor costs nothing.**
The arithmetic loop runs at the same speed under both runtimes (25.06 vs 24.81 ms, 1.01×).
gVisor doesn't emulate the CPU.
Guest instructions run natively, and the sandbox only steps in when the guest enters the kernel.

**System calls and page faults.**
gVisor's Sentry is a user-space kernel written in Go.
Every guest system call is intercepted (here by the `systrap` platform) and served by the Sentry.
File operations then go through gVisor's own VFS and its overlay root file system, not straight to the host kernel.
Each crossing costs much more than a native syscall.

- The `io` function makes about 1,700 syscalls per call. Inside the container it is 3.0× slower at p50 (56.29 vs 18.71 ms) and 3.7× at p95.
- The `cpu` sieve makes almost no syscalls but takes about 130 minor page faults per call. Under `systrap` those faults are also handled by the Sentry, which fits its 2.1× slowdown in-process (10.94 vs 5.23 ms). This is an explanation consistent with the measurements, not a measured attribution: the faults were not timed one by one.
- These deltas carry over almost one-for-one to the end-to-end numbers: +5.71 ms in-process vs +5.89 ms end to end for `cpu`, and +37.58 ms vs +35.04 ms for `io`. So for real work, most of the cost is in the function body, not in the HTTP path.

**Network path.**
The `echo` function does almost nothing, yet its request costs 1.49 ms more under gVisor (2.87 vs 1.38 ms).
Inside the sandbox, the handler's TCP traffic goes through gVisor's own network stack (netstack), not the host's.
For very short functions this fixed cost dominates (2.1×), and the tail is longer (12.58 ms max vs 3.39 ms).

**Cold start.**
Starting the sandbox (Sentry, Gofer, and booting the guest's Python under gVisor) adds about 200 ms to `docker run` → healthy (524 vs 321 ms p50).
`docker run -d` itself returns just as fast for both runtimes (about 265 ms), and teardown costs the same.
Through tinyFaaS, the difference shrinks to +37 ms (1.02×) because of tinyFaaS' readiness loop:

- It probes `/health` right after `ContainerStart`, and on failure sleeps a fixed 1 s.
- In the manager logs of this run, every handler under both runtimes failed the first probe exactly once and waited 1 s (36 of 36 under each runtime).
- Together with the image build that every upload performs, that 1 s sleep hides the sandbox's 200 ms.
- A finer-grained poll (for example 10–50 ms) would cut tinyFaaS cold starts for both runtimes and would expose gVisor's startup cost.

**The tradeoff.**
gVisor puts a second kernel boundary between untrusted function code and the host kernel.
A handler exploiting a Linux syscall bug first has to get through the Sentry, which implements syscalls itself and uses only a narrow, seccomp-filtered set of host syscalls.
On this host that isolation costs:

- nothing for pure computation;
- about 2× for allocation-heavy code;
- about 3× for filesystem-heavy code;
- about 1.5 ms per request on the network path;
- about 200 ms per sandbox start.

For a FaaS platform whose own README warns that anyone on the network can run arbitrary code in its containers, opt-in gVisor is a sensible default for untrusted tenants.
I/O-heavy or latency-critical trusted functions can stay on runc.

## Limitations

- One host, a nested Firecracker VM without KVM: gVisor ran on `systrap` and was not compared with its `kvm` platform. No Raspberry Pi or arm64 data.
- One handler language (Python 3.11), `threads: 1`, sequential requests from one client. Concurrency and throughput were not measured.
- Default gVisor settings. `--overlay2`, `--network=host` and `--file-access` options trade some isolation for speed and were not explored.
- Cold start always includes building the function image. Image build steps run under Docker's build runtime, not the handler runtime, so they cost the same for both.
- The rproxy only starts with at least two protocols enabled (an upstream argument check), so the benchmark keeps the gRPC endpoint enabled and disables only CoAP.
