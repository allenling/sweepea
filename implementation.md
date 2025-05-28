

# async/await, traps, all APIs.

## the traps

when a task or a program pauses, it must wait on some operation to be done in the future.

it might wait on a socket for messages from a client, it might wait on a thread event to be set by another thread, or whatever other events.

but the truth is that you can not execute those operations yourself, you have to ask the kernel to do that for you.

in technical terms, you are running in the user mode, and requesting IO data is an operation happening in the kernel, so you have to
enter the kernel mode in order to delegate such operation to the kernel.

there are many reasons for that, for a more elegant design, or for better safety, or etc.

but the most important thing is that you have to do something to notify the kernel that there's something you want it to do for you.

in general, you tell the kernel to do something by sending it a trap, or invoking a system call, here we use the term trap and system
call interchangeably, and do not differentiate them.

when the OS/CPU receives a trap, it will transfer control to the kernel and suspend the program and invoke the trap handler, this
is called entering kernel mode.

this is what happened when a program waited to receive data from somewhere or write data to the IO buffer in order to send them out.

the traps are essentially like the lanes to the kernel world.

```
                                trap
       your program(paused)  --------->  kernel
       
                                data
       your program(resume)  <---------  kernel
       
```

## async/await keywords

so how could we emulate such a trap in and resume interaction in Python?

it turns out that it is not as hard as it sounds.

in Python, the only way for a program to pause is via `yield` keyword, and you can use `await` keyword to wait on a coroutine.

put simply, down through an awaits chain, you will find there is a `yield` at the end.

```
async f1
      await -> async f2
                   await -> async f3
                                await -> @coroutine
                                            f4(yield)

```

so basically you can define a couple of `async` functions and await on them one after one, but the last one has to `yield` to pause
the whole invoke chain, and usually the last coroutine has to be a generator-based coroutine decorated by `coroutine` keyword. 

to start a coroutine, just execute `f1().send(None)` to send `None` to it, and actually the `None` or anything you sent will get
passed through and eventually to the last generator-based coroutine.

when a generator pauses, it can yield anything out to the caller, and anyone who injected a value by `send` method to the coroutine
will get the value.

as you can see, the function `f4` is the one actually pauses, it yields to pause.

to resume a coroutine, just send back something to the coroutine, then the last generator-based coroutine will resume, and then the
awaits chain above just resumes, programs run again in an order from the last `yield` to the first `await`.

this means that `f4` will run first, and it might pause again and yield something, and then get resumed again and again.

but when it finishes, the await statement on `f4` in coroutine `f3` will return, and then `f3` carrys on, and then coroutine
`f2` and corountine `f1` proceed.

and calling the `send` method is the way how you start a generator, that is why Python claims that coroutines are generator based,
though it does have a new object type named `coroutine` for functions defined by `async` keyword.

all of those boil down to if you want to pause at certain line of code, just `yield`, or you yield, you pause. 

this is how awaits chains work.

## the kernel and coroutines

by Python's built-in support for pause-resume ability, we can build a mini concurrent scheduling kernel.

```
the kernel                              the coroutine


                        trap1
                     <-------------     await trap1, pause
                     
execute trap1    

                       result
                     -------------->    await trap1, resume
                    
                       trap2
                     <--------------    await trap2, pause
             
execute trap2
                        result
                     ---------------->  await trap2, resume

```

awaiting on trap1 and trap2 is to send the traps to the kernel, as we mentioned, you have to yield trap1 and trap2 at the end.

```
async f1
      await -> async f2
                   await -> async f3
                                await -> yield trap1/trap2
```

so the core of that concurrent kernel would be the function below:

```python

# curio/traps.py

from types import coroutine


@coroutine
def _kernel_trap(*request):
    result = yield request
    if isinstance(result, BaseException):
        raise result
    else:
        return result
```

and a sleep trap looks like

```python

async def _sleep(clock):
    return await _kernel_trap("trap_sleep", clock)
```

as you can see, the system call `_sleep` just yields the trap `trap_sleep`.

```python

def trap_sleep(clock):
    pass

def kernel_run(coro):
    for _ in range(len(ready)):
        current = ready_popleft()
        while current:
            try:
                trap = current.send(current._trap_result)
            except BaseException as e:
                pass
            # trap = trap_sleep, 10.
            # traps is the traps map.
            traps[trap[0]](*trap[1:])
```

the kernel runs when there is at least one ready task in the read_queue, and it just pops the task from the queue, and send the
last trap result to the coroutine to start or resume the task.

