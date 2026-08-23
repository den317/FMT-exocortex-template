"""
Тесты residency-gate-skill-adapter.sh (WP-7 ResidencyGate-Event-Adapter, issue #323).

Раньше Point A (проверка согласия при активации функции) была когнитивной:
автор скилла должен был сам вставить `source residency-gate-init.sh` в свой
код — забытая строка означала отсутствие проверки вообще. Этот хук делает то
же самое механически, на событии PreToolUse:Skill, до того как код скилла
вообще запустится.

Прогоняют хук как subprocess с JSON-payload на stdin (тот же контракт, что и
у dry-run-gate.sh: tool_name/tool_input) и проверяют returncode:
  exit 0 = разрешено (нет data_needs, нет манифеста, или согласие уже дано)
  exit 2 = заблокировано (Claude Code convention для PreToolUse-блока)

Состояние согласия (data-residency.yaml) читается из `~/IWE/current/` —
изолируется через $HOME на временный каталог, чтобы тест не трогал реальное
согласие пилота.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / ".claude" / "hooks" / "residency-gate-skill-adapter.sh"
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"


def _env_with_home(fake_home: Path) -> dict:
    """A real hook invocation inherits the caller's full environment (PATH,
    PYTHONPATH, etc.) -- only HOME changes here, to redirect
    ResidencyState's default state file (~/IWE/current/data-residency.yaml)
    away from the pilot's real consent record."""
    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    return env


def _run_hook(skill_name: str, fake_home: Path) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": "Skill", "tool_input": {"skill": skill_name}})
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
        env=_env_with_home(fake_home),
    )


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    (home / "IWE" / "current").mkdir(parents=True)
    return home


@pytest.fixture
def temp_skill(request):
    """Creates a real (throwaway) skill dir under .claude/skills for the test's
    duration -- the adapter resolves manifests by real path, so a fixture-only
    in-memory manifest cannot exercise it."""
    skill_name = f"pytest-residency-{request.node.name}".replace("[", "-").replace("]", "")
    skill_dir = SKILLS_DIR / skill_name
    yield skill_name, skill_dir
    if skill_dir.exists():
        for f in skill_dir.iterdir():
            f.unlink()
        skill_dir.rmdir()


def test_no_manifest_allows(fake_home, temp_skill):
    """Скилл без SKILL.md вообще (или без файла на диске) — хук не имеет
    мнения, пропускает не вызывая residency-gate.py."""
    skill_name, _ = temp_skill
    result = _run_hook(skill_name, fake_home)
    assert result.returncode == 0, result.stderr


def test_no_data_needs_allows(fake_home, temp_skill):
    """Скилл с SKILL.md, но без блока data_needs — residency-gate.py сам
    возвращает allowed=true, хук пропускает."""
    skill_name, skill_dir = temp_skill
    skill_dir.mkdir(exist_ok=True)
    (skill_dir / "SKILL.md").write_text("---\nname: test\n---\n\nObычный скилл без данных.\n")
    result = _run_hook(skill_name, fake_home)
    assert result.returncode == 0, result.stderr


def test_declared_need_without_consent_blocks(fake_home, temp_skill):
    """Чистая установка (issue #323 acceptance): скилл объявляет data_needs,
    согласия ещё не было — хук блокирует ДО того как код скилла запустится."""
    skill_name, skill_dir = temp_skill
    skill_dir.mkdir(exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test\n---\n\n"
        "data_needs:\n"
        "  - type: 2.1, flow: inbound, name: digital-twin, schema_version: 1\n"
    )
    result = _run_hook(skill_name, fake_home)
    assert result.returncode == 2, result.stderr
    assert "BLOCKED" in result.stderr
    assert "digital-twin" in result.stderr


def test_granted_consent_allows(fake_home, temp_skill):
    """После явного grant тем же CLI, что использует пилот — хук пропускает."""
    skill_name, skill_dir = temp_skill
    skill_dir.mkdir(exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test\n---\n\n"
        "data_needs:\n"
        "  - type: 2.1, flow: inbound, name: digital-twin, schema_version: 1\n"
    )
    gate_py = REPO_ROOT / ".claude" / "skills" / "residency-gate" / "residency-gate.py"
    subprocess.run(
        ["python3", str(gate_py), "grant", skill_name, "2.1", "inbound", "digital-twin"],
        env=_env_with_home(fake_home),
        check=True,
        capture_output=True,
    )
    result = _run_hook(skill_name, fake_home)
    assert result.returncode == 0, result.stderr


def test_denied_consent_blocks(fake_home, temp_skill):
    """Явный отказ пилота — хук продолжает блокировать, не переспрашивает
    молча (Point A не является интерактивным)."""
    skill_name, skill_dir = temp_skill
    skill_dir.mkdir(exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test\n---\n\n"
        "data_needs:\n"
        "  - type: 2.2, flow: outbound, name: health-export, schema_version: 1\n"
    )
    gate_py = REPO_ROOT / ".claude" / "skills" / "residency-gate" / "residency-gate.py"
    subprocess.run(
        ["python3", str(gate_py), "deny", skill_name, "2.2", "outbound", "health-export",
         "тестовый отказ"],
        env=_env_with_home(fake_home),
        check=True,
        capture_output=True,
    )
    result = _run_hook(skill_name, fake_home)
    assert result.returncode == 2, result.stderr
    assert "health-export" in result.stderr


def test_non_skill_tool_call_ignored(fake_home):
    """Не Skill-вызов (нет .tool_input.skill) — хук выходит немедленно, ничего
    не резолвит и не падает."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
        env=_env_with_home(fake_home),
    )
    assert result.returncode == 0, result.stderr


def test_malformed_manifest_fails_closed(fake_home, temp_skill):
    """Битая декларация (нет schema_version) — residency-gate.py сам
    fail-closed (ManifestError); хук отражает это блокировкой, не тихим
    пропуском."""
    skill_name, skill_dir = temp_skill
    skill_dir.mkdir(exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test\n---\n\n"
        "data_needs:\n"
        "  - type: 2.1, flow: inbound, name: broken\n"  # no schema_version
    )
    result = _run_hook(skill_name, fake_home)
    assert result.returncode == 2, result.stderr
