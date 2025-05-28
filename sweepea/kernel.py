


import logging
import errno
import functools
import time
from collections import deque
from concurrent.futures import Future
import selectors

import pika
import pika.compat
from pika.adapters.select_connection import PollEvents
from pika.adapters.select_connection import IOLoop

import curio
from curio.errors import TaskTimeout
from curio.traps import _future_wait as await_future
from curio.workers import _FutureLess

from .task import Task
from .sleepq_timer import SleeqpTimer
from .selector_storage import PeaSelectorStorage
from .exceptions import TaskNotFoundExc

logger = logging.getLogger("sweepea-kernel")


class PikaAsync:
    """
    https://github.com/pika/pika/blob/main/examples/asynchronous_consumer_example.py
    """
    logging_prefix = "!@$PikaAsync=> "


    def __init__(self, amqp_url):
        self.amqp_url = amqp_url
        self._connection = None
        self._channel = None
        self.closing = False
        self._consumer_tags = set()
        return

    def _prefix_msg(self, msg):
        return f"{self.logging_prefix}{msg}"

    def log_info(self, msg, *args, **kwargs):
        logger.info(self._prefix_msg(msg), *args, **kwargs)
        return

    def log_debug(self, msg, *args, **kwargs):
        logger.debug(self._prefix_msg(msg), *args, **kwargs)
        return

    def log_warning(self, msg, *args, **kwargs):
        logger.warning(self._prefix_msg(msg), *args, **kwargs)
        return

    def log_error(self, msg, *args, **kwargs):
        logger.error(self._prefix_msg(msg), *args, **kwargs)
        return

    def connect(self):
        ioloop = IOLoop()
        ioloop._timer = SleeqpTimer()
        self._connection = pika.SelectConnection(parameters=pika.URLParameters(self.amqp_url),
                                                 on_open_callback=self.on_connection_open,
                                                 on_open_error_callback=self.on_connection_open_error,
                                                 on_close_callback=self.on_connection_closed,
                                                 custom_ioloop=ioloop,
                                                 )
        return

    def on_connection_open(self, _unused_connection):
        self.log_debug("Connection opened")
        self._connection.channel(on_open_callback=self.on_channel_open)
        return

    def on_connection_open_error(self, _unused_connection, err):
        self.log_error("Connection open failed: {err}")
        exit(-1)
        return

    def on_connection_closed(self, _unused_connection, reason):
        self.log_debug(f"connection closed, reason {reason}, stop the loop!")
        self._channel = None
        self._connection.ioloop.stop()
        return

    def on_channel_open(self, channel):
        logger.debug('Channel opened')
        self._channel = channel
        self._channel.add_on_close_callback(self.on_channel_closed)
        # setup your app
        self._on_channel_open()
        return

    def _on_channel_open(self):
        # after the channel established, do your things.
        return

    def on_channel_closed(self, channel, reason):
        self.log_debug(f"Channel {channel} was closed: {reason}")
        self.close_connection()
        return

    def close_connection(self):
        if self._connection.is_closing or self._connection.is_closed:
            self.log_debug(f"close_connection return, {self._connection.is_closing},{self._connection.is_closed}")
            return
        self.log_debug("closing connection!")
        self._connection.close()
        return

    def on_cancelok(self, frame, userdata):
        self.log_debug(f"RabbitMQ acknowledged the cancellation of the consumer: {userdata}")
        self._consumer_tags.remove(userdata)
        if self.closing and not self._consumer_tags:
            self._channel.close()
        return

    def run(self):
        self._connection.ioloop.start()
        return

    def close(self):
        self.closing = True
        # cancel all consumers, then close.
        if self._channel:
            self.log_info(f"_consumer_tags {self._consumer_tags}")
            if not self._consumer_tags:
                self._channel.close()
                return
            for ctag in self._consumer_tags:
                cb = functools.partial(self.on_cancelok, userdata=ctag)
                self._channel.basic_cancel(ctag, cb)
        return