when a coroutine pauses and returns a trap, for instance it wants to sleep 10 seconds, and then the kernel gets the trap, or the trap
name, and it knows that the task is going to wait for something, and then the kernel just looks up the trap handler in the traps map
by the name and calls it.

## APIs and implementation.

if we carefully observe, we can notice that acutally the coroutine and the kernel, they are agnostic to each other.

the coroutine just throws out the trap no matter who is executing it, and the kernel just keep running the task, and as soon as it
gets a trap, call the handler.

this kind of decoupling design would be very helpful, and it enables seamless adoption of third party plugins and contribution. 

a practical example of that would be like regarding thread and process worker pool implementation and management, we do not
want to build ourselves.

it will be wiser to adopt some popular worker pool implementation used by many people out here, like the Python standard library
`concurrent`, or the workers built by Curio.

so to incorperate these worker pools into our application, all we have to do just implement requisite traps in your kernel.

it is really like augment your application by just plugging several LEGO bricks, like a jetpack, to your backbound.

a third party plugin or feature can be used in any kernel who has implemented the set of traps, and the kernel can run any task
that integrates the traps.

then traps to the task, they are APIs, user programs just do not care the implementation, and the kernel just calls traps thrown by
anybody.

```
               kernel workflow
               
                    |
                    |
                    | <---- plugin X
                    |
                    | <---- plugin Y
                    |
                    V
                    
```

## the scheduling strategy

the quetsion here is if a task sleeps 10 seconds, will it be resumed exactly 10 seconds later?

suppose that the task gets paused at time x, and must it be awakend exactly at time x+10?

the answer is not really within a scheduling kernel, and it depends on the scheduling strategy.

one of the facts about scheduling is that there is alaway one task that gets executed at a time, the kernel will try to run current task until hits a trap.

a trap might cause the task sleep for a period of time, then there's a chance for next task to run, the kernel pops the next task from
the ready queue to repeat the procedure.

or there's nothing to wait, e.g. the data has already arrived at the hardware, so it is readable now, then the trap's handler returns 
and notifies the kernel that everything is ready, and then the kernel will immediately execute current task again.

as you can imagine, if there's a bunch of tasks ready to run, it is possible that the prior task takes too long before it pauses, and
that might lead to the next task running a bit later than expected.

it is just this very simple serialization scheduling strategy, no task priority, no preemptive support, tasks just get executed one
by one in order.

and there is a variety of different schedulers out there designed for various purposes. 

in Linux, e.g. Deadline scheduler is used for tasks that must finish before a deadline, audio processing and video encoding/decoding
are among the typical use cases, and RT or RealTime is used for short latency-sensitive real-time tasks, and so on.

# timeouts!

let's first take a quick refresher on Python's awaits chain.

all await calls will eventually reach to a `yield` statement, and `f4` will receive the value sent back by the caller.

```
async f1
      await -> async f2
                   await -> async f3
                                await -> @coroutine
                                            f4(yield)

```

and speaking of timeouts, there is also a timeouts chain.

a typical timeous chain is like `f1` expects results from `f2` in a certain acmount of time, and during the run of `f2`, it waits
`f3` to complete for X seconds at most, and then `f3` calls `f4` and will raise an error if `f4` is still running Y seconds
later.

and awaiting on something with a timeout of seconds and sleeping X seconds really can be just summarized as wake me up later.

tell somebody to wake you up after N seconds, and if you are woken, then that indicates that the operation has not returned and
time out!

and if the operation finishes within the timeout, then cancel the wake-up call.

it is really like set the timer, and if the timer rings, then there's a timeout, or you've had something return in time,
and then disable or cancel the timer.

```

def f1():
    set the timer at time X.
    call f2, and wait until a timeout occurs or f2 finishes.
    cancel the timer in case no timeout.

```

and in this case, that one who is going to awaken you is going to be the kernel.

remember traps are the notifications sent to the kernel to ask it to do something for you, so basically here when you are awaiting
on an operation, and you want to put a timeout on that operation, you are telling the kernel that resume the task after N seconds.

and the kernel would just simply put that timer into a heap or priority queue depending on their implementation, and
wake up the corresponding task when there's a timeout.

and asynchronous architecture suits perfectly this timer scenario, thanks to its innate ability of pause and resume.

the timeouts chain would look like

```
async f1
      await -> set timeout, here will yield the name set_timeout to the kernel.
      await -> async f2.
                   await -> set timeout, yield the trap set_timeout.
                   await -> async f3.
                            await -> set timeout, yield the trap set_timeout.
                            await -> async f4, yield the trap trap_io

```

## exceptions propagation

