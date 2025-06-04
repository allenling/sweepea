

import dataclasses
from enum import Enum

from jeep.dataclass_conf import ConfigAbs
from jeep.common_utils import get_uuid4_str


class WorkerType(Enum):
    thread = "thread"
    process = "process"

    def __deepcopy__(self, memo):
        # https://stackoverflow.com/a/64602943
        return self.value


class PoolImp(Enum):
    curio = "curio"
    concurrent = "concurrent"

    def __deepcopy__(self, memo):
        return self.value


@dataclasses.dataclass
class WorkerConfig(ConfigAbs):
    env_prefix = "worker"
    num_workers: int = 20
    worker_type: WorkerType = WorkerType.thread
    pool_imp: PoolImp = PoolImp.curio

    def __post_init__(self):
        if isinstance(self.worker_type, (int, str)):
            self.worker_type = WorkerType(self.worker_type)
        if isinstance(self.pool_imp, (int, str)):
            self.pool_imp = PoolImp(self.pool_imp)
        return

    @property
    def process_worker(self):
        return self.worker_type == WorkerType.process

    @property
    def curio_pool(self):
        return self.pool_imp == PoolImp.curio


@dataclasses.dataclass
class AMQPConfig(ConfigAbs):
    env_prefix = "amqp"

    url: str = "amqp://guest:guest@localhost:5672/%2F"
    exchange_name: str = "Olive.x"
    queue_name: str = "Olive.q"
    routing_key: str = "Olive.k"
    qos: int = 80
    global_qos: bool = True


@dataclasses.dataclass
class OliveAppConfig(ConfigAbs):
    env_prefix = "olive"

    amqp_config: AMQPConfig = dataclasses.field(default_factory=lambda: AMQPConfig())
    worker_config: WorkerConfig = dataclasses.field(default_factory=lambda: WorkerConfig())
    #


@dataclasses.dataclass
class OliveTaskMessage(ConfigAbs):
    func: str  # imported path
    args: list = dataclasses.field(default_factory=list)
    kwargs: dict = dataclasses.field(default_factory=dict)
    tid: str = dataclasses.field(default_factory=get_uuid4_str)  # task id
    timeout: float = -1
    resp_exchange: str = None
    resp_routing_key: str = None


def main():
    x = OliveAppConfig()
    q = x.to_dict()
    print(q)
    a = OliveAppConfig.from_dict(q)
    print(a)
    print(a.worker_config)
    print(a.worker_config.process_worker)
    return


if __name__ == "__main__":
    main()
