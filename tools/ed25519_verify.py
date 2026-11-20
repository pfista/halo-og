"""Verify an Ed25519 signature (RFC 8032) with a public key alone.

Sparkle's `sign_update --verify` needs the private key. Release tools use this
check instead, so the signature a feed carries is tested against the public key
that installed apps hold. It handles public values only and makes no attempt at
constant-time arithmetic.
"""
import hashlib

P = 2**255 - 19
ORDER = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
ROOT_OF_MINUS_ONE = pow(2, (P - 1) // 4, P)


def _x(y, sign):
    if y >= P:
        return None
    square = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if square == 0:
        return None if sign else 0
    x = pow(square, (P + 3) // 8, P)
    if (x * x - square) % P:
        x = x * ROOT_OF_MINUS_ONE % P
    if (x * x - square) % P:
        return None
    return P - x if x & 1 != sign else x


def _point(encoded):
    y = int.from_bytes(encoded, "little")
    x = _x(y & ((1 << 255) - 1), y >> 255)
    if x is None:
        return None
    y &= (1 << 255) - 1
    return x, y, 1, x * y % P


def _add(a, b):
    first = (a[1] - a[0]) * (b[1] - b[0]) % P
    second = (a[1] + a[0]) * (b[1] + b[0]) % P
    third = 2 * a[3] * b[3] * D % P
    fourth = 2 * a[2] * b[2] % P
    e, f, g, h = second - first, fourth - third, fourth + third, second + first
    return e * f % P, g * h % P, f * g % P, e * h % P


def _multiply(scalar, point):
    result = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


BASE = _point((4 * pow(5, P - 2, P) % P).to_bytes(32, "little"))


def verify(public_key, message, signature):
    """True when `signature` is `public_key`'s Ed25519 signature of `message`."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    key, commitment = _point(public_key), _point(signature[:32])
    scalar = int.from_bytes(signature[32:], "little")
    if key is None or commitment is None or scalar >= ORDER:
        return False
    challenge = int.from_bytes(
        hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % ORDER
    left, right = _multiply(scalar, BASE), _add(commitment, _multiply(challenge, key))
    return ((left[0] * right[2] - right[0] * left[2]) % P == 0
            and (left[1] * right[2] - right[1] * left[2]) % P == 0)
