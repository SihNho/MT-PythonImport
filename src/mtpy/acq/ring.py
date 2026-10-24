"""The ring buffer between the camera thread and the tracking worker.

The camera thread must never wait for the worker: `push` always returns at once. When the ring is full the OLDEST
unprocessed frame is dropped and handed back to the caller, which counts it as a pipeline drop (distinct from
camera-side gaps, which show in the buffer numbers). The worker receives the dropped frames' records with its next
`pop`, so the results stream still has a row for every received frame.
"""
import collections
import threading


class FrameRing:
    def __init__(self, capacity=64):
        if capacity < 1:
            raise ValueError("ring capacity must be >= 1")
        self.capacity = capacity
        self._items = collections.deque()
        self._dropped = []
        self._cond = threading.Condition()

    def push(self, item, record):
        """Add item (never blocks on the consumer). Returns the record of the dropped oldest item, or None."""
        with self._cond:
            dropped = None
            if len(self._items) >= self.capacity:
                dropped = self._items.popleft()[1]
                self._dropped.append(dropped)
            self._items.append((item, record))
            self._cond.notify()
        return dropped

    def pop(self, timeout_s):
        """(item or None after timeout_s, [records dropped since the last pop])."""
        with self._cond:
            self._cond.wait_for(lambda: self._items or self._dropped, timeout_s)
            item = self._items.popleft()[0] if self._items else None
            dropped, self._dropped = self._dropped, []
        return item, dropped

    def __len__(self):
        with self._cond:
            return len(self._items)
