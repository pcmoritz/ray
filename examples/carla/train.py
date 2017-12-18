import ray
from ray.tune.registry import get_registry, register_env
from ray.rllib import ppo

from env import CarlaEnv

env_name = "carla_env"
register_env(env_name, lambda: CarlaEnv())

ray.init(redirect_output=True)
alg = ppo.PPOAgent(env=env_name, registry=get_registry(), config={"num_workers": 1, "timesteps_per_batch": 2000, "num_sgd_iter": 20, "min_steps_per_task": 100, "sgd_batchsize": 32, "lambda": 0.95, "clip_param": 0.02, "sgd_stepsize": 0.0001, "devices": ["/gpu:0"], "tf_session_args": {"gpu_options": {"allow_growth": True}}})

for i in range(100):
    alg.train()
