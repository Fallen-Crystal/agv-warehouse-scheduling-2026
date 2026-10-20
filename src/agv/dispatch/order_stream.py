"""Historical adapters to the publisher-owned order lifecycle."""


def initialize(env, manual=False):
    env.initialize_orders(manual)


def publish(env):
    return env.orders.publish(env.time)


def close(env):
    return env.close_order_stream()


def final_return_ready(env):
    return env.final_return_ready
