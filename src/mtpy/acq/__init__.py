"""Acquisition pipeline (plan phase 5, WP3): camera thread -> ring buffer -> tracking worker -> results sink, with a
display tap for the GUI. Used through `mtpy.api.acq` / `api.tracking` / `api.beads`; the HDF5 / .tra writer (WP4)
implements `ResultSink`."""
from .pipeline import Beads, BeadTracker, DisplayTap, Pipeline, Snapshot, make_kernel
from .records import UNKNOWN, FrameRecord, FrameResult, Segment
from .ring import FrameRing
from .sink import MemorySink, ResultSink

__all__ = ["UNKNOWN", "BeadTracker", "Beads", "DisplayTap", "FrameRecord", "FrameResult", "FrameRing", "MemorySink",
           "Pipeline", "ResultSink", "Segment", "Snapshot", "make_kernel"]
