"""Versioned execution contracts over the frozen warehouse modelling rules.

The warehouse layer owns geometry, metadata validation, and shelf permissions.
These objects collect lifecycle/feature decisions so the kernel need not infer
a business contract from scattered version-string comparisons.
"""

from dataclasses import dataclass
from typing import Protocol

from agv.core import Profile
from agv.warehouse.rules import dispatch_status, validate_profile
from agv.warehouse.scenarios import Scenario


class Ruleset(Protocol):
    profile: Profile
    layered: bool
    catalog: bool
    stream: bool
    supports_positioning: bool
    supports_bounded_standby: bool

    def validate(self) -> None: ...

    def dispatchable(self, task, records, assigned, time) -> tuple[bool, str | None]: ...

    def pickup_candidates(self, task) -> tuple: ...

    def service_duration(self, task, leg: str) -> int: ...

    def is_terminal(self, cell) -> bool: ...

    def may_wait_at(self, cell) -> bool: ...

    def allowed_commands(self) -> frozenset[str]: ...

    def termination(self, plans, assigned, active, orders) -> bool: ...


@dataclass(frozen=True)
class LegacyRuleset:
    scenario: Scenario
    profile = Profile.LEGACY
    layered = False
    catalog = False
    stream = False
    supports_positioning = False
    supports_bounded_standby = False

    def validate(self):
        validate_profile(self.scenario)

    def dispatchable(self, task, records, assigned, time):
        return dispatch_status(self.scenario, task, records, assigned, time)

    def pickup_candidates(self, task):
        return tuple(self.scenario.pickup_candidates(task))

    def service_duration(self, task, leg):
        if leg == "pickup":
            return task.pickup_service
        if leg in ("drop", "delivery"):
            return task.delivery_service
        raise ValueError("Unknown service leg")

    def is_terminal(self, cell):
        return cell in self.scenario.stations

    def may_wait_at(self, cell):
        s = self.scenario
        return (
            self.layered
            and s.service_axis == "catalog"
            and cell in s.transit_only
            and cell not in s.homes
            and cell not in s.stations
            and cell not in s.pickup_zones
            and s.free(cell)
        )

    def allowed_commands(self):
        return frozenset(("assign", "replace_suffix"))

    def validate_options(
        self, idle_hold_steps=0, stream_open=False, positioning=False, *, reset=False
    ):
        """Preserve historical constructor/reset checks and their error text."""
        if not reset and (type(idle_hold_steps) is not int or not 0 <= idle_hold_steps <= 1000):
            raise ValueError("idle_hold_steps must be an integer from 0 to 1000")
        if idle_hold_steps and not self.catalog:
            raise ValueError("Bounded standby requires the explicit V9 catalog profile")
        if not reset and type(stream_open) is not bool:
            raise ValueError("stream_open must be boolean")
        if self.stream and idle_hold_steps:
            message = (
                "V9.1 does not accept a finite hold allowance"
                if reset
                else "V9.1 uses stream standby, not a finite hold allowance"
            )
            raise ValueError(message)
        if (not reset and type(positioning) is not bool) or (
            positioning and not self.supports_positioning
        ):
            raise ValueError("Positioning requires the explicit V9.1 profile")

    def termination(self, plans, assigned, active, orders):
        return (
            orders.final_return_ready(assigned, active)
            and all(len(plan) == 1 for plan in plans)
            and all(plan[0] == home for plan, home in zip(plans, self.scenario.homes))
        )


class V4Ruleset(LegacyRuleset):
    profile = Profile.V4
    layered = True


class V9Ruleset(V4Ruleset):
    profile = Profile.V9
    catalog = True
    supports_bounded_standby = True

    def allowed_commands(self):
        return super().allowed_commands() | {"hold"}


class V91Ruleset(V9Ruleset):
    profile = Profile.V91
    stream = True
    supports_positioning = True
    supports_bounded_standby = False

    def allowed_commands(self):
        return super().allowed_commands() | {"reposition"}


_RULESETS = {
    Profile.LEGACY: LegacyRuleset,
    Profile.V4: V4Ruleset,
    Profile.V9: V9Ruleset,
    Profile.V91: V91Ruleset,
}


def get_ruleset(scenario) -> Ruleset:
    """Resolve the contract after Scenario.check has rejected unknown metadata."""
    version = scenario.map_info.get("model_version", Profile.LEGACY)
    try:
        profile = Profile(version)
    except ValueError:
        profile = Profile.LEGACY
    return _RULESETS[profile](scenario)


def ordinary_transit(scenario, cell):
    """Compatibility helper for independent read-only policy geometry checks."""
    return get_ruleset(scenario).may_wait_at(cell)
