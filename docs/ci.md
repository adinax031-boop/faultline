# CI integration

Faultline reads reports you supply. A single execution usually cannot establish instability. Preserve the SQLite database or re-import earlier reports with correct run/revision/environment metadata before evaluating a gate.

## GitHub Actions step example

```yaml
- name: Install Faultline from a reviewed source checkout
  run: python -m pip install ./tools/faultline
- name: Import JUnit
  if: always()
  run: >-
    faultline ingest junit.xml --db history.db
    --run "${{ github.run_id }}-attempt-${{ github.run_attempt }}"
    --revision "${{ github.sha }}"
    --environment "ubuntu-python312-lock-v1"
- name: Produce report
  if: always()
  run: faultline report --db history.db --output reliability.html
- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: faultline-report
    path: reliability.html
```

This snippet assumes a reviewed Faultline checkout exists at `tools/faultline`, your runner has Python, and your test step emitted `junit.xml`. Set provenance to match the actual tested code (PR merge SHA and head SHA may differ). Use per-matrix environment labels and per-report shards. Never disguise separate executions as a single run.

## Durable history

Artifact upload alone does not restore past history. Choose a durable store appropriate to your project: download and import a controlled set of past JUnit artifacts, or restore a database snapshot and save the updated snapshot. Serialize writers; SQLite is a local database, not a distributed merge format. Cache eviction, branch-specific cache keys and concurrent cache writes can make a cache unreliable as the only historical source. Do not persist an empty/new history as if it were a complete baseline.

## Policy

Start with reports for human review. Add `--fail-on-instability` when you deliberately want any observed same-revision mixed outcome to fail a job. The gate applies to all imported history, including old findings; there is no time window or resolved-finding lifecycle yet. For scoped evaluation, construct a database from the exact reports you wish to evaluate. Do not quarantine tests automatically from one finding.

Review exported failure text before making artifacts public. Faultline does not redact secrets on your behalf.
