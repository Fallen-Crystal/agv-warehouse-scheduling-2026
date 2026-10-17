"""Offline, same-scene normalization of the reviewed V4 objective.

The primary score is ``.5 * T/Tref + .3 * R/Rref + .2 * D/Dref`` (lower
is better). T is the last delivery completion time, R the mean order flow
time, and D all executed moves, including returns. The denominators come
from the fixed layer-aware distance-greedy policy with reservation-based
space-time A*, without joint replanning. They never enter an observation.

``reference_context`` returns a detached JSON-compatible context;
``score_result`` returns a detached result and leaves its input untouched.
Passing an explicit context does not establish trust: it must agree with
the independently reproduced reference for this exact serialized scene.
``validate_score`` checks all context and score fields. An execution auditor
that has already checked paths can pass ``execution_validated=True`` to
avoid repeating its own checks. The base auditor must only invoke this
function when objective fields are present; reference execution is unscored.
"""

import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from math import isclose, isfinite

OBJECTIVE_FIELD = "weighted_score"
OBJECTIVE_NAME = "归一化综合分数（整批时间50%＋平均订单耗时30%＋里程20%）"
MODEL_VERSION = "math-v4-reviewed-v1"
REFERENCE_POLICY = "per_face_layer_aware_distance_greedy_service2l_v2"
ENERGY_PER_MOVE = 0.05
TIME_WEIGHT = 0.5
RESPONSE_WEIGHT = 0.3
DISTANCE_WEIGHT = 0.2
WEIGHTS = {"time": TIME_WEIGHT, "response": RESPONSE_WEIGHT, "distance": DISTANCE_WEIGHT}

# Energy is a display-only estimate derived from distance, not a fourth term.
_NORMALIZED_FIELDS = (
    "normalized_time",
    "normalized_response",
    "normalized_distance",
    "normalized_energy",
)
_SCORE_FIELDS = frozenset(
    (
        "model_version",
        "objective_weights",
        "estimated_energy",
        "normalization_reference",
        "weighted_score",
        "score_valid",
    )
    + _NORMALIZED_FIELDS
)


def _model_version(scenario):
    return (
        "mixed-v9.1-reviewed-v1"
        if scenario.is_v9_1
        else "mixed-v9-reviewed-v1"
        if scenario.is_v9
        else MODEL_VERSION
    )


def _validate_execution(scenario, result):
    from agv.evaluation.validation import validate

    # Prevent recursion when validate() also audits scored results.
    validate(scenario, {key: value for key, value in result.items() if key not in _SCORE_FIELDS})


def _successful(result):
    return bool(
        result["feasible"]
        and result["comparison_valid"]
        and result.get("reason") is None
        and result.get("diagnostics", {}).get("execution_error") is None
    )


@lru_cache(maxsize=32)
def _cached_reference(raw_scene):
    from agv.dispatch.greedy import run
    from agv.domain import Scenario

    scenario = Scenario.from_dict(json.loads(raw_scene))
    result = run(scenario)
    _validate_execution(scenario, result)
    available = _successful(result) and (
        not scenario.tasks
        or all(result[name] > 0 for name in ("makespan", "mean_flow_time", "moves"))
    )
    return {
        "policy": "stream_standby_distance_greedy_service2l_v9_1"
        if scenario.is_v9_1
        else REFERENCE_POLICY,
        "model_version": _model_version(scenario),
        "scenario_sha256": hashlib.sha256(raw_scene.encode("utf-8")).hexdigest(),
        "available": bool(available),
        "time": result["makespan"] if available else None,
        "response": result["mean_flow_time"] if available else None,
        "distance": result["moves"] if available else None,
        "energy": ENERGY_PER_MOVE * result["moves"] if available else None,
    }


def reference_context(scenario):
    """Reproduce the fixed baseline once per scene; return a detached context.

    The cache holds at most 32 scene/context pairs, never candidate results.
    Its key includes all serialized scene inputs, including the horizon and
    layer/service rules. A failed baseline has ``available=False`` and null
    denominators, rather than substituting candidate-dependent constants.
    """
    raw_scene = json.dumps(scenario.to_dict(), sort_keys=True, separators=(",", ":"))
    return deepcopy(_cached_reference(raw_scene))


def _equal(actual, expected):
    """Compare JSON values, rejecting booleans/nonfinite numbers as metrics."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_equal(actual[key], value) for key, value in expected.items())
        )
    if type(expected) in (int, float):
        return (
            type(actual) in (int, float)
            and isfinite(actual)
            and isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
        )
    return type(actual) is type(expected) and actual == expected


def _trusted_reference(scenario, supplied):
    expected = reference_context(scenario)
    if supplied is not None and not _equal(supplied, expected):
        raise ValueError("Normalization reference differs from the fixed same-scene baseline")
    return expected


def _score_fields(scenario, result, context):
    fields = {
        "model_version": _model_version(scenario),
        "objective_weights": dict(WEIGHTS),
        "estimated_energy": ENERGY_PER_MOVE * result["moves"],
        "normalization_reference": deepcopy(context),
        "score_valid": bool(
            _successful(result)
            and context["available"]
            and (bool(scenario.tasks) or result["moves"] == 0)
        ),
        "weighted_score": None,
        **{name: None for name in _NORMALIZED_FIELDS},
    }
    if fields["score_valid"]:
        if scenario.tasks:
            nt = result["makespan"] / context["time"]
            nr = result["mean_flow_time"] / context["response"]
            nd = result["moves"] / context["distance"]
        else:
            nt = nr = nd = 0.0
        fields.update(
            normalized_time=nt,
            normalized_response=nr,
            normalized_distance=nd,
            normalized_energy=nd,
            weighted_score=TIME_WEIGHT * nt + RESPONSE_WEIGHT * nr + DISTANCE_WEIGHT * nd,
        )
    return fields


def score_result(scenario, result, reference=None):
    """Return an independently execution-validated result with offline scores.

    ``reference`` may be a context returned by ``reference_context``. Its
    denominators, scene digest, policy and model version are all verified.
    An invalid trace raises ValueError; a valid unfinished/failed execution
    remains reportable but has no normalized metrics or primary score.
    A successful stationary empty scene scores zero. Empty executions with
    movement retain actual distance/energy but have no normalized score:
    their fixed zero-demand reference has zero distance. Original fields survive.
    """
    _validate_execution(scenario, result)
    context = _trusted_reference(scenario, reference)
    scored = deepcopy(result)
    scored.update(_score_fields(scenario, result, context))
    return scored


def validate_score(scenario, result, reference_context=None, *, execution_validated=False):
    """Audit reported score/context without trusting any reported denominator.

    The optional context is also compared with a reproduced reference, so
    callers cannot validate a forged score by supplying a forged reference.
    ``execution_validated`` is intended only for the independent path auditor.
    """
    if not execution_validated:
        _validate_execution(scenario, result)
    context = _trusted_reference(scenario, reference_context)
    expected = _score_fields(scenario, result, context)
    for name, value in expected.items():
        if name not in result or not _equal(result[name], value):
            raise ValueError("Wrong objective field: " + name)
    return True


def objective_value(result):
    """Read a previously validated score; missing/failed scores return None."""
    value = result.get(OBJECTIVE_FIELD)
    if (
        result.get("comparison_valid") is True
        and result.get("score_valid") is True
        and type(value) in (int, float)
        and isfinite(value)
        and value >= 0
    ):
        return value
    return None
