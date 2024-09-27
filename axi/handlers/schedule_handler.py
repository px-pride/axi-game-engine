import asyncio
from bisect import insort
import random
import time
import copy

scheduled_events = []
scheduled_times = dict()
scheduled_keys = dict()
scheduled_tasks = dict()

async def schedule_event(timer, event, keys=None, suffix=None):
    already_scheduled = True
    if keys:
        for k_ in keys:
            k = (k_, suffix) if suffix else k_
            if k not in scheduled_keys:
                scheduled_keys[k] = (timer, event)
                already_scheduled = False
    if not (keys and already_scheduled):
        while timer in scheduled_times:
            timer += 0.01 * random.random()
        pair = (timer, event)
        scheduled_times[timer] = event
        insort(scheduled_events, pair)
        duration = timer - time.time()
        if duration < 0:
            return
        async def event_as_task():
            await asyncio.sleep(duration)
            await event()
            scheduled_events.remove(pair)
            del scheduled_times[timer]
        task = asyncio.create_task(event_as_task())
        if keys:
            for k_ in keys:
                k = (k_, suffix) if suffix else k_
                scheduled_tasks[k] = task

async def schedule_event_sequence(timers, events):
    async def e(x, timers, events, j):
        y = await events[j](x)
        if j + 1 < len(timers):
            await schedule_event(
                timers[j+1], lambda: e(y, timers, events, j+1))
        return y
    await schedule_event(
        timers[0], lambda: e(None, timers, events, 0))

async def unschedule(k):
    for k_ in copy.copy(list(scheduled_keys.keys())):
        if k_ == k or (isinstance(k_, tuple) and k_[0] == k):
            del scheduled_keys[k_]

