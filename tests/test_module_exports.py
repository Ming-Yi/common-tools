import ast
from pathlib import Path

import common_tools


def test_every_source_module_declares_all() -> None:
    package_root = Path(common_tools.__file__).parent
    missing: list[str] = []

    for module_path in sorted(package_root.rglob("*.py")):
        if module_path.name == "__init__.py":
            continue

        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        declares_all = any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
            )
            for node in tree.body
        )
        if not declares_all:
            missing.append(str(module_path.relative_to(package_root)))

    assert missing == []
