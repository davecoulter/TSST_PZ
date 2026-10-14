"""Integration tests for scripts/ingest_candidates_cli.py (#25).

The CLI is run as a subprocess against the live service, the way a user runs it.
Payload contract: agentic_planning/023-add-candidate-endpoint/contract.md.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import unique_name
from test_add_candidate import candidate_payload

pytestmark = pytest.mark.integration

CLI = Path(__file__).resolve().parents[2] / "scripts" / "ingest_candidates_cli.py"


@pytest.fixture
def cli(base_url, credentials):
    """Run the CLI; returns the CompletedProcess. No terminal is attached, so a
    missing password cannot be prompted for."""
    def _run(*args, password=credentials[1]):
        env = {k: v for k, v in os.environ.items() if k not in ("URL", "YSE_URL", "USER_YSE", "PW")}
        env.update(YSE_URL=base_url, USER_YSE=credentials[0])
        if password is not None:
            env["PW"] = password
        return subprocess.run([sys.executable, str(CLI), *map(str, args)], env=env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
    return _run


def write_json(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_dry_run_reports_and_saves_nothing(cli, tmp_path, new_transient, api_get):
    path = write_json(tmp_path, "run.json", [candidate_payload(**new_transient)])
    result = cli("--dry-run", path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "would create" in result.stdout
    assert "dry run, nothing saved" in result.stdout
    assert api_get(f"/api/transients/?name={new_transient['name']}&format=json")["results"] == []


def test_single_object_file_is_created_then_appended(cli, tmp_path, new_transient, api_get):
    path = write_json(tmp_path, "one.json", candidate_payload(**new_transient))  # an object, not an array
    first = cli(path)
    assert first.returncode == 0, first.stdout + first.stderr
    assert " created " in first.stdout and "1 created" in first.stdout
    assert api_get(f"/api/transients/?name={new_transient['name']}&format=json")["results"]

    again = cli(path)
    assert again.returncode == 0, again.stdout + again.stderr
    assert " appended " in again.stdout and "2 superseded" in again.stdout


def test_bad_candidate_is_reported_and_the_good_one_is_saved(cli, tmp_path, new_transient, api_get):
    good = candidate_payload(**new_transient)
    bad = candidate_payload(unique_name("bad"), new_transient["ra"], new_transient["dec"])
    del bad["ra"]
    result = cli(write_json(tmp_path, "mixed.json", [bad, good]))
    assert result.returncode == 1
    assert "FAILED" in result.stdout and bad["candidate_id"] in result.stdout and "ra: required" in result.stdout
    assert "1 created" in result.stdout and "1 failed" in result.stdout
    assert api_get(f"/api/transients/?name={new_transient['name']}&format=json")["results"]
    assert api_get(f"/api/transients/?name={bad['candidate_id']}&format=json")["results"] == []


def test_an_unreadable_file_does_not_stop_the_run(cli, tmp_path, new_transient, api_get):
    good = write_json(tmp_path, "good.json", [candidate_payload(**new_transient)])
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    result = cli(broken, tmp_path / "missing.json", good)
    assert result.returncode == 1
    assert "broken.json" in result.stdout and "missing.json" in result.stdout
    assert "1 created" in result.stdout
    assert api_get(f"/api/transients/?name={new_transient['name']}&format=json")["results"]


def test_missing_password_without_a_terminal_exits_2(cli, tmp_path, new_transient):
    result = cli(write_json(tmp_path, "run.json", [candidate_payload(**new_transient)]), password=None)
    assert result.returncode == 2
    assert "no password" in result.stderr


def test_bad_login_exits_2_and_sends_nothing(cli, tmp_path, new_transient, api_get):
    path = write_json(tmp_path, "run.json", [candidate_payload(**new_transient)])
    result = cli(path, password="definitely-wrong")
    assert result.returncode == 2
    assert "rejected the login" in result.stderr
    assert api_get(f"/api/transients/?name={new_transient['name']}&format=json")["results"] == []


def test_target_is_printed_before_sending(cli, tmp_path, new_transient, base_url):
    result = cli("--dry-run", write_json(tmp_path, "run.json", [candidate_payload(**new_transient)]))
    assert f"Target: {base_url}" in result.stderr
