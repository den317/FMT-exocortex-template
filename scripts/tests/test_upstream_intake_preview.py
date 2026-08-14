import json
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "upstream-intake-preview.py"


def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, text=True, capture_output=True)


def commit(repo: Path, message: str) -> str:
    run("git", "add", "tracked.txt", "update.sh", "update-manifest.json", cwd=repo)
    run("git", "commit", "-q", "-m", message, cwd=repo)
    return run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()


def init_repo(path: Path) -> None:
    path.mkdir()
    run("git", "init", "-q", cwd=path)
    run("git", "config", "user.name", "Test", cwd=path)
    run("git", "config", "user.email", "test@example.invalid", cwd=path)


def test_read_only_three_way_report_and_blockers(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    init_repo(upstream)
    (upstream / "tracked.txt").write_text("base\n", encoding="utf-8")
    (upstream / "update.sh").write_text("base\n", encoding="utf-8")
    (upstream / "update-manifest.json").write_text(
        json.dumps({"files": [{"path": "tracked.txt"}], "excluded_paths": ["update.sh"]}),
        encoding="utf-8",
    )
    base = commit(upstream, "base")
    (upstream / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (upstream / "update.sh").write_text("candidate\n", encoding="utf-8")
    target = commit(upstream, "candidate")

    den317 = tmp_path / "den317"
    run("git", "clone", "-q", str(upstream), str(den317))
    run("git", "config", "user.name", "Test", cwd=den317)
    run("git", "config", "user.email", "test@example.invalid", cwd=den317)
    run("git", "checkout", "-q", base, cwd=den317)
    (den317 / "tracked.txt").write_text("den317\n", encoding="utf-8")
    (den317 / "update.sh").write_text("base\n", encoding="utf-8")
    (den317 / "update-manifest.json").write_text(
        json.dumps(
            {
                "files": [{"path": "tracked.txt"}],
                "excluded_paths": ["update.sh"],
                "upstream_provenance": {"accepted_tag": base, "accepted_sha": base},
            }
        ),
        encoding="utf-8",
    )
    commit(den317, "den317")
    before = run("git", "rev-parse", "HEAD", cwd=den317).stdout.strip()

    result = run(
        "python3",
        str(SCRIPT),
        "--upstream",
        str(upstream),
        "--target",
        target,
        "--den317",
        str(den317),
        "--format",
        "json",
    )
    report = json.loads(result.stdout)

    assert report["mode"] == "read-only"
    assert report["verdict"] == "blocked"
    assert {item["path"] for item in report["blockers"]} == {"tracked.txt", "update.sh"}
    assert {item["classification"] for item in report["files"] if item["path"] == "tracked.txt"} == {"both-diverged"}
    assert {item["delivery_scope"] for item in report["files"] if item["path"] == "tracked.txt"} == {"delivered"}
    assert {item["delivery_scope"] for item in report["files"] if item["path"] == "update.sh"} == {"excluded"}
    assert run("git", "rev-parse", "HEAD", cwd=den317).stdout.strip() == before
    assert run("git", "status", "--porcelain", cwd=den317).stdout == ""


def test_dirty_den317_is_rejected(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    init_repo(upstream)
    (upstream / "tracked.txt").write_text("base\n", encoding="utf-8")
    (upstream / "update.sh").write_text("base\n", encoding="utf-8")
    (upstream / "update-manifest.json").write_text(
        json.dumps({"files": [{"path": "tracked.txt"}], "excluded_paths": ["update.sh"]}),
        encoding="utf-8",
    )
    base = commit(upstream, "base")
    den317 = tmp_path / "den317"
    run("git", "clone", "-q", str(upstream), str(den317))
    run("git", "config", "user.name", "Test", cwd=den317)
    run("git", "config", "user.email", "test@example.invalid", cwd=den317)
    (den317 / "update-manifest.json").write_text(
        json.dumps(
            {
                "files": [{"path": "tracked.txt"}],
                "excluded_paths": ["update.sh"],
                "upstream_provenance": {"accepted_tag": base, "accepted_sha": base},
            }
        ),
        encoding="utf-8",
    )
    commit(den317, "provenance")
    (den317 / "tracked.txt").write_text("dirty\n", encoding="utf-8")

    result = run(
        "python3",
        str(SCRIPT),
        "--upstream",
        str(upstream),
        "--target",
        base,
        "--den317",
        str(den317),
        check=False,
    )
    assert result.returncode == 2
    assert "working tree is dirty" in result.stderr


def test_conflicting_manual_base_is_rejected(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    init_repo(upstream)
    (upstream / "tracked.txt").write_text("base\n", encoding="utf-8")
    (upstream / "update.sh").write_text("base\n", encoding="utf-8")
    (upstream / "update-manifest.json").write_text("{}\n", encoding="utf-8")
    base = commit(upstream, "base")
    (upstream / "update-manifest.json").write_text(
        json.dumps({"upstream_provenance": {"accepted_tag": base, "accepted_sha": base}}),
        encoding="utf-8",
    )
    commit(upstream, "provenance")

    result = run(
        "python3",
        str(SCRIPT),
        "--upstream",
        str(upstream),
        "--base",
        "0" * 40,
        "--target",
        base,
        "--den317",
        str(upstream),
        check=False,
    )
    assert result.returncode == 2
    assert "differs from attested base" in result.stderr
