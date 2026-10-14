"""Transparent heuristics; observed instability is not a causal diagnosis."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import math
import re
from statistics import median


def wilson(failures: int, total: int) -> tuple[float, float]:
    """95% Wilson score interval for an observed failure proportion."""
    if total == 0:
        return (0.0, 1.0)
    z = 1.959963984540054
    p = failures / total
    d = 1 + z*z/total
    centre = (p + z*z/(2*total))/d
    half = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/d
    return (0.0 if failures == 0 else max(0.0, centre-half),
            1.0 if failures == total else min(1.0, centre+half))


def signature(message: str) -> str:
    text = message.lower()
    text = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<uuid>", text)
    text = re.sub(r"0x[0-9a-f]+", "<hex>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", text)
    return re.sub(r"\s+", " ", text).strip() or "unknown failure"


def analyze(rows: list[dict]) -> dict:
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        groups[(row["suite"], row["classname"], row["name"], row["environment"])].append(row)
    tests = []
    clusters: dict[str, dict] = {}
    for key, history in sorted(groups.items()):
        suite, classname, name, environment = key
        test_id = hashlib.sha256(repr(key).encode()).hexdigest()[:16]
        eligible = [r for r in history if r["status"] != "skipped"]
        failures = sum(r["status"] == "failed" for r in eligible)
        by_revision: dict[str, set] = defaultdict(set)
        by_run: dict[str, set] = defaultdict(set)
        for row in eligible:
            by_revision[row["revision"]].add(row["status"])
            by_run[row["run_id"]].add(row["status"])
        mixed = sorted(rev for rev, outcomes in by_revision.items() if len(outcomes) > 1)
        recovered = sorted(run for run, outcomes in by_run.items() if len(outcomes) > 1)
        if mixed:
            classification = "same-revision instability"
        elif failures and failures < len(eligible):
            classification = "cross-revision variation"
        elif failures:
            classification = "consistent failure"
        elif eligible:
            classification = "no failure observed"
        else:
            classification = "only skipped"
        lo, hi = wilson(failures, len(eligible))
        durations = [r["duration"] for r in eligible if r["duration"] > 0]
        med = median(durations) if durations else 0
        # A rerun has most information when outcomes are mixed and cost is low.
        # This is a prioritization heuristic, not a calibrated probability.
        uncertainty = 4*(failures/len(eligible))*(1-failures/len(eligible)) if eligible else 0
        priority = round((2 if mixed else 1)*uncertainty/(1 + med), 6)
        test = dict(id=test_id, suite=suite, classname=classname, name=name,
                    environment=environment, classification=classification,
                    observations=len(history), executed=len(eligible), failures=failures,
                    skipped=len(history)-len(eligible), failure_rate=failures/len(eligible) if eligible else None,
                    interval=[lo, hi], median_seconds=med, rerun_priority=priority,
                    mixed_revisions=mixed, mixed_runs=recovered,
                    history=[dict(run=r["run_id"], shard=r["shard"], revision=r["revision"], attempt=r["attempt"], status=r["status"], seconds=r["duration"]) for r in history])
        tests.append(test)
        for row in history:
            if row["status"] != "failed":
                continue
            normalized = signature(row["message"])
            cluster_id = hashlib.sha256(normalized.encode()).hexdigest()[:16]
            cluster = clusters.setdefault(cluster_id, dict(id=cluster_id, signature=normalized, occurrences=0, tests=set(), example=row["message"]))
            cluster["occurrences"] += 1
            cluster["tests"].add(test_id)
    tests.sort(key=lambda t: (-t["rerun_priority"], t["id"]))
    cluster_list = []
    for cluster in clusters.values():
        cluster["tests"] = sorted(cluster["tests"])
        cluster_list.append(cluster)
    cluster_list.sort(key=lambda c: (-c["occurrences"], c["id"]))
    return dict(schema_version=1, summary=dict(tests=len(tests), observations=len(rows),
                runs=len({r["run_id"] for r in rows}),
                unstable=sum(bool(t["mixed_revisions"]) for t in tests),
                failures=sum(t["failures"] for t in tests)), tests=tests, clusters=cluster_list,
                methodology="Same revision and environment, mixed pass/fail = observed instability. Cross-revision changes are not called flaky. Wilson intervals describe attempt proportions; correlated retries violate independence. Priority is an information/cost heuristic. History is ordered by run ID, not time.")
