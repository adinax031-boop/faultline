"""Bounded JUnit reader. XML is data, never an instruction or executable."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

MAX_BYTES = 20 * 1024 * 1024
MAX_CASES = 100_000


@dataclass(frozen=True)
class Observation:
    suite: str
    classname: str
    name: str
    attempt: int
    status: str
    duration: float
    message: str


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_junit(path: str | Path) -> list[Observation]:
    """Accept testsuite/testsuites, namespaces, nested suites and retry extensions.

    Repeated test identities are attempts, so shards must not reuse the same
    suite/class/name for different parameterizations.
    """
    with Path(path).open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"JUnit report exceeds {MAX_BYTES} bytes")
    # Reject declarations before parsing; compact NULs to catch UTF-16/32.
    compact = raw.replace(b"\x00", b"")
    if re.search(br"<!\s*(DOCTYPE|ENTITY)\b", compact, re.I):
        raise ValueError("DTD and entity declarations are forbidden")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid JUnit XML: {exc}") from exc
    if local(root.tag) not in {"testsuite", "testsuites"}:
        raise ValueError("Expected a JUnit testsuite or testsuites root")
    rows: list[Observation] = []
    attempts: dict[tuple[str, str, str], int] = {}
    # Iterative traversal avoids Python recursion limits with nested suites.
    stack = [(root, "")]
    while stack:
        node, suite = stack.pop()
        kind = local(node.tag)
        if kind == "testsuite":
            suite = node.get("name", suite)
        if kind == "testcase":
            name = node.get("name")
            if not name:
                raise ValueError("Every testcase needs a nonempty name")
            classname = node.get("classname", "")
            identity = (suite, classname, name)
            try:
                duration = float(node.get("time", "0"))
            except ValueError as exc:
                raise ValueError(f"Invalid duration for {name}") from exc
            if not math.isfinite(duration) or duration < 0:
                raise ValueError(f"Invalid duration for {name}")
            children = list(node)
            retries = [c for c in children if local(c.tag) in {"flakyFailure", "flakyError", "rerunFailure", "rerunError"}]
            failures = [c for c in children if local(c.tag) in {"failure", "error"}]
            skipped = any(local(c.tag) == "skipped" for c in children)
            # Maven flakyFailure records failed attempts before a final pass.
            # rerunFailure with a final failure remains a failure, never a pass.
            for child in retries + [None]:
                attempt = attempts.get(identity, 0)
                attempts[identity] = attempt + 1
                problem = child if child is not None else (failures[0] if failures else None)
                status = "failed" if problem is not None else ("skipped" if skipped else "passed")
                message = "" if problem is None else (problem.get("message", "") + "\n" + "".join(problem.itertext())).strip()[:4000]
                rows.append(Observation(suite, classname, name, attempt, status, duration if child is None else 0.0, message))
                if len(rows) > MAX_CASES:
                    raise ValueError(f"JUnit report exceeds {MAX_CASES} observations")
        else:
            stack.extend((child, suite) for child in reversed(list(node)))
    if not rows:
        raise ValueError("JUnit report contains no testcases")
    return rows
