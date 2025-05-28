

import os
import time
import logging

from curio.timequeue import TimeQueue

from pika.adapters.select_connection import _Timer

from .exceptions import TaskNotFoundExc

logger = logging.getLogger(__file__)


class SleeqpTimer(_Timer):

    def __init__(self):
        super(SleeqpTimer, self).__init__()
        self.sleepq = TimeQueue()
        self.cbs = {}
        self.max_select_timeout = None if os.name != 'nt' else 1.0
        return

    def push(self, key, clock, cb):
        self.sleepq.push(key, clock)
        self.cbs[key] = cb
        return

    def cancel(self, key, clock=None):
        self.sleepq.cancel(key, clock)
        return

    def get_remaining_interval(self):
        i = super(SleeqpTimer, self).get_remaining_interval()
        current_time = time.monotonic()
        timeout = self.sleepq.next_deadline(current_time)
        if self.max_select_timeout and (timeout is None or timeout > self.max_select_timeout):
            timeout = self.max_select_timeout
        if i is None and timeout is None:
            return
        if i is not None and timeout is not None:
            return min(timeout, i)
        if i is None:
            return timeout
        return i

    def process_timeouts(self):
        super(SleeqpTimer, self).process_timeouts()
        current_time = time.monotonic()
        for clock, key in self.sleepq.expired(current_time):
            if key not in self.cbs:
                continue
            cb = self.cbs[key]
            try:
                cb(key, clock)
            except TaskNotFoundExc:
                self.cbs.pop(key, None)
        return




def main():
    return


if __name__ == "__main__":
    main()
