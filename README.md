
# Sweepea

an AMQP asynchronous task queue on the top of Pika's event loop.

at its heart, it is this concurrent scheduling kernel which is "borrowed" from Curio, a prominent and fun python concurrent library.

in order to implement such a scheduling kernel, you need a robust io event loop, and this is exactly what you will find in Pika.

and meanwhile, Pika itself is a RabbitMQ (AMQP 0-9-1) client library for Python.

and by putting all of these together, here we have Sweepea.

# Motivation

the initial goal was to replace Celery and get rid of its complexities.

Celery is one of the most popular task queue applications in the python world, it is fast and has built-in support for different message queues.

and there are hundreds of thousands projects using Celery in support to their business, but it is also famous for its complexities.

we found it very difficult to read the source code and understand the design pattern.

to reduce that mental load in terms of debugging and troubleshooting, we decided to build a lightweight alternative. 

and a simple design for a task queue application would be just send-and-receive.

you have a delivery process called main process waiting on the message queue, and once a message or a task has arrived, that delivery
process will just submit it to one of the workers, and waiting until the task finishes.

and as long as the task is done, the worker will send the result back to the main process, that is the typical workflow. 

and what the main process does is waiting on IO events, and then sending and receiving messages throughout the networking, nothing else. 

obviously, it is an IO intensive task, that really reminded us of concurrent programming.

Python has generators built in to underpin concurrent programming, and it also introduces async/await keywords to make concurrent
programming even simpler and eaiser.

we thought a concurrent scheduling kernel would be a great fit for this listen, receive and run case.

so what we did was to implement the traps of Curio kernel and merge them into Pika's event loop without meddling in the AMQP protocol
details handled by Pika itself.

simply put, it's like now the event loop is equipped with a concurrent kernel while retaining the ability of interacting with RabbitMQ.

and when a message arrives, the kernel will be woken up by the event loop to operate.

```

                              +-------+
      concurrent  <=====>     | event |  <========>  RabbitMQ
         kernel               | loop  |  
                              +-------+

```

# Usage

the `olive` module contains a simple implementation of that celery alternative.

```python

from olive.app import OliveOly
from olive.common import OliveAppConfig


def run():
    # olive/common.py has all configuration key-value pairs in it.
    config = OliveAppConfig.from_env()  # read your own configuration from env.
    # config = OliveAppConfig  # or use the default setting.
    app = OliveOly(config)
    app.start()
    return

```

the application will listen on the exchange `Olive.x` and the queue `Olive.q` with a rounting key `Olive.k`.

run `olive_utils.py` to send a task to the task queue application, and the task will be run in a thread/process worker.


# Implementation details

for more implementation details, please check out `implementation.md`.

