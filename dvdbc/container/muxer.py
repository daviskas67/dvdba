"""
DVDBC Container Format:
┌──────────────────────────────┐
│  Magic: "DVDBC" (5 bytes)    │
│  Version: uint8              │
│  Width: uint32               │
│  Height: uint32              │
│  FPS: float32                │
│  FrameCount: uint32          │
│  Quality: float32            │
│  KeyframeInterval: uint32    │
│  Reserved: 16 bytes          │
├──────────────────────────────┤
│  Frame N:                    │
│  ┌────────────────────────┐  │
│  │ Type: uint8 (0=key,1=P)│  │
│  │ Size: uint32           │  │
│  │ Data: [size bytes]     │  │
│  └────────────────────────┘  │
└──────────────────────────────┘
"""

import struct
import numpy as np

MAGIC = b'DVDBC'
HEADER_FMT = '!5s B I I f I f I 16x'
HEADER_SIZE = struct.calcsize(HEADER_FMT)

FRAME_HEADER_FMT = '!B I'
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FMT)

def mux_header(width: int, height: int, fps: float,
               frame_count: int, quality: float,
               keyframe_interval: int) -> bytes:
    return struct.pack(HEADER_FMT,
                       MAGIC, 1, width, height, fps,
                       frame_count, quality, keyframe_interval)

def parse_header(data: bytes) -> dict:
    magic, ver, w, h, fps, fc, qual, ki = struct.unpack_from(HEADER_FMT, data)
    if magic != MAGIC:
        raise ValueError(f"Not a DVDBC file (magic: {magic})")
    return {
        'version': ver, 'width': w, 'height': h,
        'fps': fps, 'frame_count': fc,
        'quality': qual, 'keyframe_interval': ki
    }

def mux_frame(frame_type: int, frame_data: bytes) -> bytes:
    return struct.pack(FRAME_HEADER_FMT, frame_type, len(frame_data)) + frame_data

def parse_frame_header(data: bytes, offset: int) -> tuple:
    ftype, fsize = struct.unpack_from(FRAME_HEADER_FMT, data, offset)
    return ftype, fsize, offset + FRAME_HEADER_SIZE
