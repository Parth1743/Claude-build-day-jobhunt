import pytest
from typer.testing import CliRunner

from jobhunt.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_HOME", str(tmp_path))
    return tmp_path


def run(*args):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_end_to_end_offline_flow(tmp_path):
    run("init")
    out = run("ledger", "add", "experience", "Backend Engineer", "--org", "Acme",
              "--start", "2022-01", "--skills", "Python,PostgreSQL", "--desc", "Built billing APIs")
    assert "Added experience #1" in out
    run("ledger", "add", "skill", "Python", "--level", "advanced")
    assert "Backend Engineer" in run("ledger", "list")
    assert "advanced" in run("ledger", "skills")

    run("ledger", "edit", "1", "--add-skills", "Docker")
    assert "Docker" in run("ledger", "show", "1")

    run("role", "add", "Platform Engineer", "--skills", "Python,Kubernetes,Terraform")
    show = run("role", "show", "platform engineer")
    assert "have" in show and "gap" in show

    jd = tmp_path / "jd.txt"
    jd.write_text("We need Kubernetes and Python.", encoding="utf-8")
    out = run("job", "add", "Globex", "Platform Eng", "--role", "Platform Engineer", "--jd", str(jd))
    assert "Saved job #1" in out
    run("job", "status", "1", "applied", "--note", "referral")
    run("job", "note", "1", "phone screen Friday")
    show = run("job", "show", "1")
    assert "applied" in show and "phone screen" in show
    assert "Not analyzed yet" in show

    exported = tmp_path / "profile.md"
    run("ledger", "export", "--out", str(exported))
    assert "## Experience" in exported.read_text(encoding="utf-8")

    status = run("status")
    assert "Pipeline" in status and "Roadmaps" in status


def test_errors_are_clean():
    result = runner.invoke(app, ["ledger", "show", "42"])
    assert result.exit_code == 1
    result = runner.invoke(app, ["job", "status", "1", "applied"])
    assert result.exit_code == 1
    result = runner.invoke(app, ["ledger", "add", "hobby", "Chess"])
    assert result.exit_code == 1


def test_ai_commands_need_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-invalid")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")  # nothing listens here
    run("ledger", "add", "skill", "Python", "--level", "advanced")
    result = runner.invoke(app, ["role", "add", "Data Engineer", "--ai"])
    assert result.exit_code == 1
    assert "Could not reach" in result.output or "Anthropic" in result.output


def test_settings_cli(tmp_path, monkeypatch):
    for var in ("GROQ_API_KEY", "JOBHUNT_PROVIDER", "JOBHUNT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    out = run("settings", "set", "--provider", "groq", "--model", "llama-3.3-70b-versatile", "--key", "gsk_abc12345")
    assert "groq" in out.lower() and "2345" in out and "gsk_abc" not in out
    out = run("settings", "show")
    assert "key configured" in out
    run("settings", "clear-key", "groq")
    assert "no key" in run("settings", "show")
