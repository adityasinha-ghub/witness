"""A tiny "legacy" module with no tests — the kind witness gives a safety net to.

Note there are no witness imports here: the demo records these functions by
wrapping them externally, so witness can net code you don't want to edit.
"""

import re


def slugify(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def parse_kv(line):
    out = {}
    for pair in line.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        key, _, val = pair.partition("=")
        out[key.strip()] = val.strip()
    return out


def median(nums):
    if not nums:
        raise ValueError("median() of empty sequence")
    ordered = sorted(nums)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def word_count(text):
    return len(text.split())
