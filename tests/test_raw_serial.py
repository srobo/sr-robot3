"""
Test that raw serial devices can be created and used.

This test uses a mock serial wrapper to simulate the connection to the serial device.
"""
from __future__ import annotations

from typing import NamedTuple

import pytest

from sr.robot.raw_serial import RawSerial, RawSerialDevice
from sr.robot.utils import BoardIdentity

from .conftest import MockSerialWrapper


class MockRawSerial(NamedTuple):
    """A mock arduino board."""

    serial_wrapper: MockSerialWrapper
    serial_device: RawSerial


@pytest.fixture
def raw_serial(monkeypatch) -> None:
    serial_wrapper = MockSerialWrapper([])
    monkeypatch.setattr('sr.robot.raw_serial.SerialWrapper', serial_wrapper)
    raw_serial_device = RawSerial('test://', identity=BoardIdentity(asset_tag='TEST123'))

    yield MockRawSerial(serial_wrapper, raw_serial_device)

    # Test that we made all the expected calls
    assert serial_wrapper.request_index == len(serial_wrapper.responses)


def test_invalid_properties(raw_serial: MockRawSerial) -> None:
    """
    Test that settng invalid properties raise an AttributeError.
    """
    serial_device = raw_serial.serial_device

    with pytest.raises(AttributeError):
        serial_device.invalid_property = 1


def test_serial_device_discovery(monkeypatch) -> None:
    """
    Test that discovery finds arduino boards from USB serial ports.

    Test that different USB pid/vid combinations are ignored.
    """
    class ListPortInfo(NamedTuple):
        """A mock serial port info."""
        device: str
        manufacturer: str
        product: str
        serial_number: str
        vid: int
        pid: int

    def mock_comports() -> list[ListPortInfo]:
        ports = [
            ListPortInfo(
                device='test://1',
                manufacturer='Student Robotics',
                product='Arduino',
                serial_number='TEST123',
                vid=0x2341,
                pid=0x0043,
            ),
            ListPortInfo(  # A arduino board with a different pid/vid
                device='test://3',
                manufacturer='Other',
                product='Arduino',
                serial_number='OTHER',
                vid=0x1234,
                pid=0x5678,
            ),
            ListPortInfo(  # An unrelated device
                device='test://5',
                manufacturer='Student Robotics',
                product='OTHER',
                serial_number='TESTABC',
                vid=0x2341,
                pid=0x0043,
            ),
        ]
        return ports

    serial_wrapper = MockSerialWrapper([])
    monkeypatch.setattr('sr.robot.raw_serial.SerialWrapper', serial_wrapper)
    monkeypatch.setattr('sr.robot.raw_serial.comports', mock_comports)

    serial_devices = RawSerial._get_supported_boards([
        RawSerialDevice(
            serial_number='TEST123',
        ),
        RawSerialDevice(
            serial_number='OTHER',
            baudrate=9600,
        ),
    ])
    assert len(serial_devices) == 2
    assert {'TEST123', 'OTHER'} == set(serial_devices.keys())
    assert serial_devices['TEST123'].identify() == BoardIdentity(
        manufacturer='Student Robotics',
        board_type='Arduino',
        asset_tag='TEST123',
        sw_version='2341:0043',
    )
    assert serial_devices['OTHER'].identify() == BoardIdentity(
        manufacturer='Other',
        board_type='Arduino',
        asset_tag='OTHER',
        sw_version='1234:5678',
    )


def test_serial_device(raw_serial: MockRawSerial) -> None:
    serial_device = raw_serial.serial_device
    raw_serial.serial_wrapper._add_responses([
        ("test", "test response"),
        (None, "test read"),
        ("test write", ""),
    ])

    assert serial_device.query("test") == "test response"
    assert serial_device.read() == "test read"
    serial_device.write("test write")
