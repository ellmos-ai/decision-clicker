# SPDX-License-Identifier: MIT
"""Automated metadata contract tests for ellmos-ai/decision-clicker.

Validates PEP 621 compliance, OS classifiers, pytest configuration,
.gitignore hardening, CI workflow security, bilingual documentation parity,
Shields.io badges, Mermaid diagrams, Governance Invariants, and zero runtime dependencies.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from decision_clicker import __version__

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def _read_toml(rel_path: str = "pyproject.toml") -> dict:
    with (ROOT / rel_path).open("rb") as f:
        return tomllib.load(f)


def test_pep621_project_urls():
    """Verify pyproject.toml contains complete PEP 621 project URLs."""
    pyproject = _read_toml()
    urls = pyproject.get("project", {}).get("urls", {})
    required_keys = [
        "Homepage",
        "Repository",
        "Documentation",
        "Changelog",
        "Security",
        "Issues",
        "Third-Party Licenses",
        "Code of Conduct",
        "Agent Skill",
        "LLM Ready",
        "Parent Organization",
        "Umbrella Ecosystem",
    ]
    assert "Marketing Log" not in urls, "MARKETING-LOG.txt must not be published in project URLs"
    for key in required_keys:
        assert key in urls, f"Missing project URL key: {key}"
        assert urls[key].startswith("https://github.com/"), f"URL for {key} must start with https://github.com/"


def test_pep621_os_classifiers():
    """Verify pyproject.toml contains OS-specific classifiers."""
    pyproject = _read_toml()
    classifiers = pyproject.get("project", {}).get("classifiers", [])
    expected = [
        "Operating System :: OS Independent",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
    ]
    for cls in expected:
        assert cls in classifiers, f"Missing classifier: {cls}"


def test_pytest_ini_options():
    """Verify tool.pytest.ini_options contains required paths and addopts."""
    pyproject = _read_toml()
    pytest_opts = pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert "src" in pytest_opts.get("pythonpath", [])
    assert "tests" in pytest_opts.get("testpaths", [])
    assert "-ra -v" in pytest_opts.get("addopts", "")


def test_gitignore_hardening():
    """Verify .gitignore includes multi-host sync conflicts, locks, and caches."""
    gitignore_path = ROOT / ".gitignore"
    assert gitignore_path.is_file(), ".gitignore must exist"
    content = gitignore_path.read_text(encoding="utf-8")

    required_patterns = [
        "*-conflict-*",
        "*.sync-conflict-*",
        "*.sync-temp-*",
        "LOCK",
        "LOCK.*",
        "*.lock",
        "LOCK*.txt",
        "LOCK.permissions.json",
        "wheelhouse/",
        ".wheel-smoke/",
    ]
    for pat in required_patterns:
        assert pat in content, f"Missing .gitignore pattern: {pat}"


def test_ci_workflow_hardening():
    """Verify GitHub Actions CI workflow contains concurrency, bytecode gate, and multi-OS matrix."""
    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), ".github/workflows/ci.yml must exist"
    ci_text = ci_path.read_text(encoding="utf-8")

    assert "cancel-in-progress: true" in ci_text, "CI must enable cancel-in-progress concurrency"
    assert "python -m compileall -q src tests" in ci_text, "CI must include bytecode compilation gate"
    assert "ubuntu-latest" in ci_text and "windows-latest" in ci_text and "macos-latest" in ci_text


def test_security_policy_slas_and_contacts():
    """Verify SECURITY.md contains supported versions table, 48h SLA, and contacts."""
    sec_path = ROOT / "SECURITY.md"
    assert sec_path.is_file(), "SECURITY.md must exist"
    sec_text = sec_path.read_text(encoding="utf-8")

    assert "48h" in sec_text, "SECURITY.md must specify 48h acknowledgment SLA"
    assert "5" in sec_text and ("Triage" in sec_text or "triage" in sec_text)
    assert "security@open-bricks.org" in sec_text
    assert "security@ellmos.ai" in sec_text
    assert "1.1.x" in sec_text, "Supported versions table must include 1.1.x"


def test_bilingual_readme_parity():
    """Verify English and German READMEs exist with 15-point quick navigation."""
    readme_en = ROOT / "README.md"
    readme_de = ROOT / "README_de.md"
    readme_de_alt = ROOT / "README.de.md"

    assert readme_en.is_file(), "README.md must exist"
    assert readme_de.is_file(), "README_de.md must exist"
    assert readme_de_alt.is_file(), "README.de.md must exist for legacy compatibility"

    text_en = readme_en.read_text(encoding="utf-8")
    text_de = readme_de.read_text(encoding="utf-8")
    text_de_alt = readme_de_alt.read_text(encoding="utf-8")

    # Verify 15 quick nav items
    for i in range(1, 16):
        assert f"{i}. [" in text_en, f"README.md missing quick navigation item {i}"
        assert f"{i}. [" in text_de, f"README_de.md missing quick navigation item {i}"

    assert text_de == text_de_alt, "README.de.md must be byte-for-byte identical with README_de.md"


def test_readme_badges_suite():
    """Verify README.md contains complete Shields.io badge suite."""
    text_en = (ROOT / "README.md").read_text(encoding="utf-8")
    expected_badges = [
        "version-1.1.2-blue.svg",
        "CI-passing-brightgreen.svg",
        "tests-405%20passed%20%7C%20100%25-brightgreen.svg",
        "privacy-100%25%20Local--First%20%7C%20Zero--Egress-success.svg",
        "security-RunAsInvoker%20%7C%20Non--Elevation-blue.svg",
        "security--SLA-48h%20Response%20%7C%205d%20Triage%20%7C%2030d%20Fix-informational.svg",
        "third--party-audited%20%7C%20zero%20dependencies-green.svg",
        "skill-SKILL.md-teal.svg",
        "code%20style-Ruff-black.svg",
        "ecosystem-ellmos--ai-purple.svg",
        "umbrella-open--bricks-orange.svg",
        "LLM-llms.txt-blueviolet.svg",
        "last%20checked-2026--11--15-informational.svg",
        "license-MIT-green.svg",
    ]
    for badge in expected_badges:
        assert badge in text_en, f"Missing badge in README.md: {badge}"


def test_mermaid_diagram_syntax():
    """Verify both Mermaid diagrams exist with required tokens in README."""
    text_en = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "```mermaid\nflowchart TD" in text_en, "Missing flowchart TD diagram"
    assert "```mermaid\nsequenceDiagram\n    autonumber" in text_en, "Missing autonumbered sequenceDiagram"


def test_governance_invariants_presence():
    """Verify all 10 Governance and Runtime Invariants are documented in README and llms.txt."""
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    llms_text = (ROOT / "llms.txt").read_text(encoding="utf-8")

    invariants = [
        "INV-LOCAL-01",
        "INV-CANON-02",
        "INV-NOELEV-03",
        "INV-ONEDOC-04",
        "INV-BACKUP-05",
        "INV-NOWRITE-06",
        "INV-UNDO-07",
        "INV-LOCK-08",
        "INV-CROSS-09",
        "INV-SLA-10",
    ]
    for inv_code in invariants:
        assert inv_code in readme_text, f"Missing {inv_code} in README.md"
        assert inv_code in llms_text, f"Missing {inv_code} in llms.txt"


def test_sibling_ecosystem_matrix():
    """Verify 16 sibling repositories are documented in the partner matrix."""
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    siblings = [
        "policy-registry",
        "system-auditor",
        "assistant-core",
        "store-packager",
        "clip-storyboard-director",
        "sqlite-transit-sync",
        "clutch",
        "ellmos-installer",
        "app-rotator",
        "workflowhooker",
        "ExplorerPro",
        "CleanMarkdown",
        "KlangpultLight",
        "abc-hct",
        "functional-stability-theory",
        "umbrella",
    ]
    for s in siblings:
        assert f"[`{s}`]" in readme_text, f"Missing sibling in README partner matrix: {s}"


def test_llms_txt_freshness_and_parity():
    """Verify llms.txt is up to date with version 1.1.2 and recent timestamp."""
    llms_text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "2026-11-15" in llms_text
    assert "1.1.2" in llms_text
    assert "decision_clicker/api.py" in llms_text
    assert "decision_clicker/writer.py" in llms_text


def test_changelog_release_entry():
    """Verify CHANGELOG.md documents version 1.1.2 under 2026-09-12 and preserves 1.1.1 and 1.1.0."""
    changelog_text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.1.2] - 2026-09-12" in changelog_text
    assert "## [1.1.1] - 2026-09-10" in changelog_text
    assert "## [1.1.0] - 2026-09-09" in changelog_text


def test_zero_external_runtime_dependencies():
    """Verify decision-clicker has zero external runtime dependencies."""
    pyproject = _read_toml()
    deps = pyproject.get("project", {}).get("dependencies", [])
    assert deps == [], "decision-clicker must have zero external runtime dependencies"
    assert (ROOT / "THIRD_PARTY_LICENSES.md").is_file(), "THIRD_PARTY_LICENSES.md must exist"


def test_gitignore_hygiene_patterns():
    """Verify .gitignore contains comprehensive multi-host conflict, lock, and cache patterns."""
    gitignore_path = ROOT / ".gitignore"
    content = gitignore_path.read_text(encoding="utf-8")
    required_patterns = [
        "*-conflict-*",
        "*.sync-conflict-*",
        "*-ASUS-GEI.*",
        "*-WORKSTATION-LG.*",
        "*-WORKSTATION.*",
        "* (kopie)*",
        "* (copy)*",
        "LOCK",
        "LOCK.*",
        "*.lock",
        "LOCK*.txt",
        "LOCK.permissions.json",
        "uv.lock",
        ".coverage.*",
        "wheelhouse/",
        ".wheel-smoke/",
    ]
    for pattern in required_patterns:
        assert pattern in content, f"Missing gitignore pattern: {pattern}"


def test_pytest_configuration_and_flags():
    """Verify pytest configuration in pyproject.toml has standardized -ra -v options."""
    pyproject = _read_toml()
    addopts = pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("addopts", "")
    assert "-ra" in addopts
    assert "-v" in addopts


def test_ci_workflow_pytest_flags():
    """Verify CI workflow executes pytest with standardized -ra -v flags."""
    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    content = ci_path.read_text(encoding="utf-8")
    assert "pytest -ra -v" in content


def test_changelog_recent_pfad_a_entry():
    """Verify CHANGELOG.md contains the Pfad A release entry."""
    changelog_path = ROOT / "CHANGELOG.md"
    content = changelog_path.read_text(encoding="utf-8")
    assert "## [1.1.1] - 2026-09-10" in content
    assert "Technical Hygiene" in content


def test_changelog_recent_pfad_b_entry():
    """Verify CHANGELOG.md contains the latest Pfad B release entry."""
    changelog_path = ROOT / "CHANGELOG.md"
    content = changelog_path.read_text(encoding="utf-8")
    assert "## [1.1.2] - 2026-09-12" in content
    assert "Discoverability & Design" in content


def test_third_party_licenses_audit_and_invariants():
    """Verify THIRD_PARTY_LICENSES.md contains formal audit stamp and invariant verifications."""
    tpl_path = ROOT / "THIRD_PARTY_LICENSES.md"
    assert tpl_path.is_file(), "THIRD_PARTY_LICENSES.md must exist"
    content = tpl_path.read_text(encoding="utf-8")
    assert "Stand: 2026-09-16 / As of: 2026-09-16" in content
    assert "PEP 639" in content
    assert "INV-LOCAL-01" in content
    assert "INV-NOELEV-03" in content
    assert "INV-LOCK-08" in content


def test_marketing_log_untracked_and_ignored():
    """Verify MARKETING-LOG.txt is excluded from git tracking, manifests, and public docs."""
    gitignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    manifest_text = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "*MARKETING-LOG.txt" in gitignore_text
    assert "MARKETING-LOG.txt" not in manifest_text
    assert "MARKETING-LOG.txt" not in readme_text


def test_policy_p022_agentic_readiness():
    """Verify Policy P-022 deliverables: SKILL.md, llm.txt, llms.txt 4-point guide, and README LLM prompt."""
    skill_path = ROOT / "SKILL.md"
    llm_pointer_path = ROOT / "llm.txt"
    llms_path = ROOT / "llms.txt"
    assert skill_path.is_file()
    assert llm_pointer_path.is_file()
    assert llms_path.is_file()

    skill_text = skill_path.read_text(encoding="utf-8")
    assert "name: decision-clicker" in skill_text
    assert "ProposalSubmitter" in skill_text

    llms_text = llms_path.read_text(encoding="utf-8")
    for marker in ("Requirements", "Installation Command", "Verification Command", "Minimal Usage Example"):
        assert marker in llms_text

    readme_en = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_de = (ROOT / "README_de.md").read_text(encoding="utf-8")
    assert "### Install with your LLM" in readme_en
    assert "### Mit deinem LLM installieren" in readme_de
    assert "```text" in readme_en and "```text" in readme_de


def test_community_health_and_ui_screenshots():
    """Verify bilingual Code of Conduct, issue templates, and rendered UI screenshots."""
    coc_path = ROOT / "CODE_OF_CONDUCT.md"
    assert coc_path.is_file()
    coc_text = coc_path.read_text(encoding="utf-8")
    assert "Contributor Covenant" in coc_text
    assert "Verhaltenskodex" in coc_text

    for rel in (
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/ISSUE_TEMPLATE/config.yml",
    ):
        assert (ROOT / rel).is_file(), f"Missing community template: {rel}"

    readme_en = (ROOT / "README.md").read_text(encoding="utf-8")
    for shot in ("dashboard_overview.png", "klick_decision_view.png", "new_proposal_view.png"):
        shot_path = ROOT / "README" / "screenshots" / shot
        assert shot_path.is_file() and shot_path.stat().st_size > 1000
        assert f"README/screenshots/{shot}" in readme_en


def test_module_manifest_version_parity():
    """Verify ellmos-module.v2.json exists and matches package __version__."""
    manifest_path = ROOT / "ellmos-module.v2.json"
    assert manifest_path.is_file(), "ellmos-module.v2.json must exist"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data.get("version") == __version__
    assert data.get("version") == "1.1.2"


def test_pep639_license_files_metadata():
    """Verify pyproject.toml declares PEP 639 license-files and targets exist."""
    pyproject = _read_toml()
    project = pyproject.get("project", {})
    assert "license-files" in project, "pyproject.toml must declare PEP 639 license-files"
    license_files = project.get("license-files", [])
    assert "LICENSE" in license_files, "license-files must include LICENSE"
    assert "THIRD_PARTY_LICENSES.md" in license_files, "license-files must include THIRD_PARTY_LICENSES.md"
    for lf in license_files:
        p = ROOT / lf
        assert p.is_file(), f"Declared license file missing: {lf}"
        assert p.stat().st_size > 0, f"Declared license file empty: {lf}"


def test_gitignore_secret_and_credential_patterns():
    """Verify .gitignore contains comprehensive secret, cert, key, and multi-host rules."""
    gitignore_path = ROOT / ".gitignore"
    content = gitignore_path.read_text(encoding="utf-8")
    security_patterns = [
        "*.pem",
        "*.key",
        "*.crt",
        "*.cer",
        "*.pfx",
        "*.p12",
        "*.token",
        "*.secret",
        "*secret*.json",
        "credentials.json",
        ".npmrc",
        "id_rsa*",
        "id_ed25519*",
        "*.orig",
        "*.rej",
        "*-ASUS-GEI*",
        "*-WORKSTATION-LG*",
        "CONFLICT_REVIEW_LOG*",
    ]
    for pattern in security_patterns:
        assert pattern in content, f"Missing security pattern in .gitignore: {pattern}"


def test_ast_zero_hardcoded_secrets_and_personal_paths():
    """Verify zero hardcoded API keys, private keys, or personal paths in src/."""
    src_dir = ROOT / "src"
    patterns = [
        (re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"][^'\"]{10,}['\"]"), "API Key"),
        (re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"), "Private Key"),
        (re.compile(r"C:\\Users\\lukas", re.IGNORECASE), "Personal path"),
        (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "GitHub Token"),
    ]
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        ast.parse(text, filename=str(py_file))
        for regex, desc in patterns:
            match = regex.search(text)
            assert not match, f"Found {desc} in {py_file}: {match.group(0) if match else ''}"


def test_supply_chain_zero_external_runtime_imports():
    """Verify runtime source code only imports Python standard library and internal modules."""
    src_dir = ROOT / "src" / "decision_clicker"
    internal_modules = {"decision_clicker", "decisions_index", "decisions_db"}
    stdlib_top_levels = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else {
        "http", "urllib", "json", "pathlib", "subprocess", "argparse", "dataclasses",
        "re", "shutil", "typing", "os", "sys", "datetime", "uuid", "hashlib", "io"
    }

    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    assert (
                        root_pkg in stdlib_top_levels or root_pkg in internal_modules
                    ), f"Disallowed runtime import '{alias.name}' in {py_file}"
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                if node.module:
                    root_pkg = node.module.split(".")[0]
                    assert (
                        root_pkg in stdlib_top_levels or root_pkg in internal_modules
                    ), f"Disallowed runtime import from '{node.module}' in {py_file}"


def test_security_policy_remediation_sla():
    """Verify SECURITY.md defines 30-day remediation SLA in both English and German."""
    sec_path = ROOT / "SECURITY.md"
    content = sec_path.read_text(encoding="utf-8")
    assert "30-Day Remediation" in content
    assert "30 calendar days" in content
    assert "30 Tage Fix-Plan" in content or "30 Tage Behebung" in content
    assert "30 Kalendertagen" in content



def test_ci_timeout_minutes_guardrails():
    """Verify CI workflow defines a 15-minute execution timeout guardrail."""
    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), "ci.yml must exist"
    content = ci_path.read_text(encoding="utf-8")
    assert "timeout-minutes: 15" in content, "CI test matrix job must define timeout-minutes: 15"


def test_ci_stale_workflow_integrity():
    """Verify .github/workflows/stale.yml exists with required action, timeout and concurrency."""
    stale_path = ROOT / ".github" / "workflows" / "stale.yml"
    assert stale_path.is_file(), "stale.yml must exist"
    content = stale_path.read_text(encoding="utf-8")
    assert "actions/stale@v9" in content
    assert "timeout-minutes: 10" in content
    assert "cancel-in-progress: true" in content
    assert "issues: write" in content
    assert "pull-requests: write" in content


def test_ci_welcome_workflow_integrity():
    """Verify .github/workflows/welcome.yml exists with first-interaction action, timeout and concurrency."""
    welcome_path = ROOT / ".github" / "workflows" / "welcome.yml"
    assert welcome_path.is_file(), "welcome.yml must exist"
    content = welcome_path.read_text(encoding="utf-8")
    assert "actions/first-interaction@v3" in content
    assert "timeout-minutes: 5" in content
    assert "cancel-in-progress: true" in content
    assert "issues: write" in content
    assert "pull-requests: write" in content


def test_extended_gitignore_sync_and_lock_defense():
    """Verify .gitignore contains extended multi-host lock, cache and conflict defense rules."""
    gitignore_path = ROOT / ".gitignore"
    content = gitignore_path.read_text(encoding="utf-8")
    extra_patterns = [
        "* (Kopie)*",
        "* (Copy)*",
        "*conflicted copy*",
        "*-LAPTOP*",
        "*-Mac Studio*",
        "*-MacBook*",
        "LOCK.user.*",
        "LOCK.until.*",
        "LOCK.condition.*",
        "!package-lock.json",
        ".hypothesis/",
        ".turbo/",
        ".nyc_output/",
        ".tox/",
        ".mypy_cache/",
    ]
    for pattern in extra_patterns:
        assert pattern in content, f"Missing extended pattern in .gitignore: {pattern}"