as we can see, we have 3 functions setting up timeout separately, and what are we going to if one of them just hit a timeout?

suppose `f1` set up a timeout of 5 seconds, and `f2`, 6 seconds, and `f3`, 7 seconds.

```

+5 represents that the task would be awakend 5 seconds later from now.

f1(+5), f2(+6), f3(+7)

```

in this case, `f1` would time out first, and get a timeout exception, and then it would make sense to cancel `f2` and `f3`, why?

because the caller just crashed and terminated, there was no need to run all the subtasks anymore.

```

f1(+5)    f2(+6)       f3(+7)
  X       Canceled     Canceled 
```

and what if `f2` set up a timeout of 4 seconds instead.

```

f1(+5), f2(+4), f3(+7)

```

in this case, `f2` would hit a timeout error first, and then we just canceled all the tasks behind it.

and what about the task `f1` that the caller of `f2`?

well, what Curio does would differ slightly from asyncio.

Curio will raise a `TimeoutCancellationError` and propagate it through all the task after `f2`, and raise a `TaskTimeout`
exception at `f2` indicating that it was f2 who had a timeout error, and raise an `UncaughtTimeoutError` and propagate it along
to the head of the chain.

and of course, all exceptions are going to propagate from back to front.

```

suppose we had 5 tasks, f1, f2, f3, f4, f5

f1(+5), f2(+6), f3(+4), f4(+7), f5(+8)

and the exceptions would be

f1(+5)                     f2(+6)        f3(+4)          f4(+7)                        f5(+8)
  --- UncaughtTimeoutError ---         TaskTimeout          -- TimeoutCancellationError -- 

```

actually due to exception chain suppressing(the use of `raise from None` statement), you won't see the full and detailed stack info,
(delete `from None` to show the full stack info), you will see that the first stack traceback block would have a `TaskTimeout`
exception, and the call stack would track from `f5` to `f3`. 

and the second stack traceback block would have an `UncaughtTimeoutError` exception, and you will find f2 and f1 on the call stack.

and asyncio will also raise a cancellation exception for all the task behind f3, but it will just raise a timeout error for
all the task before f3.

```


f1(+5)   f2(+6)      f3(+4)    f4(+7)             f5(+8)
  ------ timeout --------        --- cancellation ---

```


## Curio timeout implementation

Curio uses a class named `TimeQueue` to manage timers.

the idea is that timers inserted into the TimeQueue first time will probably be canceled in the near future. 

this is the important assumptation for a more efficient management on timers.

based on this assumptation, Curio will put the timers into a dict named `far` contains timers that expire far enough from now,
and the threshold for how far is being considered far enough is set to one second by default.

so when someone cancels the timer, we can remove the timer from the `far` dict at `O(1)` complexity. 

and any timer that will expire less than or equal to one seconds from now would be moved into a heaq, which takes `O(logN)` to
push and pop item out of it.

and another quite commonly seen optimization here is that only keep the cloest timeout for the task and discard the others.

and the last one, timeout context manager.

as we see in the diagram, before and after waiting on another coroutine, we have to set up a timer and cancel the timer.

```

def f1():
    set the timer at time X.
    call f2, and wait until a timeout occurs or f2 finishes.
    cancel the timer in case no timeout.

```

and a proper approach would be the use of `with` statement to manage these before and after operations.

and when a `TaskTimeout` exception was being sent to arise, Curio will raise `TimeoutCancellationError` if this was not us that
had timed out.

Curio will store all timeout timestamps in a list of `task._deadlines`.

suppose there were 3 timers, and they would expire at 5, 4 and 7 seconds later respectively, then the deadlines list would be

```
[+5, +4, +7]
```

the timer context manager would be

```python

class _TimeoutAfter(object):

    def __init__(self, clock, ignore=False, timeout_result=None):
        self._clock = clock
        return

    async def __aenter__(self):
        task = await current_task()
        # Clock adjusted to absolute time
        if self._clock is not None:
            self._clock += await _clock()
        # append our clock into the deadlines list.
        self._deadlines = task._deadlines
        self._deadlines.append(self._clock)
        return self
```

and when the second timer expired, a `TaskTimeout(clock)` would be sent into the coroutine, and then the tasks would resume in
reverse order.

and the exception holds the timestamp associated to the timer as it gets sent to the chain.

e.g. when the seond timer has expired, the exception would be initialized as `TaskTimeout(+4)`, and then sent to coroutine.

and to find out which timer has timed out, a straightfoward method is to compare the timestamp in the exception with every one in
the `task._deadlines` list .

