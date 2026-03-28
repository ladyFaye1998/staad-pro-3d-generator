"""Structural checks on generated frame models before emitting STAAD text."""

from __future__ import annotations

import math

from staad_generator.geometry import FrameModel


class FrameValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        msg = "Frame validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        super().__init__(msg)


def validate_frame(fm: FrameModel, *, min_member_length_m: float = 1e-4) -> list[str]:
    """Return a list of human-readable issues (empty if OK)."""
    errors: list[str] = []
    joints = fm.joint_coords
    jset = set(joints)

    seen_mid: set[int] = set()
    referenced: set[int] = set()
    for mid, n1, n2, kind in fm.members:
        if mid in seen_mid:
            errors.append(f"duplicate member id {mid}")
        seen_mid.add(mid)
        referenced.add(n1)
        referenced.add(n2)
        for jn, label in ((n1, "i"), (n2, "j")):
            if jn not in jset:
                errors.append(f"member {mid} ({kind}): {label}-end joint {jn} missing")
        if n1 in jset and n2 in jset:
            x1, y1, z1 = joints[n1]
            x2, y2, z2 = joints[n2]
            length = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)
            if length < min_member_length_m:
                errors.append(
                    f"member {mid} ({kind}): near-zero length {length:.2e} m (joints {n1}-{n2})"
                )

    if len(seen_mid) != len(fm.members):
        errors.append("member count mismatch vs unique member ids")

    dangling = sorted(jset - referenced)
    if dangling:
        tail = " ..." if len(dangling) > 24 else ""
        sample = dangling[:24]
        errors.append(f"joints with no member incidence: {sample}{tail}")

    return errors


def validate_frame_or_raise(fm: FrameModel, *, min_member_length_m: float = 1e-4) -> None:
    err = validate_frame(fm, min_member_length_m=min_member_length_m)
    if err:
        raise FrameValidationError(err)
