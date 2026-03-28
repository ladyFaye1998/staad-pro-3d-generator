"""Frame model validation."""

from __future__ import annotations

import pytest

from staad_generator.geometry import FrameModel
from staad_generator.validate import FrameValidationError, validate_frame, validate_frame_or_raise


def test_validate_ok_minimal() -> None:
    fm = FrameModel(
        joint_coords={1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)},
        members=[(1, 1, 2, "test")],
    )
    assert validate_frame(fm) == []
    validate_frame_or_raise(fm)


def test_validate_missing_joint() -> None:
    fm = FrameModel(
        joint_coords={1: (0.0, 0.0, 0.0)},
        members=[(1, 1, 99, "bad")],
    )
    err = validate_frame(fm)
    assert any("missing" in e and "joint" in e for e in err)
    with pytest.raises(FrameValidationError):
        validate_frame_or_raise(fm)


def test_validate_duplicate_member_id() -> None:
    fm = FrameModel(
        joint_coords={1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)},
        members=[(1, 1, 2, "a"), (1, 1, 2, "b")],
    )
    err = validate_frame(fm)
    assert any("duplicate member" in e for e in err)


def test_validate_zero_length() -> None:
    fm = FrameModel(
        joint_coords={1: (0.0, 0.0, 0.0), 2: (0.0, 0.0, 0.0)},
        members=[(1, 1, 2, "bad")],
    )
    err = validate_frame(fm)
    assert any("zero-length" in e or "near-zero" in e for e in err)


def test_validate_dangling_joint() -> None:
    fm = FrameModel(
        joint_coords={
            1: (0.0, 0.0, 0.0),
            2: (1.0, 0.0, 0.0),
            3: (2.0, 0.0, 0.0),
        },
        members=[(1, 1, 2, "beam")],
    )
    err = validate_frame(fm)
    assert any("no member incidence" in e and "3" in e for e in err)
