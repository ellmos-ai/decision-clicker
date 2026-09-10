# SPDX-License-Identifier: MIT
"""Automated metadata contract tests for ellmos-ai/decision-clicker.

Validates PEP 621 compliance, OS classifiers, pytest configuration,
.gitignore hardening, CI workflow security, bilingual documentation parity,
Shields.io badges, Mermaid diagrams, Governance Invariants, and zero runtime dependencies.
"""
from __future__ import annotations

from pathlib import Path

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
        "Parent Organization",
        "Umbrella Ecosystem",
    ]
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
    """Verify English and German READMEs exist with 14-point quick navigation."""
    readme_en = ROOT / "README.md"
    readme_de = ROOT / "README_de.md"
    readme_de_alt = ROOT / "README.de.md"

    assert readme_en.is_file(), "README.md must exist"
    assert readme_de.is_file(), "README_de.md must exist"
    assert readme_de_alt.is_file(), "README.de.md must exist for legacy compatibility"

    text_en = readme_en.read_text(encoding="utf-8")
    text_de = readme_de.read_text(encoding="utf-8")

    # Verify 14 quick nav items
    for i in range(1, 15):
        assert f"{i}. [" in text_en, f"README.md missing quick navigation item {i}"
        assert f"{i}. [" in text_de, f"README_de.md missing quick navigation item {i}"


def test_readme_badges_suite():
    """Verify README.md contains complete Shields.io badge suite."""
    text_en = (ROOT / "README.md").read_text(encoding="utf-8")
    expected_badges = [
        "version-1.1.1-blue.svg",
        "CI-passing-brightgreen.svg",
        "tests-142%2B%20passed-brightgreen.svg",
        "privacy-100%25%20Local--First%20%7C%20Zero--Egress-success.svg",
        "security-RunAsInvoker%20%7C%20Non--Elevation-blue.svg",
        "security--SLA-48h%20Response%20%7C%205d%20Triage-informational.svg",
        "code%20style-Ruff-black.svg",
        "ecosystem-ellmos--ai-purple.svg",
        "umbrella-open--bricks-orange.svg",
        "LLM-llms.txt-blueviolet.svg",
        "last%20checked-2026--09--10-informational.svg",
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
    """Verify llms.txt is up to date with version 1.1.1 and recent timestamp."""
    llms_text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "2026-09-10" in llms_text
    assert "1.1.1" in llms_text
    assert "decision_clicker/api.py" in llms_text
    assert "decision_clicker/writer.py" in llms_text


def test_changelog_release_entry():
    """Verify CHANGELOG.md documents version 1.1.1 under 2026-09-10 and preserves 1.1.0."""
    changelog_text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
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
    """Verify CHANGELOG.md contains the latest Pfad A release entry."""
    changelog_path = ROOT / "CHANGELOG.md"
    content = changelog_path.read_text(encoding="utf-8")
    assert "## [1.1.1] - 2026-09-10" in content
    assert "Technical Hygiene" in content
