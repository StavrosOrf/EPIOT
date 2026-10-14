"""Counter-based random numbers: a value depends only on its key and counter.

Synthetic scenarios are generated on request for arbitrary windows, so random
numbers are hashed from (key, counter) rather than drawn in sequence: the same
point, quarter-hour or day always gets the same value, whichever window asks.
"""

import hashlib

import numpy as np

_M1, _M2 = np.uint64(0xbf58476d1ce4e5b9), np.uint64(0x94d049bb133111eb)


def mix(values):
    """SplitMix64 finalizer: a bijective, well-mixed uint64 hash (in place)."""
    shifted = np.empty_like(values)
    for shift, multiplier in ((30, _M1), (27, _M2), (31, None)):
        np.right_shift(values, np.uint64(shift), out=shifted)
        np.bitwise_xor(values, shifted, out=values)
        if multiplier is not None:
            np.multiply(values, multiplier, out=values)
    return values


def text_key(text):
    """A uint64 key from any identifying text."""
    return np.uint64(int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little"))


def to_unit(values):
    """53 random bits to a float strictly inside (0, 1)."""
    return ((values >> np.uint64(11)).astype(float)+.5)*2.**-53


def stream(slots, index):
    return mix(np.asarray(slots, np.uint64)*np.uint64(4)+np.uint64(index))


def uniforms(keys, slots, index):
    """Counter-based uniforms: identical for the same key, counter and stream."""
    return to_unit(mix(np.bitwise_xor(keys, stream(slots, index))))
