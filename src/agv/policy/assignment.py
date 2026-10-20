"""Deterministic rectangular minimum-cost assignment (rows <= columns)."""

from math import isfinite


def minimum_assignment(costs):
    if not costs:
        return []
    n, m = len(costs), len(costs[0])
    if m < n or any(len(row) != m for row in costs):
        raise ValueError("Assignment needs a rectangular matrix with rows <= columns")
    finite = [abs(x) for row in costs for x in row if isfinite(x)]
    big = (max(finite, default=1) + 1) * (n + m + 1) * 100
    a = [[x if isfinite(x) else big for x in row] for row in costs]
    u, v, owner, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        owner[0], column = i, 0
        best, used = [float("inf")] * (m + 1), [False] * (m + 1)
        while True:
            used[column] = True
            row, step, next_column = owner[column], float("inf"), 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                value = a[row - 1][j - 1] - u[row] - v[j]
                if value < best[j]:
                    best[j], way[j] = value, column
                if best[j] < step:
                    step, next_column = best[j], j
            for j in range(m + 1):
                if used[j]:
                    u[owner[j]] += step
                    v[j] -= step
                else:
                    best[j] -= step
            column = next_column
            if not owner[column]:
                break
        while column:
            previous = way[column]
            owner[column] = owner[previous]
            column = previous
    result = [None] * n
    for j in range(1, m + 1):
        if owner[j] and isfinite(costs[owner[j] - 1][j - 1]):
            result[owner[j] - 1] = j - 1
    return result
