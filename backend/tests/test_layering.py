"""Executable version of the project's layering rules.

The decision engine only stays independently testable if it never reaches for the ORM,
the HTTP client, or the web framework. Comments do not enforce that; this test does.
Packages that do not exist yet are skipped, so the rule can be in place before the code
it guards is written.
"""

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# layer package -> import prefixes it must never pull in
FORBIDDEN_IMPORTS: dict[str, set[str]] = {
    "engine": {
        "sqlalchemy",
        "httpx",
        "fastapi",
        "app.db",
        "app.repositories",
        "app.tmdb",
        "app.api",
        "app.services",
    },
    "repositories": {"fastapi", "httpx", "app.tmdb", "app.engine", "app.api", "app.services"},
    "tmdb": {"sqlalchemy", "fastapi", "app.db", "app.repositories", "app.api", "app.services"},
    "api": {"app.db.models", "app.tmdb", "app.repositories"},
}


def _imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _violations(layer: str, forbidden: set[str]) -> list[str]:
    layer_root = APP_ROOT / layer
    if not layer_root.is_dir():
        return []

    found: list[str] = []
    for path in sorted(layer_root.rglob("*.py")):
        for module in _imported_modules(path.read_text(encoding="utf-8")):
            for banned in forbidden:
                if module == banned or module.startswith(f"{banned}."):
                    found.append(f"{path.relative_to(APP_ROOT.parent)} imports {module}")
    return found


def test_layers_respect_their_boundaries() -> None:
    all_violations = [
        violation
        for layer, banned in FORBIDDEN_IMPORTS.items()
        for violation in _violations(layer, banned)
    ]
    assert not all_violations, "layer boundary violated:\n  " + "\n  ".join(all_violations)
