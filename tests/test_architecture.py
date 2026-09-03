"""설계서 §10·§11.1의 핵심 경계가 무너지지 않았는지 검사한다."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_DIRS = (ROOT / "fdt" / "data", ROOT / "fdt" / "ledger", ROOT / "fdt" / "twin")


def _python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_numeric_core_does_not_import_agent_or_rng_globals() -> None:
    """§10 에이전트·전역 난수 의존이 코어로 새지 않는다."""
    for directory in CORE_DIRS:
        for path in _python_files(directory):
            source = path.read_text(encoding="utf-8")
            imports = _imports(path)
            assert not any(name.startswith("fdt.agent") for name in imports), path
            assert "import random" not in source and "from random" not in source, path
            assert "hash(" not in source, path


def test_twin_does_not_read_generator_truth_or_profile_yaml() -> None:
    """§10 트윈은 평가 정답·숨은 프로필 설정을 읽지 않는다."""
    for path in _python_files(ROOT / "fdt" / "twin"):
        source = path.read_text(encoding="utf-8").lower()
        assert "ground_truth" not in source, path
        assert "hidden_params" not in source, path
        assert "yaml" not in source, path


def test_no_notimplemented_stubs_remain_in_package() -> None:
    """§11.1 최종 단계의 stub 0건을 고정한다."""
    for path in sorted((ROOT / "fdt").rglob("*.py")):
        assert "NotImplementedError" not in path.read_text(encoding="utf-8"), path