class PeaPod(PikaAsync):

    logging_prefix = "!@$PeaKernel=> "

    def __init__(self, amqp_url):
        super(PeaPod, self).__init__(amqp_url)
        self._wake_queue = deque()
        self._rdy_queue = deque()
        self._kr_sock = None
        self._kw_sock = None
        self.current_task = None
        self._tasks = {}
        self._shutdown_funcs = []
        self._io_storage = PeaSelectorStorage()
        return

    def setup_app(self):
        # do your thing here.
        return

    def _call_at_shutdown(self, func):
        self._shutdown_funcs.append(func)
        return

    def wake_up_kernel(self):
        self._kw_sock.send(b'\x00')
        return

    def _on_channel_open(self):
        # register our own fds for executing tasks.
        # the pair of sockets must be generated from ioloop.
        # self.r_interrupt and self.w_interrupt are the equivalents of notify_sock and wait_sock in Curio.
        self._kr_sock, self._kw_sock = self._connection.ioloop._poller._get_interrupt_pair()
        self._connection.ioloop.add_handler(self._kr_sock.fileno(), self.kernel_run, PollEvents.READ)
        self.running = True
        self.setup_app()
        return

    def get_poll_evt(self, evt):
        return PollEvents.READ if evt == selectors.EVENT_READ else PollEvents.WRITE

    def get_selectors_evt(self, evt):
        return selectors.EVENT_READ if evt == PollEvents.READ else selectors.EVENT_WRITE

    def io_handler(self, fileno, pevent):
        # read and write events share the same callback here.
        # so get key from self._io_storage in order to reschdule the task.
        key = self._io_storage.get_key_from_fileno(fileno)
        mask = self.get_selectors_evt(pevent)
        emask, (rtask, wtask) = key.events, key.data

        if mask & selectors.EVENT_READ:
            # there's a chance that the task may continue to listen on the same fd for the same event.
            rtask._last_io = (key.fileobj, selectors.EVENT_READ)
            self.rescdule_task(rtask)
            emask &= ~selectors.EVENT_READ
            pevent &= ~PollEvents.READ

        if mask & selectors.EVENT_WRITE:
            # there's a chance that the task may continue to listen on the same fd for the same event.
            wtask._last_io = (key.fileobj, selectors.EVENT_WRITE)
            self.rescdule_task(rtask)
            emask &= ~selectors.EVENT_WRITE
            pevent &= ~PollEvents.WRITE
        self.kernel_run(None, None)
        # # the event loop would keep invoking this function until you read data in the buffer.
        # # so we have to update_handler to remove the triggered event.
        # # but since reading data happens in the kernel_run, so we actually can not retain the last_io
        # # when a task keeps waiting on the same fd.
        # if pevent:
        #     self._io_storage.modify(key.fileobj, emask, (rtask, wtask))
        #     self._connection.ioloop.update_handler(fileno, pevent)
        # else:
        #     self._io_storage.unregister(key.fileobj)
        #     self._connection.ioloop.remove_handler(fileno)
        return

    def register_event(self, fileobj, event, task):
        pevt = self.get_poll_evt(event)
        try:
            key = self._io_storage.get_key(fileobj)
            mask, (rtask, wtask) = key.events, key.data
            if event == selectors.EVENT_READ and rtask:
                raise curio.ReadResourceBusy(f"Multiple tasks can't wait to read on the same file descriptor {fileobj}")
            if event == selectors.EVENT_READ and wtask:
                raise curio.WriteResourceBusy(f"Multiple tasks can't wait to write on the same file descriptor {fileobj}")
            pmask = self.get_poll_evt(mask)
            self._io_storage.modify(fileobj, mask | event, (task, wtask) if event == selectors.EVENT_READ else (rtask, task))
            self._connection.ioloop.update_handler(fileobj.fileno(), pmask | pevt)
        except KeyError:
            # there might be two different task waiting on the same fd but for different io events.
            # so we have to differentiate the read and the write task.
            self._io_storage.register(fileobj, event, (task, None) if event == selectors.EVENT_READ else (None, task))
            self._connection.ioloop.add_handler(fileobj.fileno(), self.io_handler, pevt)
        self.current_task._last_io = (fileobj, event)
        return

    def unregister_event(self, fileobj, event):
        key = self._io_storage.get_key(fileobj)
        mask, (rtask, wtask) = key.events, key.data
        mask &= ~event
        pmask = self.get_poll_evt(mask)
        pevt = self.get_poll_evt(event)
        pmask &= ~pevt
        if not mask:
            self._io_storage.unregister(fileobj)
            self._connection.ioloop.remove_handler(fileobj.fileno())
        else:
            if event == selectors.EVENT_READ:
                data = (None, wtask)
                rtask._last_io = None
            else:
                data = (rtask, None)
                wtask._last_io = None
            self._io_storage.modify(fileobj, mask, data)
            self._connection.ioloop.update_handler(fileobj.fileno(), pmask)
        return

    def trap_io(self, fileobj, event, state):
        if self.check_cancellation():
            return
        if self.current_task._last_io != (fileobj, event):
            if self.current_task._last_io:
                self.unregister_event(*self.current_task._last_io)
            try:
                self.register_event(fileobj, event, self.current_task)
            except Exception as e:
                self.current_task._trap_result = e
                return
        # for avoding alternate registration and unregistration.
        self.current_task._last_io = None
        self.suspend_task(lambda: self.unregister_event(fileobj, event))
        return

    def trap_io_release(self, fileobj):
        if self.current_task._last_io:
            self.unregister_event(*self.current_task._last_io)
            self.current_task._last_io = None
        self.current_task._trap_result = None
        return

    def cb_and_rdy(self, task):
        self.rescdule_task(task)
        self.wake_up_kernel()
        return

    # Check if task has pending cancellation
    def check_cancellation(self):
        if self.current_task.allow_cancel and self.current_task.cancel_pending:
            self.current_task._trap_result = self.current_task.cancel_pending
            self.current_task.cancel_pending = None
            return True
        else:
            return False

    def suspend_task(self, cancel_func=None):
        self.current_task.set_waiting()
        self.current_task.cancel_func = cancel_func
        self.log_debug(f"suspend {self.current_task} ~~")
        if self.current_task._last_io:
            self.unregister_event(*current._last_io)
            self.current_task._last_io = None
        self.current_task = None
        return

    def rescdule_task(self, task):
        if self.closing:
            return
        self.log_debug(f"reschdule task {task}")
        self._rdy_queue.append(task)
        task.set_ready()
        task.cancel_func = None
        return

    def new_task(self, coro):
        task = Task(coro)
        self._tasks[task.id] = task
        self.rescdule_task(task)
        return task

    def trap_spawn(self, coro, daemon=False):
        task = self.new_task(coro)
        task.daemon = daemon
        if self.current_task:
            # the current_task asked for a task spawn, so the task would be assigned as the result to that trap.
            # and the kernel is now iterating the rdy_queue, no need to awaken the kernel.
            self.current_task._trap_result = task
        else:
            # being called in some sync function, awaken the coroutine kernel_run manually.
            self.wake_up_kernel()
        return

    # Return the current value of the kernel clock
    def trap_clock(self):
        self.current_task._trap_result = time.monotonic()
        return

    def trap_sched_wait(self, sched, state):
        self.suspend_task(sched._kernel_suspend(self.current_task))
        return

    def trap_sched_wake(self, sched, n):
        tasks = sched._kernel_wake(n)
        for task in tasks:
            self.cb_and_rdy(task)
        return

    def future_back(self, fut: Future, task: Task):
        self.log_debug(f"fut {fut} for task {task} has finished!")
        self._wake_queue.append((task, fut))
        self.wake_up_kernel()
        return

    def trap_future_wait(self, fut: Future, evt=None):
        if self.check_cancellation():
            return
        self.current_task.future = fut
        cb = functools.partial(self.future_back, task=self.current_task)
        fut.add_done_callback(cb)
        # used in workers.
        if evt:
            evt.set()
        self.suspend_task(lambda task=self.current_task: setattr(task, 'future', fut.cancel() and None))
        return

    def on_awake(self, key, clock):
        task_id, sleep_type = key
        task = self._tasks.get(task_id)
        if task is None or clock != getattr(task, sleep_type):
            raise TaskNotFoundExc(task_id)
        self.log_debug(f"{task} awakes!!")
        setattr(task, sleep_type, None)
        current_time = time.monotonic()
        if sleep_type == 'sleep':
            task._trap_result = current_time
            self.cb_and_rdy(task)

        elif task.allow_cancel and task.cancel_func:
            task.cancel_func()
            task._trap_result = TaskTimeout(current_time)
            self.cb_and_rdy(task)
        else:
            task.cancel_pending = TaskTimeout(current_time)
        return

    def set_timeout(self, clock, sleep_type="timeout"):
        tid = self.current_task.id
        logger.debug(f"set_timeout, {self.current_task}, {sleep_type}, {clock}")
        if clock is None:
            self._connection.ioloop._timer.cancel((tid, sleep_type), getattr(self.current_task, sleep_type))
        else:
            self._connection.ioloop._timer.push((tid, sleep_type), clock, self.on_awake)
        setattr(self.current_task, sleep_type, clock)
        return

    def trap_sleep(self, seconds):
        if self.check_cancellation():
            return
        if seconds <= 0:
            self.rescdule_task(self.current_task)
            self.current_task._trap_result = time.monotonic()
            self.current_task = None
            return
        self.log_debug(f"{self.logging_prefix} {self.current_task} is going to sleep {seconds}s.")
        clock = time.monotonic() + seconds
        sleep_type = "sleep"
        self.set_timeout(clock, sleep_type)
        self.suspend_task(lambda task=self.current_task: (self._connection.ioloop._timer.cancel((task.id, sleep_type)), setattr(task, 'sleep', None)))
        return

    def trap_set_timeout(self, timeout):
        self.log_info(f"trap_set_timeout {timeout} for {self.current_task}")
        old_timeout = self.current_task.timeout
        if timeout is None:
            # If no timeout period is given, leave the current timeout in effect
            pass
        else:
            self.set_timeout(timeout)
            if old_timeout and self.current_task.timeout > old_timeout:
                self.current_task.timeout = old_timeout
        self.current_task._trap_result = old_timeout
        return

    def trap_unset_timeout(self, previous):

        self.current_task._trap_result = now = time.monotonic()
        self.set_timeout(None)
        # why?
        if previous and previous >= 0 and previous < now:
            self.set_timeout(previous)
        else:
            self.set_timeout(previous)
            self.current_task.timeout = previous
            if isinstance(self.current_task.cancel_pending, TaskTimeout):
                self.current_task.cancel_pending = None
        return

    def trap_get_current(self):
        self.current_task._trap_result = self.current_task
        return

    def trap_get_kernel(self):
        self.current_task._trap_result = self
        return

    def kernel_run(self, fileno, events):
        if fileno is not None:
            try:
                self._kr_sock.recv(1000)
            except pika.compat.SOCKET_ERROR as err:
                if err.errno != errno.EAGAIN:
                    raise
        if self.closing:
            self.log_debug(f"we are closing!")
            self.log_debug(f"total tasks: {len(self._tasks)}")
            self.log_debug(f"the length of the rdy_queue: {len(self._rdy_queue)}")
            self.log_debug(f"the length of the wake_queue: {len(self._wake_queue)}")
            # for task in self._rdy_queue:
            #     task.set_terminated("closed")
            self.log_debug(f"unregistering kernel socket pair")
            self._connection.ioloop.remove_handler(self._kr_sock.fileno())
            self.log_debug(f"kernel_run return!")
            return
        while len(self._wake_queue):
            # see details.md
            task, future = self._wake_queue.popleft()
            if future and task.future is not future:
                continue
            task.future = None
            self._rdy_queue.append(task)

        while len(self._rdy_queue):
            task = self._rdy_queue.popleft()
            active = self.current_task = task
            self.current_task.set_running()
            self.log_debug(f"run task {self.current_task}")
            while self.current_task:
                try:
                    trap = self.current_task.send(self.current_task._trap_result)
                    self.log_debug(f"trap {trap}")
                except BaseException as e:
                    for wtask in self.current_task.joining._kernel_wake(len(self.current_task.joining)):
                        self.rescdule_task(wtask)
                    # if any exception has occurred, the task is done.
                    if isinstance(e, StopIteration):
                        self.current_task.set_terminated(e.value)
                        self.log_debug(f"{self.current_task} stopped!")
                    else:
                        # if not isinstance(e, CancelledError):
                        #     self.log_error(f"{task} exception!!!!!!", exc_info=True)
                        self.log_error(f"{task} exception!!!!!!", exc_info=True)
                        self.current_task.set_terminated(exc=e)
                    del self._tasks[self.current_task.id]
                    self.current_task = None
                    break
                self.current_task._trap_result = None
                # we assume that there won't be any exception here.
                getattr(self, trap[0])(*trap[1:])

            # Unregister any prior I/O listening
            if active._last_io:
                self.unregister_event(*active._last_io)
                active._last_io = None
        return

    def shutdown(self):
        self.log_info(f"Shuting down!")
        self.close()
        self.wake_up_kernel()
        # call self.run to run the poll again to wait for the event loop to stop compelely.
        self.run()
        self.log_info(f"run _shutdown_funcs")
        for func in self._shutdown_funcs:
            func()
        self.log_info(f"Gone!")
        return

    def start(self):
        self.connect()
        try:
            self.run()
        except KeyboardInterrupt:
            # you will see that we have to wait for 5 seconds to catch KeyboardInterrupt,
            # because Pika's event loop is running at a default interval of 5 seconds!
            self.log_info(f"KeyboardInterrupt!")
            pass
        self.shutdown()
        return


