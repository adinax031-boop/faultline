# Contributing

Open an issue describing a concrete input, expected output and reproducible behavior. For JUnit dialect support, include a small anonymized fixture; do not submit production secrets or personal logs.

Use Python 3.10+. Install with `python -m pip install -e .`, run `python -m unittest discover -s tests -v`, then `python -m compileall -q src`. Make a focused branch and pull request with the problem, change and validation. Keep runtime dependencies at zero unless the benefit warrants changing that constraint.

Analysis changes need tests that challenge revision/environment boundaries, skips and retry selection bias. Parsing changes need malformed and unsafe input checks. Dashboard changes should preserve keyboard navigation, narrow layouts, offline operation and safe rendering of hostile test names.

Be respectful, explain disagreements with evidence, and give contributors room to revise. Maintainers may close abusive or unrelated discussions.