```python

async def __aexit__(self, ty, val, tb):
    current_clock = await _unset_timeout(self._prior)
    try:
        if ty in (TaskTimeout, TimeoutCancellationError):
            timeout_clock = val.args[0]
            # Find the outer most deadline that has expired
            for n, deadline in enumerate(self._deadlines):
                if deadline <= timeout_clock:
                    break
            else:
                # No remaining context has expired. An operational error
                raise UncaughtTimeoutError('Uncaught timeout received')

            if n < len(self._deadlines) - 1:
                if ty is TaskTimeout:
                    raise TimeoutCancellationError(val.args[0]).with_traceback(tb) from None
                else:
                    return False
            else:
                # The timeout is us.  Make sure it's a TaskTimeout (unless ignored)
                pass
    finally:
        self._deadlines.pop()
```

and if the timestamp stored in the exception is the last one of the deadlines list, the expired one would be us.

why? remember the chain runs forwards and timestamps get append into the deadlines list in order, and the chain resumes from back to
front.

```
<------------- the order in which tasks resume.
 f1  f2  f3
[+5, +4, +6] 

```

and in the `finally` block, we will pop the last item from the list, this makes sure that the last one in the deadlines list is
always the current timer's timeout timestamp.

and we reach the last item in the deadlines list if and only if we are the smallest one or the cloest clock, because obviously,
if some timer had set up a closer clock than us, we could not expire first and earier than that closer timer.

we hit the `break` statement to go to the next `if` statment to check if the timeout is us.

so suppose we are the one has expired.

```python

async def __aexit__(self, ty, val, tb):
    current_clock = await _unset_timeout(self._prior)

    try:
        if ty in (TaskTimeout, TimeoutCancellationError):
            timeout_clock = val.args[0]

            if n < len(self._deadlines) - 1:
                pass
            else:
                # The timeout is us.  Make sure it's a TaskTimeout (unless ignored)
                self.result = self._timeout_result
                self.expired = True
                if self._ignore:
                    return True
                else:
                    if ty is TimeoutCancellationError:
                        raise TaskTimeout(val.args[0]).with_traceback(tb) from None
                    else:
                        return False
    finally:
        pass
```

if someone just passed over us a `TimeoutCancellationError`, and we must be somewhere in the middle of the chain, re-raise a
`TaskTimeout` exception.

if the exception is not `TimeoutCancellationError`, then we are the earliest clock, and we are happend to be the last coroutine in
the chain, and our clock must be the last one in original the deadlines list that had not popped any one of items.

and then the exception must be `TaskTimeout` sent by kernel, no need to re-raise, and just return `False` to allow the exception to
flow.

and suppose that the timeout is not us, we are now in coroutine `f3`'s `__aexit__` block, then we would stop at the second index of the
deadlines list, because `+4` is the smallest one.

then we break to get past the `UncaughtTimeoutError`, and we know the expired clock is not the last one and is not us, it is someone
before us in the chain, then a `TimeoutCancellationError` would be raised.

```python
            if n < len(self._deadlines) - 1:
                if ty is TaskTimeout:
                    raise TimeoutCancellationError(val.args[0]).with_traceback(tb) from None
                else:
                    # do not re-raise the exception!
                    return False
```

to allow the `TimeoutCancellationError` exception to flow through the chain, Curio just simply returns `False` insead of re-raising
the exception.

and now let's suppose we are reaching `f1` the head of chain.

we know that the `timeout_clock` is not in the deadlines list, then we know that someone behind us expired, the `for` loop would
not hit the break statment.

and we will go to the `for else` block to raise an `UncaughtTimeoutError` exception. 

```python

async def __aexit__(self, ty, val, tb):
    current_clock = await _unset_timeout(self._prior)
    try:
        if ty in (TaskTimeout, TimeoutCancellationError):
            timeout_clock = val.args[0]
            # Find the outer most deadline that has expired
            for n, deadline in enumerate(self._deadlines):
                if deadline <= timeout_clock:
                    break
            else:
                # No remaining context has expired. An operational error
                raise UncaughtTimeoutError('Uncaught timeout received')
    finally:
        self._deadlines.pop()

```

if we reach a timer that is before the expired timer but not on/to its left, say there are one or more timers between the current 
and the expired timer.

```

e.g. we are now at f2.

f1(+5) f2(+6) f3(+8) f4(+4) f5(+10)

```

the exception passed in would not be either `TaskTimeout` or `TimeoutCancellationError`, then we would just go directly to
the `finally` block and do nothing to let the `UncaughtTimeoutError` be propagated all the way along to the head of the chain.

