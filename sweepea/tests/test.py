
import logging
import time

import curio

from sweepea.kernel import PeaPod, PeaAMQP

from curio import sleep, spawn, timeout_after
from curio.socket import *


amqp_url = "amqp://guest:guest@localhost:5672/%2F"


class TestPod(PeaPod):
    logging_prefix = "!#$TestPod=> "

    async def timeout_chain4(self):
        clock = await curio.clock()
        print(f"first {clock}")
        await timeout_after(7, sleep, 10)
        return

    async def timeout_chain3(self):
        await timeout_after(4, self.timeout_chain4())
        return

    async def timeout_chain2(self):
        await timeout_after(6, self.timeout_chain3())
        return

    async def timeout_chain1(self):
        await timeout_after(5, self.timeout_chain2())
        return

    async def run_in_worker(self):
        s = time.time()
        # await curio.run_in_thread(time.sleep, 5)
        await curio.run_in_process(time.sleep, 5)
        print(time.time() - s)
        return

    async def spawn_tasks(self):
        # t = await spawn(self.timeout_chain1())
        t = await spawn(self.run_in_worker(), daemon=True)
        # await t.join()
        return

    async def echo_client(self, client):
        async with client:
            while True:
                data = await client.recv(10000)
                print(f"get data {data}")
                if not data:
                    break
                await client.sendall(data)
        print('Connection closed')
        return

    async def test_io(self):
        sock = socket(AF_INET, SOCK_STREAM)
        sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 25001))
        sock.listen(5)
        async with sock:
            while True:
                client, addr = await sock.accept()
                print('Connection from', addr)
                await spawn(self.echo_client, client, daemon=True)
        return

    def setup_app(self):
        # self.trap_spawn(self.spawn_tasks(), daemon=True)
        self.trap_spawn(self.test_io(), daemon=True)
        return


def test_kernel():
    tp = TestPod(amqp_url)
    tp.start()
    return


class AMQPTestPod(PeaAMQP):
    logging_prefix = "!@$AMQPTestPod=> "

    async def init_amqp(self):
        await self.setup_qos(10, global_qos=True)
        x_name, q_name, routing_key = "TestPod.x", "TestPod.q", "TestPod.k"
        await self.declare_x(x_name, "direct")
        await self.declare_q(q_name)
        await self.bind_x_q(x_name, q_name, routing_key)
        await self.consume_queue(q_name)
        return

    def setup_app(self):
        self.trap_spawn(self.init_amqp(), daemon=True)
        return


def test_amqp():
    tp = AMQPTestPod(amqp_url)
    tp.start()
    return


def main():
    logging.basicConfig(level=logging.DEBUG,
                        format="[%(asctime)s.%(msecs)03d]%(levelname)s %(process)d_%(thread)d[%(filename)s.%(funcName)s:%(lineno)d] %(message)s",
                        )
    test_kernel()
    # test_amqp()
    return


if __name__ == "__main__":
    main()
