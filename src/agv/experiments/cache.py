"""Content-addressed local results; a cache label never establishes validity."""

import hashlib
import json
import os
import platform
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path

from agv.io.scenes import scenario_id
from agv.io.storage import write_json

SCHEMA = "agv-experiment-cache-v1"


def _normalize(value):
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalize(item) for item in value), key=canonical)
    return value


def canonical(value):
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def cache_key(identity):
    return hashlib.sha256(canonical(identity).encode("utf-8")).hexdigest()


def cache_identity(scene, spec, seed, config, sources, *, resources=None):
    """Freeze the complete scene, solver, configuration and executable inputs."""
    normalized_scene = _normalize(scene.to_dict())
    return _normalize(
        dict(
            schema=SCHEMA,
            scene=normalized_scene,
            scenario_sha256=scenario_id(scene),
            solver=spec,
            seed=seed,
            config=config,
            source_hashes=sources,
            resource_hashes=resources or {},
            runtime=dict(
                python=platform.python_version(), implementation=platform.python_implementation()
            ),
        )
    )


def default_cache_dir():
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "agv-warehouse-scheduling" / "experiments-v1"


class ResultCache:
    def __init__(self, root):
        self.root = Path(root)

    def path(self, identity):
        return self.root / (cache_key(identity) + ".json")

    def load(self, identity, check):
        """Recheck identity, payload integrity and independent execution validity."""
        path = self.path(identity)
        if not path.exists():
            return None, "miss"
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            if (
                entry["schema"] != SCHEMA
                or canonical(entry["identity"]) != canonical(identity)
                or entry["payload_sha256"] != cache_key(entry["payload"])
            ):
                return None, "invalid"
            check(entry["payload"])
            return entry["payload"], "hit"
        except Exception:
            return None, "invalid"

    def store(self, identity, payload):
        write_json(
            self.path(identity),
            dict(
                schema=SCHEMA,
                identity=_normalize(identity),
                payload=payload,
                payload_sha256=cache_key(payload),
            ),
            overwrite=True,
        )