class PeaAMQP(PeaPod):
    logging_prefix = "!@$PeaAMQP=> "
    # future_cls = Future
    future_cls = _FutureLess

    async def setup_qos(self, prefetch_count, global_qos=False):
        fut = self.future_cls()
        # will the callback run before await_future?
        # nope, because the callback will be called just after the kernel_run function returns, or in the next
        # event loop resumption.
        # that means that we will add done callback to the future in that kernel_run before there's a chance
        # that callback gets called.
        self._channel.basic_qos(prefetch_count=prefetch_count, global_qos=global_qos, callback=fut.set_result)
        await await_future(fut)
        self.log_debug(f"setup_qos done, {prefetch_count}, {global_qos}")
        return

    def ack(self, delivery_tag):
        self.log_debug(f"Acknowledging message {delivery_tag}")
        # no need to trap in await_future because basic_ack is already asynchronous.
        # it's a write event in the event loop.
        self._channel.basic_ack(delivery_tag)
        return

    def nack(self, delivery_tag):
        self.log_debug(f"NAcknowledge_message {delivery_tag}")
        self._channel.basic_nack(delivery_tag, multiple=False, requeue=True)
        return

    async def declare_x(self, x_name, x_type, **x_params):
        fut = self.future_cls()
        self._channel.exchange_declare(exchange=x_name, exchange_type=x_type, callback=fut.set_result, **x_params)
        await await_future(fut)
        self.log_debug(f"declare_x done, {x_name}, {x_type}, {x_params}")
        return

    async def declare_q(self, q_name, **q_params):
        fut = self.future_cls()
        self._channel.queue_declare(queue=q_name, callback=fut.set_result, **q_params)
        await await_future(fut)
        self.log_debug(f"declare_q done, {q_name}, {q_params}")
        return

    async def bind_x_q(self, x_name, q_name, routing_key):
        fut = self.future_cls()
        self._channel.queue_bind(q_name, x_name, routing_key, callback=fut.set_result)
        await await_future(fut)
        self.log_debug(f"bind_q done, {x_name}, {q_name}, {routing_key}")
        return

    async def consume_queue(self, q_name, **params):
        fut = self.future_cls()
        c_tag = self._channel.basic_consume(q_name, on_message_callback=self.msg_received, callback=fut.set_result, **params)
        self._consumer_tags.add(c_tag)
        await await_future(fut)
        self.log_debug(f"consume_queue {q_name} done")
        return

    def msg_received(self, _unused_channel, basic_deliver, properties, body):
        # maybe you want to start an async function when a message arrived.
        self.log_debug(f"Message Received from {basic_deliver.delivery_tag}: \n{properties.app_id}\n{body}")
        self.ack(basic_deliver.delivery_tag)
        return


def main():
    return


if __name__ == "__main__":
    main()
