"""
Test that raw serial devices can be created and used.

This test uses a mock serial wrapper to simulate the connection to the serial device.
"""
from __future__ import annotations

from typing import NamedTuple
from unittest.mock import MagicMock, call, patch

import pytest

from sr.robot3.raw_serial import RawSerial, RawSerialDevice
from sr.robot3.utils import BoardIdentity


class MockRawSerial(NamedTuple):
    """A mock arduino board."""

    serial_wrapper: MagicMock
    serial_device: RawSerial


@pytest.fixture
def raw_serial() -> None:
    with patch('sr.robot3.raw_serial.serial_for_url') as MockSerial:
        MockSerial.return_value = MagicMock()
        raw_serial_device = RawSerial('test://', identity=BoardIdentity(asset_tag='TEST123'))
        assert MockSerial.call_count == 1

        yield MockRawSerial(MockSerial, raw_serial_device)


def test_invalid_properties(raw_serial: MockRawSerial) -> None:
    """
    Test that settng invalid properties raise an AttributeError.
    """
    serial_device = raw_serial.serial_device

    with pytest.raises(AttributeError):
        serial_device.invalid_property = 1

    assert raw_serial.serial_wrapper.mock_calls == [
        call('test://', baudrate=115200, timeout=0.5)]
    assert raw_serial.serial_wrapper.return_value.mock_calls == []


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

    monkeypatch.setattr('sr.robot3.raw_serial.comports', mock_comports)
    with patch('sr.robot3.raw_serial.serial_for_url') as MockSerial:
        MockSerial.return_value = MagicMock()
        serial_devices = RawSerial._get_supported_boards([
            RawSerialDevice(
                serial_number='TEST123',
            ),
            RawSerialDevice(
                serial_number='OTHER',
                baudrate=9600,
            ),
        ])
        assert MockSerial.mock_calls == [
            call('test://1', baudrate=115200, timeout=0.5),
            call('test://3', baudrate=9600, timeout=0.5),
        ]

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
    serial_object = raw_serial.serial_wrapper.return_value

    serial_device.write(b'hello')
    assert serial_object.write.mock_calls == [call(b'hello')]

    serial_object.read.return_value = b'A'

    assert serial_device.read(1) == b'A'
    assert serial_object.read.mock_calls == [call(1)]

    serial_object.read_until.return_value = b'hello'

    assert serial_device.read_until(b'x') == b'hello'
    assert serial_object.read_until.mock_calls == [call(b'x')]
