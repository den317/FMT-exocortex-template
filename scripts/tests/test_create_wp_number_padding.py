"""
Регрессионный тест канонического WP-ID без дополнения нулями.

Контракт `/wp-new` и WP-434 требуют `inbox/WP-{N}/WP-{N}.md`; архивный
контекст создаётся только при закрытии РП.

Тест гоняет РЕАЛЬНЫЙ create-wp.sh end-to-end на минимальном scaffold'е
governance-репо во временной директории — не копию логики.
"""

import subprocess
import sys
from pathlib import Path

CREATE_WP = Path(__file__).parent.parent / "create-wp.sh"

REGISTRY_HEADER = (
    "| # | P | Название | Ст | Репо | Бюджет |\n"
    "|---|---|---|---|---|---|\n"
    "| 8 | P3 | **Существующий РП** | done | — | 5h |\n"
)


def _scaffold_governance_repo(root: Path) -> Path:
    """Минимальный governance-репо: REGISTRY с последним номером 8 (< 100 — кейс для паддинга)."""
    strategy = root / "DS-strategy"
    (strategy / "docs").mkdir(parents=True)
    (strategy / "inbox").mkdir(parents=True)
    (strategy / "archive" / "wp-contexts").mkdir(parents=True)
    (strategy / "docs" / "WP-REGISTRY.md").write_text(REGISTRY_HEADER, encoding="utf-8")
    return strategy


def _run_create_wp(iwe_root: Path, **extra_args):
    args = ["--title", "Тестовый РП", "--budget", "3h", "--priority", "P2", "--no-consent-check"]
    for k, v in extra_args.items():
        args += [f"--{k}", v]
    env = {"IWE_ROOT": str(iwe_root), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    return subprocess.run(
        ["bash", str(CREATE_WP), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_next_wp_number_uses_canonical_paths_and_headers(tmp_path):
    strategy = _scaffold_governance_repo(tmp_path)

    result = _run_create_wp(tmp_path)

    assert result.returncode == 0, result.stderr

    wp_dir = strategy / "inbox" / "WP-9"
    wp_file = wp_dir / "WP-9.md"
    assert wp_dir.is_dir(), f"ожидалась папка WP-9. stdout:\n{result.stdout}"
    assert wp_file.is_file()

    content = wp_file.read_text(encoding="utf-8")
    assert "# WP-9: Тестовый РП" in content
    assert "wp: 9" in content, "frontmatter wp: остаётся чистым числом, без паддинга"

    assert not list((strategy / "archive" / "wp-contexts").glob("WP-9*"))


def test_registry_number_column_stays_bare(tmp_path):
    strategy = _scaffold_governance_repo(tmp_path)

    result = _run_create_wp(tmp_path)

    assert result.returncode == 0, result.stderr
    registry = (strategy / "docs" / "WP-REGISTRY.md").read_text(encoding="utf-8")
    # колонка "#" — чистое число (та же конвенция, что frontmatter), НЕ "009"
    assert "| 9 |" in registry
    assert "| 009 |" not in registry
    assert "DS-strategy/inbox/WP-9/" in registry


def test_consent_file_path_stays_bare_number(tmp_path):
    """Consent-файл — внутренний хендшейк (touch .../wp-consent-{N}), не публичный путь: не паддится."""
    strategy = _scaffold_governance_repo(tmp_path)
    state_dir = tmp_path / ".claude" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "wp-consent-9").touch()

    args = ["--title", "РП с согласием", "--budget", "2h", "--priority", "P3"]
    env = {"IWE_ROOT": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    result = subprocess.run(
        ["bash", str(CREATE_WP), *args], capture_output=True, text=True, env=env
    )

    assert result.returncode == 0, result.stderr
    assert (strategy / "inbox" / "WP-9").is_dir()
