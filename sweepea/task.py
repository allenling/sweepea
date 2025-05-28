

import uuid
from enum import Enum

from curio.task import Task as CTask


class TaskState(Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    TERMINATED = "TERMINATED"


class Task(CTask):

    def __init__(self, *args, **kwargs):
        super(Task, self).__init__(*args, **kwargs)
        self.id = str(uuid.uuid4())
        return

    def set_waiting(self):
        self.state = TaskState.WAITING
        return

    def set_ready(self):
        self.state = TaskState.READY
        return

    def set_running(self):
        self.state = TaskState.RUNNING
        return

    def set_terminated(self, ret=None, exc=None):
        self.state = TaskState.TERMINATED
        self.terminated = True
        self.timeout = None
        if exc:
            self.exception = exc
        else:
            self.result = ret
        return


def main():
    return


if __name__ == "__main__":
    main()
