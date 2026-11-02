
### Cold start via tinyFaaS (upload -> first successful invocation)

| | n | p50 (ms) | p95 (ms) | min | max |
|---|---:|---:|---:|---:|---:|
| runc total | 30 | 1923.86 | 2421.96 | 1859.61 | 2456.42 |
| runsc total | 30 | 1960.71 | 2464.50 | 1873.26 | 2488.80 |
| runc upload call | 30 | 1921.60 | 2419.16 | 1856.93 | 2453.80 |
| runsc upload call | 30 | 1955.39 | 2460.67 | 1869.07 | 2484.64 |
| runc upload return -> first OK | 30 | 2.21 | 3.75 | 1.85 | 4.01 |
| runsc upload return -> first OK | 30 | 4.24 | 5.64 | 3.42 | 7.76 |

### Direct handler container start (docker run -> /health OK)

| | n | p50 (ms) | p95 (ms) | min | max |
|---|---:|---:|---:|---:|---:|
| runc run -> healthy | 30 | 320.81 | 364.09 | 276.30 | 369.01 |
| runsc run -> healthy | 30 | 524.33 | 546.05 | 480.36 | 573.64 |
| runc docker run returns | 30 | 263.13 | 287.84 | 226.92 | 325.67 |
| runsc docker run returns | 30 | 265.87 | 289.59 | 244.58 | 294.33 |
| runc docker rm -f | 30 | 189.50 | 217.93 | 158.27 | 243.23 |
| runsc docker rm -f | 30 | 195.88 | 221.20 | 165.63 | 236.07 |

### Warm request latency (sequential, keep-alive, via rproxy)

| | n | p50 (ms) | p95 (ms) | min | max |
|---|---:|---:|---:|---:|---:|
| echo runc | 400 | 1.38 | 1.77 | 1.06 | 3.39 |
| echo runsc | 400 | 2.87 | 3.96 | 2.09 | 12.58 |
| cpu runc | 400 | 7.74 | 10.30 | 6.25 | 30.57 |
| cpu runsc | 400 | 13.63 | 17.36 | 9.47 | 31.72 |
| io runc | 400 | 22.49 | 34.25 | 16.89 | 377.07 |
| io runsc | 400 | 57.53 | 69.51 | 41.98 | 97.14 |

### Function body timed inside the container (no HTTP)

| | n | p50 (ms) | p95 (ms) | min | max |
|---|---:|---:|---:|---:|---:|
| arith runc | 200 | 24.81 | 31.45 | 23.81 | 39.72 |
| arith runsc | 200 | 25.06 | 32.20 | 24.11 | 43.80 |
| cpu runc | 200 | 5.23 | 8.32 | 4.93 | 11.14 |
| cpu runsc | 200 | 10.94 | 17.52 | 7.31 | 47.49 |
| io runc | 200 | 18.71 | 23.53 | 14.92 | 29.70 |
| io runsc | 200 | 56.29 | 87.70 | 36.96 | 175.41 |

### Ratios

- cold start total: p50 runsc/runc = 1.02x, p95 runsc/runc = 1.02x
- container run -> healthy: p50 runsc/runc = 1.63x, p95 runsc/runc = 1.50x
- warm echo: p50 runsc/runc = 2.08x, p95 runsc/runc = 2.24x
- warm cpu: p50 runsc/runc = 1.76x, p95 runsc/runc = 1.69x
- warm io: p50 runsc/runc = 2.56x, p95 runsc/runc = 2.03x
- in-process arith: p50 runsc/runc = 1.01x, p95 runsc/runc = 1.02x
- in-process cpu: p50 runsc/runc = 2.09x, p95 runsc/runc = 2.11x
- in-process io: p50 runsc/runc = 3.01x, p95 runsc/runc = 3.73x

### Per-round p50 (drift check)

| series | runtime | round | n | p50 (ms) |
|---|---|---:|---:|---:|
| cold | runc | 0 | 15 | 1956.21 |
| cold | runc | 1 | 15 | 1908.29 |
| cold | runsc | 0 | 15 | 2018.25 |
| cold | runsc | 1 | 15 | 1956.01 |
| container | runc | 0 | 15 | 320.82 |
| container | runc | 1 | 15 | 320.81 |
| container | runsc | 0 | 15 | 525.19 |
| container | runsc | 1 | 15 | 524.33 |
| cpu | runc | 0 | 200 | 7.58 |
| cpu | runc | 1 | 200 | 7.96 |
| cpu | runsc | 0 | 200 | 13.96 |
| cpu | runsc | 1 | 200 | 13.25 |
| echo | runc | 0 | 200 | 1.42 |
| echo | runc | 1 | 200 | 1.35 |
| echo | runsc | 0 | 200 | 2.80 |
| echo | runsc | 1 | 200 | 2.95 |
| io | runc | 0 | 200 | 24.86 |
| io | runc | 1 | 200 | 21.29 |
| io | runsc | 0 | 200 | 58.25 |
| io | runsc | 1 | 200 | 57.12 |
