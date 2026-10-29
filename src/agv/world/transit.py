"""The shared one-tick vehicle movement and trace recorder for every profile."""

from agv.world.itinerary import Itinerary


def advance_fleet(plans, histories, labels, state_at, time, *, coerce_itineraries=False):
    moves = 0
    for vehicle, plan in enumerate(plans):
        labels[vehicle].append(state_at(vehicle))
        previous = plan[0]
        if len(plan) > 1:
            if isinstance(plan, Itinerary):
                plans[vehicle] = plan.advance()
            elif coerce_itineraries:
                plans[vehicle] = Itinerary(plan, 1)
            else:
                plans[vehicle] = plan[1:]
        following = plans[vehicle][0]
        moves += following != previous
        histories[vehicle].append(following)
    return time + 1, moves