```python

    try:
        if ty in (TaskTimeout, TimeoutCancellationError):
            pass
        elif ty is None:
            # code omitted
            pass
    finally:
        # code omitted
        pass
```

# avoid IO re-registration.

the way how an IO event loop works is you register the fd you want to wait on to the loop along with the IO events, read or write.

and when the fd is avaliable for read or write, then the event loop will wake up from dormancy to tell you which fd event pair is ready.

and next a typeical process would be like you read the data from the fd, and then unregister the fd-event pair from the loop and
register the pair when needed.

but as Curio says

```python

# When a task performs I/O, it registers itself with the underlying
# I/O selector.  When the task is reawakened, it unregisters itself
# and prepares to run.  However, in many network applications, the
# task will perform a small amount of work and then go to sleep on
# exactly the same I/O resource that it was waiting on before. For
# example, a client handling task in a server will often spend most
# of its time waiting for incoming data on a single socket.
#
# Instead of always unregistering the task from the selector, we
# can defer the unregistration process until after the task goes
# back to sleep again.  If it happens to be sleeping on the same
# resource as before, there's no need to unregister it--it will
# still be registered from the last I/O operation.
```

so what Curio does is simply defer the unregistration process until the task would not be performing the same IO operation.

such a modification should give the application a small boost.

but when we tried to implement this feature upon Pika's IO event loop, problems aroes. 

when a coroutine registered a fd to the underlying event loop, we first just assoicated that fd with a callback function, and 
the event loop was expected to call that callback function when the fd became ready.

and then we have to send a byte via a specific socket to run the kernel to execute the task.

```

        event loop ----> callback ---> send the kernel socket something
                                                    |
                   < -------------------------------+
                   
                   ----> kernel, the kernel was awakened by the pool because the socket had become readable
         

```

in the callback, we have to remove the fd event pair out of the event loop, because the event loop will keep invoking the callback
as the fd is constantly readable to the event loop.

to stop such a continuous buzzing noise, you have to read the data, and the fd will become unreadable since the buffer has no data.

remember we are running asynchronously, you can not count on that the kernel will run just followed the callback so that the data
on the buffer will be taken out before the event loop goes and invokes that callback again.

actually since in order to run the kernel, some bytes must be sent through the event loop, then even in the ideal case scenario where
the kernel does run right after the execution of the callback, there'a alaways at least one extra callback invoking.

why? beacuse we go back from the callback to the event loop, there will be two fds that are avaliable, the fd that the task is waiting
on, and the fd of the socket used to communicate the kernel.

so the event loop is going to first run the kernel, and then call the callback one more time.

to get around this IO re-registration problem, instead of going back to the event loop to run the kernel, we just call the kernel
function in that callback function, and that's it.

now we will read the data from the buffer once a fd becomes avaliable and run the coroutine task at the same time without
experiencing one more round of this listen and awaken of the event loop.

basically we do not have to tell the event loop that the socket for the kernel is avaliable, so go to run the kernel.  

# operations external to the kernel 

the kernel runs when there's at least one task appended into the ready queue.

and the kernel will just keep popping the task from the ready queue until no task left in the queue.

and something might go unexpectedly when it comes to worker delegation.

imagine our application will get a message bearing a function name and the parameters from RabbitMQ.

and next we will just run that function in a thread or process, and wait on a future object for the result.

and when the function finishes, the worker will send the result or exception back to the kernel via that future object.

and when the future's got a result or an exception, it will call the callback you have specified.

we can not run the kernel within that future's callback, why?

because that callback will be executed in a different thread than the kernel, and suddenly you are running your kernel
in two different places, which is inherently dangerous.

```python

        # It's inherently dangerous for any kind of operation on the kernel to be
        # performed by a separate thread. 
```

so it's like you execute task t1 in thread th1, and resume task t2 in thread th2, bad behavior. 

we have to execute all the task in one thread only, it's a serialization process to make sure everthing run consistently.

but why just put the task into the wake_queue and then transfer it to the ready_queue rather than put it directly into the
ready_queue?

we guess in part because there are some things to be done to decide whether the task is eligible to run.

and of course we can put the task into the ready_queue and do those things before actually run it.

but moving those checks to another corountine activated once the wake_queue appends something is a better and cleaner design.

and if a thread just is completing a future object while the kernel is popping the task from the ready queue, then 
the length of the ready_queue would become unconsistently, lyou are changing the size of the read_queue while iterationg through it.

though it's ok since the `deque` data structure is thread-safe, it's just weired and probably not a good choice for coding as we
are not a producer-consumer application.

