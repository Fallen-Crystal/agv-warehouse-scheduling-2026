"""Composition adapter for the fixed historical A* reference execution.

Kept distinct from the independent validator and from online policies. The
compatibility call preserves the documented reference and existing audit hooks.
"""


def run(scenario):
    from agv.runner.compat import run_baseline as baseline

    return baseline(scenario)
