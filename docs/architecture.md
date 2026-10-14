# Architecture and methodology

## Data flow

JUnit XML → bounded parser → atomic SQLite store → pure analysis → HTML / JSON / Markdown.

The standard-library-only runtime is usable offline. The parser has a 20 MiB byte limit and 100,000 observation limit per report. DTD/entity declarations are rejected before XML parsing, including UTF-16/32 declarations. Namespaced suites are accepted. Durations must be finite and nonnegative. Ingestion uses an immediate transaction, foreign keys and a busy timeout. The schema is versioned; incompatible schemas fail closed. There is no migration system yet.

## Identity and provenance

A report is identified by `(run_id, shard)`. Its semantic digest is SHA-256 over normalized observations, including failure samples (truncated to 4,000 characters). Whitespace-only changes outside parsed fields do not create a new import. Runs must share revision and environment across shards. A test group is `(suite, classname, name, environment)`; duplicate testcase identities form numbered attempts in document order. Nested suites use the nearest suite name, not a concatenated path. Ensure leaf suite names/class names distinguish your tests.

Full revisions and detailed environments are supplied by the caller. Faultline does not fetch code, dependencies or infrastructure to validate them. A repeated CI execution should use a new run ID. For parameterized cases, names must distinguish parameters.

## Instability evidence

For each test/environment group, collect executed outcomes per revision. At least one pass and one failure under the same revision is labeled same-revision instability. Skips supply no pass/fail evidence. A mixture exclusively across different revisions is cross-revision variation. This prevents a simple regression or fix from automatically becoming a flakiness finding.

Same-revision observations can still differ in external state, random seeds, time or infrastructure. Classification is an observation, not a causal attribution. The tool does not infer a final retry outcome beyond the documented XML conventions. Maven flakyFailure/flakyError entries precede the final testcase outcome; rerunFailure/rerunError entries are failed attempts. Actual retry timing is not inferred.

## Statistics and rerun ranking

For `f` failures among `n` executed attempts, report `p = f/n` and the 95% Wilson score interval (`z = 1.959963984540054`). Empty histories have a null proportion and interval `[0,1]`. Boundary intervals include exactly 0 or 1 where appropriate.

Rerun priority = `weight × 4p(1-p) / (1 + median_positive_duration_seconds)`, where weight is 2 for a group with mixed same-revision evidence and 1 otherwise. This ranks mixed, inexpensive cases first. It is neither a calibrated prediction nor a recommended retry count. It gives persistent failures and all-passing groups a zero priority; those still deserve attention through finding filters.

Retries and shards can be correlated. The interval does not account for clustering, censoring, adaptive reruns, selection bias, or drift. Compare groups only when sampling policies are comparable.

## Failure clusters

Lowercase messages, normalize whitespace, UUIDs, hex addresses and numeric values, then SHA-256 the normalized message. A cluster holds occurrence counts, test IDs and an original sample. This is intentionally inspectable, but unrelated failures may share a fingerprint and stack differences may split related failures. No root cause is assigned.

## Output safety and privacy

JSON uses a schema version and disallows NaN. HTML embeds escaped JSON and populates content with DOM `textContent`, never untrusted `innerHTML`. The dashboard has no network requests. Markdown escapes table separators, newlines and raw HTML. Databases and reports retain potentially sensitive test names, environments and failure samples. Redact upstream and apply your own filesystem permissions and retention policies.

## Future work

Real-world dialect fixtures, timestamp-aware sequence analysis, run-clustered uncertainty, manifest batches, baselines and adapters are open directions. These are not shipped features. Evidence on representative CI histories is needed before comparative state-of-the-art claims.
