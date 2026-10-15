"""比较同一货架的合法相邻停靠格，选择完整可行的取送返回路线。"""


def plan_task(
    scenario, router, job, vehicle, position, start, vertices, edges, service_blocked=None
):
    candidates = scenario.pickup_candidates(job)
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
        for name, goal, service in [
            ("pickup", point, job.pickup_service),
            ("delivery", job.delivery, job.delivery_service),
            ("return", scenario.homes[vehicle], 0),
        ]:
            leg = router.leg(
                path[-1],
                goal,
                start + len(path) - 1,
                vehicle,
                vertices,
                edges,
                service,
                service_blocked=service_blocked if name == "pickup" else None,
            )
            if leg is None:
                failed = name
                break
            path.extend(leg[1:])
            record[name + "_end"] = start + len(path) - 1
            record[name + "_arrival"] = record[name + "_end"] - service
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
