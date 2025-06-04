

import os
import logging
import threading
import pprint
from concurrent.futures.thread import ThreadPoolExecutor
from concurrent.futures.process import ProcessPoolExecutor

from curio.traps import _future_wait
from curio.workers import run_in_thread, run_in_process, ThreadWorker, WorkerPool, ProcessWorker

from sweepea.kernel import PeaAMQP

from .common import OliveAppConfig, OliveTaskMessage
from olive.workers import import_and_run

logger = logging.getLogger(__file__)


class OliveOly(PeaAMQP):
    logging_prefix = "OliveOly=> "

    def __init__(self, config: OliveAppConfig):
        super(OliveOly, self).__init__(config.amqp_config.url)
        self.config = config
        self.worker_config = config.worker_config
        self.amqp_config = config.amqp_config
        self._shutdown_funcs = []
        self._executor = None
        self.submit_to_pool = None
        if self.worker_config.process_worker:
            if self.worker_config.curio_pool:
                self.process_pool = WorkerPool(ProcessWorker, self.worker_config.num_workers)
                self.submit_to_pool = run_in_process
                self._call_at_shutdown(self.process_pool.shutdown)
            else:
                self._executor = ProcessPoolExecutor(self.worker_config.num_workers)
        else:
            if self.worker_config.curio_pool:
                self.thread_pool = WorkerPool(ThreadWorker, self.worker_config.num_workers)
                self.submit_to_pool = run_in_thread
                self._call_at_shutdown(self.thread_pool.shutdown)
            else:
                self._executor = ThreadPoolExecutor(self.worker_config.num_workers)
        config_str = pprint.pformat(config.to_dict(), indent=4)
        self.log_info(f"\n{config_str}")
        self.log_info(f"executor: {self._executor}")
        self.log_info(f"submit_to_pool: {self.submit_to_pool}")
        self.log_info(f"pid: {os.getpid()}, thread id: {threading.get_ident()}")
        self.files_sems = {}
        return

    async def init_app(self):
        if self.amqp_config.qos > 0:
            await self.setup_qos(self.amqp_config.qos, global_qos=self.amqp_config.global_qos)
        x_name = self.amqp_config.exchange_name
        q_name = self.amqp_config.queue_name
        routing_key = self.amqp_config.routing_key
        await self.declare_x(x_name, "direct")
        await self.declare_q(q_name)
        await self.bind_x_q(x_name, q_name, routing_key)
        await self.consume_queue(q_name)
        return

    def setup_app(self):
        self.trap_spawn(self.init_app(), daemon=True)
        return

    async def task_await(self, msg, delivery_tag):
        self.log_debug(f"submit and run {msg.tid}")
        try:
            if self._executor:
                fn = self._executor.submit(import_and_run, msg.func, *msg.args, **msg.kwargs)
                ret = await _future_wait(fn)
            else:
                ret = await self.submit_to_pool(import_and_run, msg.func, *msg.args, **msg.kwargs)
            self.log_debug(f"{msg.tid} done, ret {ret}")
        finally:
            self.log_debug(f"ack delivery_tag {delivery_tag}")
            self.ack(delivery_tag)
        return

    def msg_received(self, _unused_channel, basic_deliver, properties, body):
        # submit
        self.log_debug(f"Message Received from {basic_deliver.delivery_tag}: \n{properties.app_id}\n{body}")
        msg = OliveTaskMessage.from_str(body)
        logger.debug(msg)
        self.trap_spawn(self.task_await(msg, basic_deliver.delivery_tag), daemon=True)
        return



def main():
    return


if __name__ == "__main__":
    main()
