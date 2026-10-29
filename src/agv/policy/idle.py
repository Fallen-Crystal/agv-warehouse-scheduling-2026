"""Visible-state idle decisions; mutations go through world command methods."""

from agv.rules import ordinary_transit as _ordinary_transit
from agv.warehouse.scenarios import Scenario


def hold_return(env, vehicle, steps=1):
    return env.hold(vehicle, steps)


def advance_standby(env, geometry=None):
    obs = env.observe_view()
    limit = obs.get("idle_hold_steps", 0)
    if type(limit) is not int or limit < 0:
        raise ValueError("idle_hold_steps must be a nonnegative integer")
    stream = obs.get("idle_policy") == "stream"
    if (
        stream
        and obs["order_stream_closed"]
        and not obs["pending"]
        and all(v["available"] for v in obs["vehicles"])
    ):
        return
    if not limit and not stream:
        return
    scenario = geometry or Scenario.from_observation_map(obs["map"], obs["horizon"])
    if not scenario.uses_layer_rules or scenario.service_axis != "catalog":
        return
    for vehicle in obs["vehicles"]:
        k = vehicle["id"]
        path = vehicle["return_path"]
        if "positioning_targets" in obs:
            target = obs["positioning_targets"][k]
            if (
                target is None
                or obs["time"] < target["arrival"]
                or vehicle["position"] != target["target"]
            ):
                continue
        if (
            not vehicle["available"]
            or len(path) <= 1
            or (not stream and obs["idle_hold_counts"][k] >= limit)
            or not _ordinary_transit(scenario, vehicle["position"])
        ):
            continue
        try:
            env.hold(k, counted=True)
        except ValueError:
            if "positioning_targets" in obs:
                env.clear_position_target(k)
