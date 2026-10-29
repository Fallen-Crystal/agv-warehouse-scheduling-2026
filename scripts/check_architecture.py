#!/usr/bin/env python3
"""Check dependency direction and state ownership without importing the package.

Compatibility facades are exempt as *callers*; production implementations may
not depend on them. ``registry`` and ``runner`` are explicit composition roots.
The evaluation reference runner is also a composition root, while the validator
has no dependency on execution or planning implementations.
"""

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path

COMPATIBILITY_MODULES = frozenset(
    ("agv.domain", "agv.simulation", "agv.planning.reservations", "agv.planning.reposition")
)
COMPOSITION_MODULES = frozenset(("agv.registry", "agv.evaluation.reference"))
ALLOWED_LAYERS = {
    "core": frozenset(("core",)),
    "warehouse": frozenset(("core", "warehouse")),
    "rules": frozenset(("core", "warehouse", "rules")),
    "orders": frozenset(("core", "orders")),
    "data": frozenset(("core", "warehouse", "rules", "orders", "data")),
    "world": frozenset(("core", "warehouse", "rules", "orders", "world")),
    "planning": frozenset(("core", "warehouse", "rules", "world", "planning")),
    "policy": frozenset(
        ("core", "warehouse", "rules", "orders", "world", "planning", "policy", "learning")
    ),
    "runner": frozenset(
        (
            "core",
            "warehouse",
            "rules",
            "orders",
            "world",
            "planning",
            "policy",
            "registry",
            "evaluation",
            "runner",
            "simulation",
        )
    ),
}
PRIVATE_STATE = frozenset(
    (
        "_plans",
        "_records",
        "_active",
        "_paths",
        "_assigned",
        "_idle_waits",
        "_idle_hold_counts",
        "_position_targets",
        "_position_events",
        "_replans",
    )
)
MUTATORS = frozenset(
    (
        "append",
        "extend",
        "insert",
        "pop",
        "remove",
        "clear",
        "add",
        "update",
        "discard",
        "setdefault",
    )
)
RESERVATION_CLASSES = frozenset(("ReservationTable", "PlanReservations", "VertexReservations"))
LEGACY_RUN_MODULES = frozenset(
    f"agv.dispatch.{name}" for name in ("greedy", "optimized", "stream", "bcrd")
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    code: str
    message: str

    def __str__(self):
        return f"{self.path}:{self.line}: {self.code} {self.message}"


def _inside(module, prefix):
    return module == prefix or module.startswith(prefix + ".")


def _compatibility(module):
    return _inside(module, "agv.dispatch") or any(
        _inside(module, prefix) for prefix in COMPATIBILITY_MODULES
    )


def _imports(tree, module, is_package):
    """Include local imports, TYPE_CHECKING imports and literal dynamic imports."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = module.split(".") if is_package else module.split(".")[:-1]
                prefix = package[: len(package) - node.level + 1]
                base = ".".join(prefix + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            # ``from agv import simulation`` needs the imported child name;
            # appending symbols elsewhere also preserves their owning prefix.
            for alias in node.names:
                yield node.lineno, base + "." + alias.name
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            literal = node.args[0].value
            dynamic = (isinstance(node.func, ast.Name) and node.func.id == "__import__") or (
                isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
            )
            if dynamic and isinstance(literal, str):
                yield node.lineno, literal


def _private_roots(node):
    return {
        child.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute) and child.attr in PRIVATE_STATE
    }


def _private_writes(tree):
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, (ast.Assign, ast.Delete)):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = [node.target]
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in MUTATORS:
                targets = [node.func.value]
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id in ("setattr", "delattr")
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in PRIVATE_STATE
            ):
                yield node.lineno, node.args[1].value
        for target in targets:
            for name in sorted(_private_roots(target)):
                yield node.lineno, name


def check_architecture(root):
    root = Path(root)
    package = root / "src" / "agv"
    violations = []
    kernels, runners, reservation_owners = [], [], set()

    def report(path, line, code, message):
        violations.append(Violation(path.relative_to(root), line, code, message))

    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(root / "src").with_suffix("")
        module = ".".join(relative.parts)
        is_package = path.name == "__init__.py"
        if is_package:
            module = module.removesuffix(".__init__")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            report(path, error.lineno or 1, "syntax", error.msg)
            continue
        layer = module.split(".")[1] if "." in module else ""
        for line, imported in _imports(tree, module, is_package):
            if imported.split(".")[0] in {"wepa", "improved", "v2", "simple", "paths", "objective"}:
                report(
                    path,
                    line,
                    "research-namespace",
                    f"production import still depends on archive namespace {imported}",
                )
            if not _inside(imported, "agv") or _compatibility(module):
                continue
            target_layer = imported.split(".")[1] if "." in imported else ""
            if _compatibility(imported) and not (
                layer == "runner" and _inside(imported, "agv.simulation")
            ):
                report(
                    path, line, "compat-import", f"{module} imports compatibility facade {imported}"
                )
                continue
            if module in COMPOSITION_MODULES:
                continue
            if layer in ALLOWED_LAYERS and target_layer not in ALLOWED_LAYERS[layer]:
                report(path, line, "dependency", f"{layer} may not import {imported}")
            if (
                layer == "policy"
                and target_layer == "learning"
                and not _inside(imported, "agv.learning.ranker")
            ):
                report(
                    path,
                    line,
                    "dependency",
                    f"policy may only import learning.ranker, not {imported}",
                )
            if _inside(module, "agv.learning.ranker") and target_layer != "core":
                report(
                    path,
                    line,
                    "ranker-independence",
                    "candidate ranker may only depend on core data and pure functions",
                )
            if (
                _inside(module, "agv.evaluation.validation") or module == "agv.evaluation.wepa"
            ) and target_layer in (
                "world",
                "planning",
                "policy",
                "dispatch",
                "simulation",
                "runner",
                "registry",
            ):
                report(
                    path,
                    line,
                    "validator-independence",
                    f"independent validator imports {imported}",
                )
        if layer != "world":
            for line, name in _private_writes(tree):
                report(
                    path,
                    line,
                    "state-ownership",
                    f"private state {name} may only be written by world",
                )
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
                loops = [item for item in ast.walk(node) if isinstance(item, ast.While)]
                if module in LEGACY_RUN_MODULES and loops:
                    report(
                        path,
                        node.lineno,
                        "duplicate-runner",
                        "historical run entry points must delegate without a loop",
                    )
                if module == "agv.runner.run":
                    runners.extend((path, item.lineno) for item in loops)
            elif isinstance(node, ast.ClassDef):
                methods = {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
                if {"tick", "assign", "result"} <= methods:
                    kernels.append((path, node.lineno, module, node.name))
                if node.name in RESERVATION_CLASSES:
                    reservation_owners.add(module)
                    if module != "agv.world.reservations":
                        report(
                            path,
                            node.lineno,
                            "reservation-ownership",
                            f"{node.name} belongs in world.reservations",
                        )
    if len(runners) != 1:
        violations.append(
            Violation(
                Path("src/agv/runner/run.py"),
                1,
                "runner-count",
                f"expected one execution loop, found {len(runners)}",
            )
        )
    if len(kernels) != 1 or kernels[0][2:] != ("agv.world.state", "WorldState"):
        violations.append(
            Violation(
                Path("src/agv/world/state.py"),
                1,
                "kernel-count",
                f"expected only world.state.WorldState, found {[(m, n) for _, _, m, n in kernels]}",
            )
        )
    if reservation_owners != {"agv.world.reservations"}:
        violations.append(
            Violation(
                Path("src/agv/world/reservations.py"),
                1,
                "reservation-count",
                "reservation implementations must have exactly one owning module",
            )
        )
    return sorted(violations, key=lambda item: (str(item.path), item.line, item.code))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    options = parser.parse_args(argv)
    violations = check_architecture(options.root)
    for violation in violations:
        print(violation)
    if violations:
        print(f"Architecture check failed: {len(violations)} violation(s).")
        return 1
    print(
        "Architecture check passed: dependency direction, state ownership, one runner/kernel/reservation owner."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
