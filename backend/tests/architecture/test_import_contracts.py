"""The hexagonal boundaries of ADR 0009, enforced by import-linter (design D1).

The first test runs the real contracts against the real package. The others
prove the contracts have teeth: they build a throwaway copy of the package
layout in which the domain or application layer imports a framework, and
check that import-linter rejects it with the same contract configuration.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
PYPROJECT = BACKEND_DIR / "pyproject.toml"
LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"

PACKAGES = (
    "podiumd_admin",
    "podiumd_admin/domain",
    "podiumd_admin/application",
    "podiumd_admin/ports",
    "podiumd_admin/adapters",
    "podiumd_admin/adapters/http",
    "podiumd_admin/adapters/db",
    "podiumd_admin/adapters/oidc",
    "podiumd_admin/adapters/logging",
)


def _lint_imports(
    cwd: Path, config: Path, pythonpath: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if pythonpath is not None:
        # Put the throwaway package ahead of the installed (editable) one.
        env["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(  # noqa: S603 - fixed executable from our own venv, no shell
        [str(LINT_IMPORTS), "--config", str(config), "--no-cache"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_config_with_real_contracts(target: Path) -> Path:
    """Write a pyproject.toml that holds only the real import-linter section."""
    real = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["importlinter"]
    lines = ["[tool.importlinter]"]
    lines += [f"{key} = {_toml(value)}" for key, value in real.items() if key != "contracts"]
    for contract in real["contracts"]:
        lines.append("\n[[tool.importlinter.contracts]]")
        lines += [f"{key} = {_toml(value)}" for key, value in contract.items()]
    config = target / "pyproject.toml"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


def _toml(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml(item) for item in value) + "]"
    raise TypeError(f"unsupported TOML value in import-linter config: {value!r}")


def test_package_honours_the_hexagonal_import_contracts() -> None:
    result = _lint_imports(cwd=BACKEND_DIR, config=PYPROJECT)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 broken" in result.stdout


def _lint_package_with_leak(tmp_path: Path, module: str, source: str) -> str:
    """Lint a throwaway package whose ``module`` holds ``source``; return stdout.

    Asserts that import-linter, configured with the real contracts, fails.
    """
    src = tmp_path / "src"
    for package in PACKAGES:
        (src / package).mkdir(parents=True)
        (src / package / "__init__.py").write_text("", encoding="utf-8")
    (src / f"{module.replace('.', '/')}.py").write_text(source, encoding="utf-8")
    config = _write_config_with_real_contracts(tmp_path)

    result = _lint_imports(cwd=tmp_path, config=config, pythonpath=src)

    assert result.returncode != 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize("layer", ["domain", "application"])
@pytest.mark.parametrize("framework", ["fastapi", "sqlalchemy", "authlib"])
def test_contract_rejects_a_framework_import_in_the_inner_layers(
    tmp_path: Path, layer: str, framework: str
) -> None:
    module = f"podiumd_admin.{layer}.leak"

    stdout = _lint_package_with_leak(tmp_path, module, f"import {framework}\n")

    assert f"{module} -> {framework}" in stdout


def test_contract_rejects_the_domain_depending_on_an_adapter(tmp_path: Path) -> None:
    module = "podiumd_admin.domain.leak"

    stdout = _lint_package_with_leak(tmp_path, module, "import podiumd_admin.adapters.db\n")

    assert f"{module} -> podiumd_admin.adapters.db" in stdout
