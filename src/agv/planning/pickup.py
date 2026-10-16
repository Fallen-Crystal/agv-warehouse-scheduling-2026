"""比较同一货架的合法相邻停靠格，选择完整可行的取送返回路线。"""


def plan_task(
    scenario,
    router,
    job,
    vehicle,
    position,
    start,
    vertices,
    edges,
    service_blocked=None,
    *,
    selected_pickup=None,
):
    candidates = scenario.pickup_candidates(job)
    if selected_pickup is not None:
        if selected_pickup not in candidates:
            raise ValueError("Selected pickup is not a legal candidate")
        candidates = [selected_pickup]
    successes = []
    attempts = []
    for point in candidates:
        path = [position]
        record = dict(
            vehicle=vehicle,
            task_id=job.id,
            assigned_at=start,
            pickup_point=point,
            shelf=job.shelf,
            candidate_count=len(candidates),
        )
        failed = None
        legs = [
            ("pickup", point, job.pickup_service),
            ("delivery", job.delivery, job.delivery_service),
            ("return", scenario.homes[vehicle], 0),
        ]
        for name, goal, service in legs:
            leg = router.leg(
                path[-1],
                goal,
                start + len(path) - 1,
                vehicle,
                vertices,
                edges,
                service,
                service_blocked=service_blocked if name == "pickup" else None,
                delivery_station=job.delivery if name == "delivery" else None,
            )
            if leg is None:
                failed = name
                break
            path.extend(leg[1:])
            record[name + "_end"] = start + len(path) - 1
            record[name + "_arrival"] = record[name + "_end"] - service
        # A terminal delivery must be exited immediately. The earliest delivery
        # can have a blocked exit even when a slightly later delivery is valid.
        # Bounded retries preserve a clear computational budget; not completeness.
        if failed == "return" and scenario.map_info.get("station_access") == "delivery_only":
            prefix = path[: record["pickup_end"] - start + 1]
            arrival = record["delivery_arrival"]
            for _ in range(8):
                leg = router.leg(
                    prefix[-1],
                    job.delivery,
                    record["pickup_end"],
                    vehicle,
                    vertices,
                    edges,
                    job.delivery_service,
                    delivery_station=job.delivery,
                    not_before=arrival + 1,
                )
                if leg is None:
                    break
                arrival = record["pickup_end"] + len(leg) - 1 - job.delivery_service
                delivery_end = arrival + job.delivery_service
                back = router.leg(
                    job.delivery, scenario.homes[vehicle], delivery_end, vehicle, vertices, edges
                )
                if back is not None:
                    path = prefix + leg[1:] + back[1:]
                    record.update(
                        delivery_arrival=arrival,
                        delivery_end=delivery_end,
                        return_end=start + len(path) - 1,
                        return_arrival=start + len(path) - 1,
                    )
                    record["delivery_exit_retries"] = _ + 1
                    failed = None
                    break
        attempts.append(dict(pickup_point=point, failed_leg=failed))
        if failed is None:
            score = (
                record["delivery_end"],
                record["return_end"],
                sum(a != b for a, b in zip(path, path[1:])),
                point,
            )
            successes.append((score, path, record))
    if not successes:
        failed = max(
            (a["failed_leg"] for a in attempts),
            key=lambda leg: ("pickup", "delivery", "return").index(leg),
        )
        return None, None, failed, attempts
    _, path, record = min(successes, key=lambda item: item[0])
    record["feasible_candidate_count"] = len(successes)
    return path, record, None, attempts
