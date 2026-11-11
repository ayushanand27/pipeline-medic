import json

import pytest

from medic.triage import (
    EPSS_URL,
    KEV_URL,
    enrich,
    from_bandit,
    from_leakkill,
    from_trivy,
    main,
    merge,
    safe_path,
    summarize,
)


def trivy_report(target: str, *vulns: dict) -> dict:
    return {"Results": [{"Target": target, "Vulnerabilities": list(vulns)}]}


def vuln(cve: str, severity: str, fixed: str = "", package: str = "openssl") -> dict:
    return {
        "VulnerabilityID": cve,
        "PkgName": package,
        "InstalledVersion": "1.0",
        "FixedVersion": fixed,
        "Severity": severity,
        "Title": f"{cve} in {package}",
    }


def test_same_cve_from_two_scans_is_counted_once():
    image = from_trivy(trivy_report("demo-app:abc (debian)", vuln("CVE-1", "HIGH", "1.1")))
    files = from_trivy(trivy_report("requirements.txt", vuln("CVE-1", "HIGH", "1.1")))
    merged = merge(image + files)
    assert len(merged) == 1
    assert merged[0].seen_in == ["demo-app:abc (debian)", "requirements.txt"]


def test_same_cve_in_two_packages_stays_two_findings():
    report = trivy_report("image", vuln("CVE-1", "HIGH", package="openssl"), vuln("CVE-1", "HIGH", package="libssl"))
    assert len(merge(from_trivy(report))) == 2


def test_order_is_severity_first_then_fixable_first():
    report = trivy_report(
        "image",
        vuln("CVE-LOW", "LOW", "2.0"),
        vuln("CVE-CRIT-NOFIX", "CRITICAL"),
        vuln("CVE-HIGH", "HIGH", "2.0"),
        vuln("CVE-CRIT-FIX", "CRITICAL", "2.0"),
    )
    order = [finding.id for finding in merge(from_trivy(report))]
    assert order == ["CVE-CRIT-FIX", "CVE-CRIT-NOFIX", "CVE-HIGH", "CVE-LOW"]


def test_secret_is_always_critical():
    report = [{"type": "AWS access key", "value": "AKIA****", "locations": ["config.py:2", "old.py:9"]}]
    findings = from_leakkill(report)
    assert [f.severity for f in findings] == ["CRITICAL", "CRITICAL"]
    assert summarize(2, merge(findings))["secrets"] == 2


def test_bandit_findings_are_read():
    report = {"results": [{"test_id": "B602", "issue_severity": "HIGH", "issue_text": "shell=True", "filename": "a.py", "line_number": 3}]}
    finding = from_bandit(report)[0]
    assert (finding.id, finding.severity, finding.target) == ("B602", "HIGH", "a.py:3")


def test_summary_counts_only_fixable_criticals_for_the_gate():
    report = trivy_report("image", vuln("CVE-A", "CRITICAL", "2.0"), vuln("CVE-B", "CRITICAL"), vuln("CVE-C", "weird"))
    summary = summarize(3, merge(from_trivy(report)))
    assert summary["critical_fixable"] == 1
    assert summary["counts"]["CRITICAL"] == 2 and summary["counts"]["UNKNOWN"] == 1


def test_empty_reports_do_not_crash():
    assert from_trivy({}) == [] and from_trivy({"Results": [{"Target": "x"}]}) == []
    assert from_bandit({}) == [] and from_leakkill([]) == []
    assert summarize(0, [])["unique_findings"] == 0


def test_command_line_writes_summary_and_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.json").write_text(json.dumps(trivy_report("image", vuln("CVE-1", "HIGH", "2.0"))))
    (tmp_path / "b.json").write_text(json.dumps(trivy_report("fs", vuln("CVE-1", "HIGH", "2.0"))))
    (tmp_path / "secrets.json").write_text("[]")
    out, report = tmp_path / "security.json", tmp_path / "security.md"
    main(["--trivy", str(tmp_path / "a.json"), "--trivy", str(tmp_path / "b.json"),
          "--leakkill", str(tmp_path / "secrets.json"), "--out", str(out), "--report", str(report)])
    summary = json.loads(out.read_text())
    assert summary["raw_findings"] == 2 and summary["duplicates_removed"] == 1
    assert "CVE-1" in report.read_text()


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def fake_get(url, **kwargs):
    if url == KEV_URL:
        return FakeResponse({"vulnerabilities": [{"cveID": "CVE-MEDIUM-EXPLOITED"}]})
    assert url == EPSS_URL
    return FakeResponse({"data": [{"cve": "CVE-HIGH-LIKELY", "epss": "0.91"}, {"cve": "CVE-HIGH-UNLIKELY", "epss": "0.01"}]})


def test_exploit_data_changes_the_order():
    report = trivy_report(
        "image",
        vuln("CVE-HIGH-UNLIKELY", "HIGH", "2.0"),
        vuln("CVE-CRITICAL", "CRITICAL", "2.0"),
        vuln("CVE-MEDIUM-EXPLOITED", "MEDIUM", "2.0"),
        vuln("CVE-HIGH-LIKELY", "HIGH", "2.0"),
    )
    findings = from_trivy(report)
    assert enrich(findings, get=fake_get) == []
    order = [finding.id for finding in merge(findings)]
    # A medium that is being exploited right now beats a critical that is not.
    assert order == ["CVE-MEDIUM-EXPLOITED", "CVE-CRITICAL", "CVE-HIGH-LIKELY", "CVE-HIGH-UNLIKELY"]
    assert summarize(4, merge(findings))["known_exploited_fixable"] == 1


def test_exploit_sources_being_down_is_not_fatal():
    def broken_get(url, **kwargs):
        raise ConnectionError("offline")

    findings = from_trivy(trivy_report("image", vuln("CVE-1", "HIGH", "2.0")))
    problems = enrich(findings, get=broken_get)
    assert len(problems) == 2
    assert findings[0].known_exploited is False and findings[0].epss is None
    assert [f.id for f in merge(findings)] == ["CVE-1"]


@pytest.mark.parametrize("path", ["../outside.json", "/etc/passwd", "reports/../../outside.json"])
def test_paths_outside_the_working_directory_are_refused(tmp_path, monkeypatch, path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        safe_path(path)


def test_paths_inside_the_working_directory_are_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert safe_path("reports/security.json") == tmp_path.resolve() / "reports" / "security.json"


def test_command_line_refuses_to_write_outside(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["--out", "../security.json"])
