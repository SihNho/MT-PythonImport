"""Records of the acquisition pipeline: segments, frame records and per-frame results (WP3 frame contract,
docs/design/api.md "Frame contract for WP3").

- A **segment** begins at every acquisition start (also the restart after a "needs a short pause" change, U17). It
  keeps the settings read back for it (rate, ROI, exposure) and its own counters.
- A **frame record** keeps the camera's original buffer number with its segment number; buffer numbers are never
  renumbered or joined into one running number.
- A loss at the end of a segment that cannot be confirmed is `None` (unknown), never 0.
"""
from dataclasses import dataclass, field

import numpy as np

UNKNOWN = None          # a count that cannot be confirmed (segment-end loss)


@dataclass
class Segment:
    """One acquisition start .. stop. Counters are written only by the camera thread (one writer)."""
    number: int
    start_pc_s: float                     # PC clock (time.time()) when the segment was opened
    rate_Hz: float                        # frame rate read back from the camera for this segment
    roi: tuple                            # (x, y, w, h) read back
    exposure_ms: float
    t_source: str                         # what `t_camera_s` of its frames is (sim clock / PC receive time)
    pc_gap_s: float | None = None         # PC time since the previous segment ended (None for the first)
    reason: str = "start"                 # start | settings change | unannounced restart
    end_pc_s: float | None = None
    first_buffer: int | None = None
    last_buffer: int | None = None
    frames_received: int = 0
    camera_gaps: int = 0                  # frames missing in the buffer numbers (camera / driver side)
    pipeline_drops: int = 0               # frames received but dropped from the full ring (never tracked)
    end_loss: int | None = UNKNOWN        # frames produced after the last one received: unknown until confirmed

    def as_dict(self):
        return dict(self.__dict__)


@dataclass(frozen=True)
class FrameRecord:
    """One camera frame as received. `t_camera_s` comes from `t_source` (the simulator's own clock since acquisition
    start; for the real JAI, which has no hardware timestamp (0005), it will be the PC receive time)."""
    segment: int
    buffer_number: int                    # original IMAQdx buffer number, restarts at 0 in each segment
    t_camera_s: float
    t_source: str
    t_pc_s: float                         # PC clock (time.time()) when the camera thread received it
    rate_Hz: float                        # of its segment
    roi: tuple                            # of its segment
    gap_before: int = 0                   # camera-side frames missing right before this one
    recording: bool = False               # belongs to the recording (flag at receive time)


@dataclass(frozen=True)
class FrameResult:
    """The tracking result of one frame: x, y in px, z in um, good per bead (order of `bead_ids`); -1.0 marks a
    lost bead as in LabVIEW. `dropped` = a pipeline drop (received, never tracked; xyz and good are None)."""
    record: FrameRecord
    bead_ids: tuple
    xyz: np.ndarray | None
    good: np.ndarray | None
    track_ms: float | None = None
    dropped: bool = False
    extra: dict = field(default_factory=dict)
