"""Product-shell tests that never contact a real model provider."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import minicodex.main as main_module
from .. import __version__
from ..llm import ModelConfig, ModelConfigurationError


_MODEL_ENV = (
    "MINICODEX_API_KEY",
    "MINICODEX_BASE_URL",
    "MINICODEX_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
)


def _clear_model_environment(monkeypatch):
    for name in _MODEL_ENV:
        monkeypatch.delenv(name, raising=False)


def test_model_config_prefers_product_variables_and_never_exposes_key(monkeypatch):
    _clear_model_environment(monkeypatch)
    monkeypatch.setenv("MINICODEX_API_KEY", "top-secret")
    monkeypatch.setenv("MINICODEX_BASE_URL", "https://provider.example/v1/")
    monkeypatch.setenv("MINICODEX_MODEL", "code-model")

    config = ModelConfig.from_environment()

    assert config.configured
    assert config.api_key == "top-secret"
    assert config.api_key_source == "MINICODEX_API_KEY"
    assert config.base_url == "https://provider.example/v1"
    assert config.model == "code-model"
    assert "top-secret" not in repr(config)
    assert "top-secret" not in repr(config.problems())


def test_model_config_rejects_missing_key_and_invalid_url(monkeypatch):
    _clear_model_environment(monkeypatch)
    config = ModelConfig.from_environment(base_url="not-a-url")

    with pytest.raises(ModelConfigurationError, match="API Key"):
        config.require_ready()
    assert any("Base URL" in problem for problem in config.problems())


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as stopped:
        main_module.main(["--version"])

    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip() == f"MiniCodex {__version__}"


def test_package_module_entrypoint_reports_version():
    result = subprocess.run(
        [sys.executable, "-m", "minicodex", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"MiniCodex {__version__}"


def test_doctor_json_is_machine_readable_and_missing_key_is_not_ready(
    monkeypatch, tmp_path, capsys,
):
    monkeypatch.chdir(tmp_path)
    _clear_model_environment(monkeypatch)

    exit_code = main_module.main(["doctor", "--json", "--workspace", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ready"] is False
    api_key = next(check for check in payload["checks"] if check["name"] == "api_key")
    assert api_key["passed"] is False


def test_run_subcommand_dispatches_with_resolved_configuration(
    monkeypatch, tmp_path, capsys,
):
    monkeypatch.chdir(tmp_path)
    _clear_model_environment(monkeypatch)
    monkeypatch.setenv("MINICODEX_API_KEY", "secret")
    observed = {}

    def fake_run_once(config, prompt, *, model_config, output_level):
        observed.update(
            workspace=config.workspace_root,
            prompt=prompt,
            model=model_config.model,
            output=output_level,
        )
        return "done"

    monkeypatch.setattr(main_module, "run_once", fake_run_once)
    exit_code = main_module.main([
        "run", "fix it", "--workspace", str(tmp_path),
        "--model", "custom-model", "--output", "verbose",
    ])

    assert exit_code == 0
    assert observed == {
        "workspace": tmp_path.resolve(),
        "prompt": "fix it",
        "model": "custom-model",
        "output": "verbose",
    }
    output = capsys.readouterr().out
    assert "done" in output
    assert "latest.jsonl" in output


def test_global_runtime_options_work_before_subcommand(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear_model_environment(monkeypatch)
    monkeypatch.setenv("MINICODEX_API_KEY", "secret")
    observed = []

    def fake_run_once(config, prompt, *, model_config, output_level):
        observed.append((config.workspace_root, prompt, model_config.model, output_level))
        return "done"

    monkeypatch.setattr(main_module, "run_once", fake_run_once)
    assert main_module.main([
        "--workspace", str(tmp_path), "--model", "parent-model",
        "--output", "debug", "run", "fix it",
    ]) == 0
    assert observed == [(tmp_path.resolve(), "fix it", "parent-model", "debug")]


def test_legacy_prompt_stays_compatible(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _clear_model_environment(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    observed = []

    def fake_run_once(_config, prompt, *, model_config, output_level):
        observed.append((prompt, model_config.api_key_source, output_level))
        return "done"

    monkeypatch.setattr(main_module, "run_once", fake_run_once)
    assert main_module.main([
        "--workspace", str(tmp_path), "--prompt", "legacy task",
    ]) == 0
    assert observed == [("legacy task", "DEEPSEEK_API_KEY", "normal")]


def test_run_without_key_fails_before_agent_construction(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    _clear_model_environment(monkeypatch)
    monkeypatch.setattr(
        main_module,
        "run_once",
        lambda *_args, **_kwargs: pytest.fail("agent must not start"),
    )

    assert main_module.main(["run", "fix it", "--workspace", str(tmp_path)]) == 2
    error = capsys.readouterr().err
    assert "配置错误" in error
    assert "minicodex doctor" in error
