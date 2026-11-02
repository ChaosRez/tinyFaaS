#!/usr/bin/env python3
# Baseline: returns its input. Measures the request path (rproxy -> handler) only.
import typing


def fn(input: typing.Optional[str], headers: typing.Optional[typing.Dict[str, str]]) -> typing.Optional[str]:
    return input
