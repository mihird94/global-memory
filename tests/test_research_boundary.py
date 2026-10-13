"""Enforce the one-way dependency from experiments to the memory product."""
import ast
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def test_product_does_not_import_experimental_packages():
    violations = []
    for path in (ROOT / "tools").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                if name.split(".")[0] in {"research_harness", "eval", "research", "ccmp_v1", "ccmp_behavioral", "ccmp_recovery"}:
                    violations.append(f"{path.name}:{node.lineno}: {name}")
    assert not violations, violations


def test_legacy_eval_command_only_explains_migration(capsys):
    from memoryctl import cmd_eval_lab

    assert cmd_eval_lab(SimpleNamespace(action="run", live=True)) == 2
    assert "research_harness.eval.cli" in capsys.readouterr().out
