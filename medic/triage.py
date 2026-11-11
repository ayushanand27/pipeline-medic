"""Security triage: merge the reports of several scanners into one ranked list.

Scanners:
  - Trivy    : known vulnerabilities (CVEs) in the container image and in dependencies
  - Bandit   : risky patterns in our own Python code (SAST)
  - LeakKill : secrets committed to the repo

The same CVE is often reported twice (once for the image, once for the dependency file).
This module removes the duplicates and puts the most urgent findings first.

With --enrich it also asks two public sources how likely each CVE is to be attacked:
  - CISA KEV : the list of vulnerabilities that are being exploited right now
  - EPSS     : a score from 0 to 1 for the chance of exploitation in the next 30 days

Usage:
    python -m medic.triage --trivy image.json --trivy fs.json --bandit bandit.json \\
        --leakkill secrets.json --out security.json --report security.md
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
EPSS_URL = "https://api.first.org/data/v1/epss"


@dataclass
class Finding:
    scanner: str
    kind: str  # "vulnerability", "code" or "secret"
    id: str  # CVE id, Bandit test id, or secret type
    severity: str
    title: str
    target: str  # package name, or file:line
    fix: str = ""  # fixed version, when one exists
    seen_in: list[str] = field(default_factory=list)
    known_exploited: bool = False  # on the CISA KEV list
    epss: float | None = None  # chance of exploitation, 0 to 1

    @property
    def key(self) -> tuple:
        return (self.kind, self.id, self.target)


def _severity(value: str | None) -> str:
    value = (value or "").upper()
    return value if value in SEVERITIES else "UNKNOWN"


def from_trivy(report: dict) -> list[Finding]:
    findings = []
    for result in report.get("Results") or []:
        for vuln in result.get("Vulnerabilities") or []:
            findings.append(
                Finding(
                    scanner="trivy",
                    kind="vulnerability",
                    id=vuln.get("VulnerabilityID", "?"),
                    severity=_severity(vuln.get("Severity")),
                    title=vuln.get("Title") or vuln.get("VulnerabilityID", ""),
                    target=f"{vuln.get('PkgName', '?')} {vuln.get('InstalledVersion', '')}".strip(),
                    fix=vuln.get("FixedVersion") or "",
                    seen_in=[result.get("Target", "?")],
                )
            )
    return findings


def from_bandit(report: dict) -> list[Finding]:
    return [
        Finding(
            scanner="bandit",
            kind="code",
            id=item.get("test_id", "?"),
            severity=_severity(item.get("issue_severity")),
            title=item.get("issue_text", ""),
            target=f"{item.get('filename', '?')}:{item.get('line_number', '?')}",
        )
        for item in report.get("results") or []
    ]


def from_leakkill(report: list) -> list[Finding]:
    findings = []
    for item in report or []:
        for location in item.get("locations") or ["?"]:
            findings.append(
                Finding(
                    scanner="leakkill",
                    kind="secret",
                    id=item.get("type", "secret"),
                    severity="CRITICAL",  # a committed secret is always urgent
                    title=f"{item.get('type', 'Secret')} committed to the repo",
                    target=location,
                    fix="remove it from the code and revoke it",
                )
            )
    return findings


def fetch_kev(get=requests.get) -> set[str]:
    data = get(KEV_URL, timeout=20).json()
    return {item["cveID"] for item in data.get("vulnerabilities", [])}


def fetch_epss(cves: list[str], get=requests.get) -> dict[str, float]:
    scores: dict[str, float] = {}
    for start in range(0, len(cves), 50):  # the API takes a comma-separated list
        batch = ",".join(cves[start : start + 50])
        data = get(EPSS_URL, params={"cve": batch}, timeout=20).json()
        for row in data.get("data", []):
            scores[row["cve"]] = float(row["epss"])
    return scores


def enrich(findings: list[Finding], get=requests.get) -> list[str]:
    """Add exploit data to the CVE findings. A source that is down is skipped, never fatal."""
    cves = sorted({f.id for f in findings if f.id.startswith("CVE-")})
    problems: list[str] = []
    if not cves:
        return problems
    try:
        exploited = fetch_kev(get)
        for finding in findings:
            finding.known_exploited = finding.id in exploited
    except Exception as error:  # network, JSON, anything: the pipeline must still run
        problems.append(f"KEV list not available: {error}")
    try:
        scores = fetch_epss(cves, get)
        for finding in findings:
            finding.epss = scores.get(finding.id)
    except Exception as error:
        problems.append(f"EPSS scores not available: {error}")
    return problems


def merge(findings: list[Finding]) -> list[Finding]:
    """Remove duplicates, then sort. Order of importance:
    1. being exploited right now (KEV)   2. severity
    3. chance of exploitation (EPSS)     4. fixable before not fixable"""
    unique: dict[tuple, Finding] = {}
    for finding in findings:
        if finding.key in unique:
            kept = unique[finding.key]
            kept.seen_in = sorted(set(kept.seen_in + finding.seen_in))
            kept.fix = kept.fix or finding.fix
        else:
            unique[finding.key] = finding
    return sorted(
        unique.values(),
        key=lambda f: (
            0 if f.known_exploited else 1,
            SEVERITIES.index(f.severity),
            -(f.epss or 0.0),
            0 if f.fix else 1,
            f.id,
            f.target,
        ),
    )


def summarize(raw_count: int, findings: list[Finding]) -> dict:
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        counts[finding.severity] += 1
    return {
        "raw_findings": raw_count,
        "unique_findings": len(findings),
        "duplicates_removed": raw_count - len(findings),
        "counts": counts,
        "secrets": sum(1 for f in findings if f.kind == "secret"),
        "known_exploited_fixable": sum(1 for f in findings if f.known_exploited and f.fix),
        "critical_fixable": sum(
            1 for f in findings if f.kind == "vulnerability" and f.severity == "CRITICAL" and f.fix
        ),
        "findings": [asdict(f) for f in findings],
    }


def render_markdown(summary: dict, limit: int = 15) -> str:
    counts = summary["counts"]
    lines = [
        "## Security triage",
        "",
        f"{summary['raw_findings']} raw findings, {summary['duplicates_removed']} duplicates removed, "
        f"**{summary['unique_findings']} unique**.",
        "",
        "| Critical | High | Medium | Low | Secrets | Exploited now |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {counts['CRITICAL']} | {counts['HIGH']} | {counts['MEDIUM']} | {counts['LOW']} "
        f"| {summary['secrets']} | {sum(1 for f in summary['findings'] if f['known_exploited'])} |",
    ]
    if summary["findings"]:
        lines += ["", f"Top {min(limit, len(summary['findings']))} by priority:", ""]
        lines += ["| Severity | Id | Where | Fix | Exploit chance | Scanner |", "| --- | --- | --- | --- | --- | --- |"]
        for item in summary["findings"][:limit]:
            if item["known_exploited"]:
                chance = "exploited now"
            elif item["epss"] is not None:
                chance = f"{item['epss'] * 100:.1f}%"
            else:
                chance = "-"
            lines.append(
                f"| {item['severity']} | {item['id']} | {item['target']} | {item['fix'] or 'none yet'} "
                f"| {chance} | {item['scanner']} |"
            )
    return "\n".join(lines) + "\n"


def _load(path: str):
    text = Path(path).read_text(encoding="utf-8").strip()
    return json.loads(text) if text else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="medic.triage", description="Merge and rank scanner reports.")
    parser.add_argument("--trivy", action="append", default=[], help="Trivy JSON report (can repeat)")
    parser.add_argument("--bandit", help="Bandit JSON report")
    parser.add_argument("--leakkill", help="LeakKill JSON report")
    parser.add_argument("--enrich", action="store_true", help="add CISA KEV and EPSS exploit data")
    parser.add_argument("--out", required=True, help="where to write the JSON summary")
    parser.add_argument("--report", help="where to write the Markdown report")
    args = parser.parse_args(argv)

    raw: list[Finding] = []
    for path in args.trivy:
        raw += from_trivy(_load(path))
    if args.bandit:
        raw += from_bandit(_load(args.bandit))
    if args.leakkill:
        raw += from_leakkill(_load(args.leakkill) or [])

    if args.enrich:
        for problem in enrich(raw):
            print(f"medic.triage: {problem}", file=sys.stderr)

    summary = summarize(len(raw), merge(raw))
    Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = render_markdown(summary)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
