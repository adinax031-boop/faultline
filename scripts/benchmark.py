"""Reproducible synthetic workload, not a comparison to competing tools."""
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from faultline.analysis import analyze
from faultline.store import Store

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    report = root / 'report.xml'
    report.write_text('<testsuite name="load">' + ''.join(f'<testcase name="test_{i}" time="0.01">' + ('<failure message="Timeout 123"/>' if i % 10 == 0 else '') + '</testcase>' for i in range(10000)) + '</testsuite>', encoding='utf-8')
    with Store(root / 'history.db') as store:
        start = time.perf_counter()
        count = store.ingest(report, run_id='benchmark', revision='synthetic')
        imported = time.perf_counter()
        result = analyze(store.observations())
        finished = time.perf_counter()
    assert count == 10000 and result['summary']['tests'] == 10000
    print(f'{count} observations | ingest {imported-start:.3f}s | analyze {finished-imported:.3f}s')
