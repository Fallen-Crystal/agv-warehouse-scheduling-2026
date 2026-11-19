"""只依赖 NumPy 的双动作 DQN；检查点包含完整的训练续跑状态。"""

import json
from pathlib import Path

import numpy as np


class _ReplayBuffer:
    """固定容量的环形经验池，未使用槽初始化以便安全保存。"""

    def __init__(self, capacity, state_dim):
        self.states = np.zeros((capacity, state_dim), dtype=np.float64)
        self.next_states = np.zeros_like(self.states)
        self.actions = np.zeros(capacity, dtype=np.int64)
        self.rewards = np.zeros(capacity, dtype=np.float64)
        self.dones = np.zeros(capacity, dtype=np.bool_)
        self.position = 0
        self.size = 0

    def __len__(self):
        return self.size

    def append(self, state, action, reward, next_state, done):
        i = self.position
        self.states[i] = state
        self.actions[i] = action
        self.rewards[i] = reward
        self.next_states[i] = next_state
        self.dones[i] = done
        self.position = (i + 1) % len(self.actions)
        self.size = min(self.size + 1, len(self.actions))


class DQNAgent:
    """两层全连接 Q 网络（ReLU 隐藏层、两个线性输出）。

    select(training=False) 只做贪心推断，不修改网络、经验池或随机数状态。
    learn() 在经验不足时返回 None，否则返回更新前的批次平均 Huber 损失。
    """

    _PARAMETERS = ("w1", "b1", "w2", "b2")

    def __init__(self, seed=0, state_dim=10, hidden=32, batch_size=32,
                 capacity=10000, learning_rate=0.001, gamma=1.0,
                 target_interval=100, warmup=64, epsilon=0.2,
                 double_dqn=False, output_scale=1.0):
        for name, value in (("state_dim", state_dim), ("hidden", hidden),
                            ("batch_size", batch_size), ("capacity", capacity),
                            ("target_interval", target_interval)):
            if not isinstance(value, (int, np.integer)) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(warmup, (int, np.integer)) or warmup < 0:
            raise ValueError("warmup must be a nonnegative integer")
        if capacity < max(batch_size, warmup):
            raise ValueError("capacity must be at least batch_size and warmup")
        if not np.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError("learning_rate must be finite and positive")
        if not np.isfinite(gamma) or not 0 <= gamma <= 1:
            raise ValueError("gamma must lie in [0, 1]")
        if not np.isfinite(epsilon) or not 0 <= epsilon <= 1:
            raise ValueError("epsilon must lie in [0, 1]")
        if not isinstance(double_dqn, (bool, np.bool_)):
            raise ValueError("double_dqn must be boolean")
        if not np.isfinite(output_scale) or output_scale <= 0:
            raise ValueError("output_scale must be finite and positive")
        self.double_dqn = bool(double_dqn)
        self.output_scale = float(output_scale)
        self.state_dim = int(state_dim)
        self.hidden = int(hidden)
        self.batch_size = int(batch_size)
        self.capacity = int(capacity)
        self.learning_rate = float(learning_rate)
        self.gamma = float(gamma)
        self.target_interval = int(target_interval)
        self.warmup = int(warmup)
        self.epsilon = float(epsilon)
        self.rng = np.random.default_rng(seed)
        # He 初始化适配 ReLU；偏置为零，全部计算使用 float64。
        self.online = {
            "w1": self.rng.normal(0, np.sqrt(2 / state_dim), (state_dim, hidden)),
            "b1": np.zeros(hidden),
            # 仅缩小输出权重，隐藏层及随机抽样顺序保持兼容；旧默认不变。
            "w2": self.rng.normal(0, np.sqrt(2 / hidden), (hidden, 2)) * self.output_scale,
            "b2": np.zeros(2),
        }
        self.target = {k: v.copy() for k, v in self.online.items()}
        self.adam_m = {k: np.zeros_like(v) for k, v in self.online.items()}
        self.adam_v = {k: np.zeros_like(v) for k, v in self.online.items()}
        self.train_steps = 0
        self.replay = _ReplayBuffer(capacity, state_dim)

    @property
    def replay_size(self):
        return len(self.replay)

    def _state(self, state):
        array = np.asarray(state, dtype=np.float64)
        if array.shape != (self.state_dim,) or not np.all(np.isfinite(array)):
            raise ValueError(f"state must be finite with shape ({self.state_dim},)")
        return array

    @staticmethod
    def _forward(states, weights):
        z = states @ weights["w1"] + weights["b1"]
        h = np.maximum(z, 0)
        return h @ weights["w2"] + weights["b2"], z, h

    def select(self, state, training=True):
        state = self._state(state)
        # 推断分支在任何随机调用之前退出，平局由 argmax 固定选择动作 0。
        if training and self.rng.random() < self.epsilon:
            return int(self.rng.integers(2))
        q, _, _ = self._forward(state, self.online)
        return int(np.argmax(q))

    def remember(self, state, action, reward, next_state, done):
        state = self._state(state)
        next_state = self._state(next_state)
        if not isinstance(action, (int, np.integer)) or action not in (0, 1):
            raise ValueError("action must be integer 0 or 1")
        reward = float(reward)
        if not np.isfinite(reward):
            raise ValueError("reward must be finite")
        self.replay.append(state, action, reward, next_state, bool(done))

    def _bellman_targets(self, rewards, next_states, dones):
        next_q, _, _ = self._forward(next_states, self.target)
        if self.double_dqn:
            # Double DQN：在线网络选动作，目标网络只评价该动作，降低max自举偏差。
            online_q, _, _ = self._forward(next_states, self.online)
            actions = np.argmax(online_q, axis=1)
            next_values = next_q[np.arange(len(actions)), actions]
        else:
            # 保留历史DQN默认行为，旧检查点加载后仍由目标网络取最大值。
            next_values = np.max(next_q, axis=1)
        # 两种模式均屏蔽终止状态的未来价值；目标不参与梯度计算。
        return rewards + self.gamma * np.where(dones, 0.0, next_values)

    def learn(self):
        if len(self.replay) < max(self.warmup, self.batch_size):
            return None
        # 无放回均匀抽样；随机源与探索共用并完整保存，支持精确续跑。
        indices = self.rng.choice(len(self.replay), self.batch_size, replace=False)
        states = self.replay.states[indices]
        actions = self.replay.actions[indices]
        targets = self._bellman_targets(self.replay.rewards[indices],
                                        self.replay.next_states[indices],
                                        self.replay.dones[indices])
        q, z, h = self._forward(states, self.online)
        rows = np.arange(self.batch_size)
        error = q[rows, actions] - targets
        absolute = np.abs(error)
        loss = float(np.mean(np.where(absolute <= 1, 0.5 * error ** 2,
                                      absolute - 0.5)))
        # Huber 导数只作用于实际执行的动作，另一输出的梯度保持为零。
        dq = np.zeros_like(q)
        dq[rows, actions] = np.clip(error, -1, 1) / self.batch_size
        dh = (dq @ self.online["w2"].T) * (z > 0)
        gradients = {"w2": h.T @ dq, "b2": dq.sum(axis=0),
                     "w1": states.T @ dh, "b1": dh.sum(axis=0)}
        # 全局 L2 梯度裁剪，避免异常样本引起过大的更新。
        norm = np.sqrt(sum(np.sum(g * g) for g in gradients.values()))
        scale = min(1.0, 10.0 / (norm + 1e-12))
        self.train_steps += 1
        for key in self._PARAMETERS:
            g = gradients[key] * scale
            self.adam_m[key] *= 0.9
            self.adam_m[key] += 0.1 * g
            self.adam_v[key] *= 0.999
            self.adam_v[key] += 0.001 * g * g
            m_hat = self.adam_m[key] / (1 - 0.9 ** self.train_steps)
            v_hat = self.adam_v[key] / (1 - 0.999 ** self.train_steps)
            self.online[key] -= self.learning_rate * m_hat / (np.sqrt(v_hat) + 1e-8)
        if self.train_steps % self.target_interval == 0:
            for key in self._PARAMETERS:
                self.target[key][...] = self.online[key]
        return loss

    def save(self, path):
        """保存完整 npz；不自动追加扩展名，不依赖 pickle。"""
        config = {k: getattr(self, k) for k in (
            "state_dim", "hidden", "batch_size", "capacity", "learning_rate",
            "gamma", "target_interval", "warmup", "epsilon", "double_dqn", "output_scale")}
        metadata = {"version": 1, "config": config, "train_steps": self.train_steps,
                    "rng": self.rng.bit_generator.state,
                    "replay_position": self.replay.position,
                    "replay_size": len(self.replay)}
        arrays = {"metadata": np.array(json.dumps(metadata))}
        for group in ("online", "target", "adam_m", "adam_v"):
            arrays.update({f"{group}_{k}": v for k, v in getattr(self, group).items()})
        for key in ("states", "next_states", "actions", "rewards", "dones"):
            arrays[f"replay_{key}"] = getattr(self.replay, key)
        with Path(path).open("wb") as stream:
            np.savez_compressed(stream, **arrays)

    @classmethod
    def load(cls, path):
        """恢复网络、Adam 时刻/动量、经验池与随机源，下一步训练可精确复现。"""
        with np.load(path, allow_pickle=False) as data:
            meta = json.loads(str(data["metadata"].item()))
            if meta["version"] != 1:
                raise ValueError("unsupported DQN checkpoint version")
            # 旧v1配置没有新增字段，构造默认False/1.0保持原算法与初始化语义。
            agent = cls(**meta["config"])
            for group in ("online", "target", "adam_m", "adam_v"):
                for key in cls._PARAMETERS:
                    expected = getattr(agent, group)[key]
                    value = data[f"{group}_{key}"]
                    if value.shape != expected.shape:
                        raise ValueError("invalid checkpoint parameter shape")
                    expected[...] = value
            for key in ("states", "next_states", "actions", "rewards", "dones"):
                getattr(agent.replay, key)[...] = data[f"replay_{key}"]
            agent.replay.position = int(meta["replay_position"])
            agent.replay.size = int(meta["replay_size"])
            agent.train_steps = int(meta["train_steps"])
            agent.rng.bit_generator.state = meta["rng"]
        return agent
