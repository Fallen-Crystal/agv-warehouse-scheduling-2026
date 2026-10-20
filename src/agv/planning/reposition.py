"""Compatibility import: reposition commands are owned by the world gateway."""


def reposition(env, vehicle, target):
    return env.reposition(vehicle, target)
