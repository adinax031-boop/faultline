import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from faultline.analysis import analyze, signature, wilson
from faultline.cli import demo_data, main
from faultline.junit import parse_junit
from faultline.report import html_report, markdown_report
from faultline.store import Store


class FaultlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.xml = self.root / 'junit.xml'
        self.db = self.root / 'history.db'

    def write(self, body):
        self.xml.write_text(body, encoding='utf-8')
        return self.xml

    def case(self, status='passed', name='test', time='1'):
        child = '<failure message="Timeout 123"/>' if status == 'failed' else '<skipped/>' if status == 'skipped' else ''
        return f'<testsuite name="suite"><testcase classname="C" name="{name}" time="{time}">{child}</testcase></testsuite>'


    def test_namespaces_and_nested_suites(self):
        p = self.write('<testsuites xmlns="urn:junit"><testsuite name="outer"><testsuite name="inner"><testcase name="x"/></testsuite></testsuite></testsuites>')
        self.assertEqual(parse_junit(p)[0].suite, 'inner')

    def test_maven_recovered_retry(self):
        p = self.write('<testsuite><testcase name="x"><flakyFailure message="oops"/></testcase></testsuite>')
        self.assertEqual([r.status for r in parse_junit(p)], ['failed', 'passed'])

    def test_failed_reruns_never_invent_pass(self):
        p = self.write('<testsuite><testcase name="x"><failure/><rerunFailure/></testcase></testsuite>')
        self.assertEqual([r.status for r in parse_junit(p)], ['failed', 'failed'])

    def test_duplicate_cases_are_attempts(self):
        rows = parse_junit(self.write('<testsuite><testcase name="x"><failure/></testcase><testcase name="x"/></testsuite>'))
        self.assertEqual([r.attempt for r in rows], [0, 1])

    def test_invalid_xml_and_empty_reports(self):
        for body in ['<testsuite>', '<other/>', '<testsuite/>', '<testsuite><testcase/></testsuite>']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_junit(self.write(body))

    def test_forbidden_entities_in_utf_encodings(self):
        body = '<!DOCTYPE testsuite [<!ENTITY x "unsafe">]><testsuite><testcase name="&x;"/></testsuite>'
        for encoding in ['utf-8', 'utf-16', 'utf-32']:
            self.xml.write_bytes(body.encode(encoding))
            with self.subTest(encoding=encoding), self.assertRaises(ValueError):
                parse_junit(self.xml)

    def test_invalid_durations(self):
        for time in ['nan', 'inf', '-1', 'oops']:
            with self.subTest(time=time), self.assertRaises(ValueError):
                parse_junit(self.write(self.case(time=time)))

    def test_idempotence_and_conflicting_import(self):
        with Store(self.db) as store:
            self.write(self.case())
            self.assertEqual(store.ingest(self.xml, run_id='r', revision='abc'), 1)
            self.assertEqual(store.ingest(self.xml, run_id='r', revision='abc'), 0)
            self.write(self.case('failed'))
            with self.assertRaises(ValueError):
                store.ingest(self.xml, run_id='r', revision='abc')
            self.assertEqual(len(store.observations()), 1)

    def test_shard_provenance_and_rollback(self):
        with Store(self.db) as store:
            self.write(self.case())
            store.ingest(self.xml, run_id='r', revision='abc', shard='one')
            with self.assertRaises(ValueError):
                store.ingest(self.xml, run_id='r', revision='def', shard='two')
            store.ingest(self.xml, run_id='r', revision='abc', shard='two')
            self.assertEqual(len(store.observations()), 2)

    def test_schema_rejection(self):
        with Store(self.db) as store:
            store.db.execute('UPDATE meta SET version=99')
            store.db.commit()
        with self.assertRaises(ValueError):
            Store(self.db)

    def history(self, revisions, statuses, environments=None):
        with Store(self.db) as store:
            for i, (revision, status) in enumerate(zip(revisions, statuses)):
                self.write(self.case(status))
                store.ingest(self.xml, run_id=f'r{i}', revision=revision, environment=(environments or ['linux'] * len(revisions))[i])
            return analyze(store.observations())

    def test_same_revision_instability(self):
        data = self.history(['a', 'a'], ['failed', 'passed'])
        self.assertEqual(data['summary']['unstable'], 1)
        self.assertEqual(data['tests'][0]['mixed_revisions'], ['a'])

    def test_cross_revision_not_flaky(self):
        data = self.history(['a', 'b'], ['failed', 'passed'])
        self.assertEqual(data['summary']['unstable'], 0)
        self.assertEqual(data['tests'][0]['classification'], 'cross-revision variation')

    def test_environments_are_isolated(self):
        data = self.history(['a', 'a'], ['failed', 'passed'], ['linux', 'windows'])
        self.assertEqual(data['summary']['unstable'], 0)
        self.assertEqual(data['summary']['tests'], 2)

    def test_skips_not_counted_as_passes(self):
        data = self.history(['a', 'a'], ['failed', 'skipped'])
        self.assertEqual(data['summary']['unstable'], 0)
        self.assertEqual(data['tests'][0]['failure_rate'], 1)

    def test_all_skipped_and_empty(self):
        data = self.history(['a'], ['skipped'])
        self.assertIsNone(data['tests'][0]['failure_rate'])
        self.assertEqual(data['tests'][0]['classification'], 'only skipped')
        self.assertEqual(analyze([])['summary']['runs'], 0)

    def test_wilson_known_values(self):
        lo, hi = wilson(5, 10)
        self.assertAlmostEqual(lo, .236593, places=5)
        self.assertAlmostEqual(hi, .763407, places=5)
        self.assertEqual(wilson(0, 0), (0, 1))
        for total in range(1, 50):
            for failed in range(total + 1):
                lo, hi = wilson(failed, total)
                self.assertTrue(0 <= lo <= failed/total <= hi <= 1)

    def test_signature_normalizes_variable_values(self):
        self.assertEqual(signature('Timeout 123 at 0xabc'), signature('Timeout 999 at 0xdef'))

    def test_demo_is_deterministic_and_revision_aware(self):
        data = demo_data()
        self.assertEqual(data, demo_data())
        self.assertEqual(data['summary']['unstable'], 3)
        migration = next(t for t in data['tests'] if t['name'] == 'migration_schema')
        self.assertEqual(migration['classification'], 'cross-revision variation')

    def test_html_untrusted_payload_and_roundtrip(self):
        data = analyze([])
        data['methodology'] = '</script><img src=x onerror=alert(1)> & café'
        html = html_report(data)
        self.assertNotIn(data['methodology'], html)
        payload = html.split('<script type="application/json" id="data">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload), data)
        self.assertNotIn('__FAULTLINE_DATA__', html)

    def test_markdown_escapes_cells(self):
        data = self.history(['a'], ['failed'])
        data['tests'][0]['name'] = 'x|y\n<script>'
        report = markdown_report(data)
        self.assertIn('x\\|y &lt;script&gt;', report)

    def test_cli_report_and_policy(self):
        self.history(['a', 'a'], ['passed', 'failed'])
        output = self.root / 'result.json'
        with contextlib.redirect_stdout(io.StringIO()):
            result = main(['report', '--db', str(self.db), '--format', 'json', '--output', str(output), '--fail-on-instability'])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.read_text())['summary']['unstable'], 1)

    def test_cli_error_and_demo(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['report', '--db', str(self.db)]), 2)
        output = self.root / 'demo.html'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['demo', '--output', str(output)]), 0)
        self.assertIn('Reliability queue', output.read_text())


if __name__ == '__main__':
    unittest.main()
