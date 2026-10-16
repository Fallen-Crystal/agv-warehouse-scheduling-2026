"""Publisher-owned close events; never infer completion inside an online policy."""


def initialize(env, manual=False):
    env._released_jobs = {}
    env._stream_closed = False
    env._stream_closed_at = None
    env._auto_close_at = (
        None
        if manual
        else (
            env._scenario.order_stream_end
            if env._scenario.order_stream_end is not None
            else max((j.release for j in env._jobs.values()), default=0)
        )
    )
    publish(env)


def publish(env):
    env._released_jobs.update((j.id, j) for j in env._jobs.values() if j.release <= env.time)
    if not env._stream_closed and env._auto_close_at is not None and env.time >= env._auto_close_at:
        close(env)


def close(env):
    if env._stream_closed:
        return
    if any(j.release > env.time for j in env._jobs.values()):
        raise ValueError("Cannot close before scheduled orders are published")
    declared = env._scenario.order_stream_end
    if declared is not None and declared != env.time:
        raise ValueError("Close event must match declared stream end")
    env._stream_closed = True
    env._stream_closed_at = env.time


def final_return_ready(env):
    return (
        env._stream_closed
        and all(j in env._assigned for j in env._released_jobs)
        and all(r is None for r in env._active)
    )
