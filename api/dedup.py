"""Bounded process-local deduplication; no pending work is acknowledged."""

import time
from collections import OrderedDict


class Deduplicator:
    def __init__(self, ttl, max_entries, max_inflight, clock=time.monotonic):
        self.ttl = ttl
        self.max_entries = max_entries
        self.max_inflight = max_inflight
        self.clock = clock
        self.completed = OrderedDict()
        self.pending = set()

    def claim(self, key):
        # All methods run without awaits on one event loop / one worker.
        now = self.clock()
        while self.completed and next(iter(self.completed.values())) <= now:
            self.completed.popitem(last=False)
        if key in self.completed:
            return "duplicate"
        if key in self.pending or len(self.pending) >= self.max_inflight:
            return "busy"
        self.pending.add(key)
        return "claimed"

    def finish(self, key):
        self.pending.discard(key)
        self.completed[key] = self.clock() + self.ttl
        while len(self.completed) > self.max_entries:
            self.completed.popitem(last=False)

    def release(self, key):
        self.pending.discard(key)
