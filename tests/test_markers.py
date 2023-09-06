import csv
import json
from math import radians
from pathlib import Path
from typing import NamedTuple

import pytest
import numpy as np

from sr.robot3.marker import Marker


class MarkerValues(NamedTuple):
    index: int
    tvec: np.ndarray
    rvec: np.ndarray
    distance: float
    horizontal_angle: float
    vertical_angle: float
    yaw: float
    pitch: float
    roll: float
    name: str = "marker"


class MockAprilMarker(NamedTuple):
    """
    A minimal mock of the Marker class from april_vision.
    """
    id: int
    size: int
    tvec: np.ndarray
    rvec: np.ndarray
    pixel_corners: tuple = ((0, 0), (0, 0), (0, 0), (0, 0))
    pixel_centre: tuple = (0, 0)


def load_test_values():
    with open(Path(__file__).parent / "test_data/marker_detections.json") as f:
        test_data = json.load(f)

    expected_values = []
    with open(Path(__file__).parent / "test_data/marker_locations.csv") as f:
        csv_reader = csv.DictReader(f)
        for row in csv_reader:
            expected_values.append(row)

    return [
        pytest.param(
            MarkerValues(
                index=int(row["Index"]),
                tvec=np.array(test_data[row["Index"]]["tvec"]),
                rvec=np.array(test_data[row["Index"]]["rvec"]),
                distance=float(row["distance"]),
                horizontal_angle=float(row["horizontal angle"]),
                vertical_angle=float(row["vertical angle"]),
                yaw=float(row["yaw"]),
                pitch=float(row["pitch"]),
                roll=float(row["roll"]),
                name=row.get("name", "marker"),
            ),
            id=row.get("name", "marker"),
        )
        for row in expected_values
    ]


@pytest.mark.parametrize("test_values", load_test_values())
def test_marker(test_values: MarkerValues):
    marker_under_test = MockAprilMarker(
        id=14, size=200, tvec=test_values.tvec, rvec=test_values.rvec,
    )
    marker = Marker.from_april_vision_marker(marker_under_test)

    assert marker.id == 14, "Marker ID should be 14"
    assert marker.size == 200, "Marker size should be 200mm"

    # in mm
    assert marker.position.distance == pytest.approx(
        test_values.distance * 1000, rel=1e-2), (
        f"Distance to marker of {test_values.name} is incorrect. "
        f"{marker.position.distance} != {test_values.distance * 1000}")
    assert marker.position.horizontal_angle == pytest.approx(
        test_values.horizontal_angle, abs=radians(0.1)), (
        f"Horizontal angle of {test_values.name} is incorrect. "
        f"{marker.position.horizontal_angle} != {test_values.horizontal_angle}")
    assert marker.position.vertical_angle == pytest.approx(
        test_values.vertical_angle, abs=radians(0.1)), (
        f"Vertical angle of {test_values.name} is incorrect. "
        f"{marker.position.vertical_angle} != {test_values.vertical_angle}")

    assert marker.orientation.yaw == pytest.approx(test_values.yaw, abs=radians(2.5)), (
        f"Yaw of {test_values.name} is incorrect. "
        f"{marker.orientation.yaw} != {test_values.yaw}"
    )
    assert marker.orientation.pitch == pytest.approx(test_values.pitch, abs=radians(2.5)), (
        f"Pitch of {test_values.name} is incorrect. "
        f"{marker.orientation.pitch} != {test_values.pitch}"
    )
    assert marker.orientation.roll == pytest.approx(test_values.roll, abs=radians(0.2)), (
        f"Roll of {test_values.name} is incorrect. "
        f"{marker.orientation.roll} != {test_values.roll}"
    )
