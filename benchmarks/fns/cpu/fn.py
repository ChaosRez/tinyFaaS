#!/usr/bin/env python3
# CPU-bound: sieve of Eratosthenes up to N (default 200000), pure Python.
# Performs almost no system calls, so it shows the cost of the sandbox when
# the guest stays in user space.
import typing


def fn(input: typing.Optional[str], headers: typing.Optional[typing.Dict[str, str]]) -> typing.Optional[str]:
    n = int(input) if input else 200000
    sieve = bytearray([1]) * (n + 1)
    sieve[0:2] = b"\x00\x00"
    i = 2
    while i * i <= n:
        if sieve[i]:
            sieve[i * i :: i] = bytearray(len(range(i * i, n + 1, i)))
        i += 1
    count = 0
    for v in sieve:
        count += v
    return str(count)
