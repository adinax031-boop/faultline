"""Self-contained outputs; untrusted test names never become executable HTML."""
import json
from importlib.resources import files


def html_report(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return files("faultline").joinpath("dashboard.html").read_text(encoding="utf-8").replace("__FAULTLINE_DATA__", payload)


def markdown_report(data: dict) -> str:
    def escape(value):
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ").replace("<", "&lt;").replace(">", "&gt;").replace("`", "&#96;")
    s = data["summary"]
    lines = ["# Faultline reliability report", "", f"{s['tests']} test/environment groups · {s['runs']} runs · {s['unstable']} unstable groups", "", "| Test | Environment | Finding | Failures | 95% interval |", "|---|---|---|---:|---|"]
    for t in data["tests"]:
        lo, hi = t["interval"]
        lines.append(f"| {escape(t['classname'] + '::' + t['name'])} | {escape(t['environment'])} | {t['classification']} | {t['failures']}/{t['executed']} | {lo:.1%}–{hi:.1%} |")
    return "\n".join(lines + ["", data["methodology"], ""])
