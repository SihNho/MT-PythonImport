"""Results sink: where recorded frames and events go. The HDF5 / .tra writer is WP4; it implements `ResultSink`.

The pipeline calls every method from ONE sink thread, in the order the items were queued (a lossless queue: data,
not control), so an implementation needs no locking of its own. It receives `write_frame` for every received frame
that belongs to the recording (pipeline drops included, `result.dropped`) and `write_event` for every `api.events`
event logged while recording is on, including the `recording` on / off events themselves.
"""


class ResultSink:
    def write_frame(self, result):
        """result: `mtpy.acq.records.FrameResult`."""
        raise NotImplementedError

    def write_event(self, event):
        """event: `mtpy.api.events.Event`."""
        raise NotImplementedError

    def close(self):
        """Called once at acquisition stop, after the last write."""


class MemorySink(ResultSink):
    """Keeps everything in lists (tests, short exploration runs)."""

    def __init__(self):
        self.frames, self.events, self.closed = [], [], False

    def write_frame(self, result):
        self.frames.append(result)

    def write_event(self, event):
        self.events.append(event)

    def close(self):
        self.closed = True
