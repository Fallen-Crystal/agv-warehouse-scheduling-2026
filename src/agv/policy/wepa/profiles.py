"""Predeclared interventions; no warehouse or objective changes."""

PROFILES = {
    "hungarian": dict(proxy=0, previews=0, generations=0, gate=False, anchor=False, repair=0),
    "hga": dict(
        proxy=192,
        previews=6,
        generations=16,
        gate=True,
        anchor=False,
        repair=0,
        hungarian_seeds=True,
    ),
    "compound": dict(
        proxy=144,
        previews=6,
        generations=16,
        gate=True,
        anchor=False,
        repair=48,
        compound=True,
        local_previews=3,
    ),
    "compound_only": dict(
        proxy=0,
        previews=6,
        generations=0,
        gate=True,
        anchor=False,
        repair=48,
        compound=True,
        local_previews=5,
    ),
    "lns": dict(
        proxy=144, previews=6, generations=16, gate=True, anchor=False, repair=48, targeted=True
    ),
    "coord": dict(
        proxy=192, previews=6, generations=16, gate=True, anchor=False, repair=0, coordination=True
    ),
    "coupled": dict(
        proxy=144,
        previews=6,
        generations=16,
        gate=True,
        anchor=False,
        repair=48,
        targeted=True,
        coordination=True,
    ),
    "open_gate": dict(
        proxy=192, previews=6, generations=16, gate=True, anchor=False, repair=0, terminal="standby"
    ),
    "simple": dict(proxy=96, previews=3, generations=8, gate=False, anchor=False, repair=0),
    "wide": dict(proxy=192, previews=6, generations=16, gate=False, anchor=False, repair=0),
    "gate": dict(proxy=192, previews=6, generations=16, gate=True, anchor=False, repair=0),
    "anchor": dict(proxy=192, previews=6, generations=16, gate=False, anchor=True, repair=0),
    "restored": dict(proxy=144, previews=6, generations=10, gate=True, anchor=False, repair=48),
    "guided": dict(
        proxy=192, previews=6, generations=16, gate=False, anchor=False, repair=0, local_seeds=True
    ),
    "guided_gate": dict(
        proxy=192,
        previews=6,
        generations=16,
        gate=True,
        anchor=False,
        repair=0,
        local_seeds=True,
        linear_matching=True,
    ),
}

# Independent interventions retain the existing gate as the comparison arm.
PROFILES.update(
    gate_anchor=dict(PROFILES["gate"], previews=7, base_previews=6, second_anchor=True),
    gate_anchor_tail=dict(
        PROFILES["gate"], previews=7, base_previews=6, second_anchor=True, tail=True
    ),
    gate_tail=dict(PROFILES["gate"], tail=True),
    gate_trigger=dict(PROFILES["gate"], trigger_ratio=3),
)
