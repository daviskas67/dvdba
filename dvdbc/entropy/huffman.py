"""
Entropy coding: Run-Length + packed binary values.
Robust: separate sections for markers, run-lengths, and values.
"""

import struct
import numpy as np


class RLEPlusHuffman:
    """
    Entropy coding for quantized DCT coefficients.
    Three separate length-prefixed sections:
      1. Marker types (Z=0, V=1, E=2)
      2. Zero run lengths (uint16 per Z marker)
      3. Values (int32 per V marker)
    """

    @staticmethod
    def encode_coeffs(coeffs: np.ndarray) -> bytes:
        markers = bytearray()
        run_lengths = []
        values = []

        zero_run = 0
        for c in coeffs:
            if c == 0:
                zero_run += 1
            else:
                if zero_run > 0:
                    markers.append(0)  # Z
                    run_lengths.append(zero_run)
                    zero_run = 0
                markers.append(1)  # V
                values.append(int(c))
        if zero_run > 0:
            markers.append(0)
            run_lengths.append(zero_run)
        markers.append(2)  # E

        # Pack run lengths as uint16 (big-endian)
        runs_bytes = struct.pack(f'!{len(run_lengths)}H', *run_lengths) if run_lengths else b''
        # Pack values as int16 (big-endian) — quantized DCT coeffs fit in 16-bit
        val_bytes = struct.pack(f'!{len(values)}h', *values) if values else b''

        return (struct.pack('!I', len(markers)) + bytes(markers) +
                struct.pack('!I', len(runs_bytes)) + runs_bytes +
                struct.pack('!I', len(val_bytes)) + val_bytes)

    @staticmethod
    def decode_coeffs(data: bytes) -> np.ndarray:
        offset = 0
        # Markers
        mlen = struct.unpack_from('!I', data, offset)[0]
        offset += 4
        markers = data[offset:offset+mlen]
        offset += mlen
        # Run lengths (uint16)
        rlen = struct.unpack_from('!I', data, offset)[0]
        offset += 4
        nruns = rlen // 2
        runs = list(struct.unpack(f'!{nruns}H', data[offset:offset+rlen])) if nruns > 0 else []
        offset += rlen
        # Values (int16)
        vlen = struct.unpack_from('!I', data, offset)[0]
        offset += 4
        n_vals = vlen // 2
        vals = list(struct.unpack(f'!{n_vals}h', data[offset:offset+vlen])) if n_vals > 0 else []

        coeffs = []
        ri = 0
        vi = 0
        for m in markers:
            if m == 0:  # zero run
                if ri < len(runs):
                    coeffs.extend([0] * runs[ri])
                    ri += 1
            elif m == 1:  # value
                if vi < len(vals):
                    coeffs.append(vals[vi])
                    vi += 1
            elif m == 2:  # end
                break

        return np.array(coeffs, dtype=np.int32)
