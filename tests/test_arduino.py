"""
Test that the arduino board can be created and used.

This test uses a mock serial wrapper to simulate the connection to the arduino board.
"""
from __future__ import annotations

import logging
from typing import NamedTuple

import pytest

from sr.robot3.arduino import AnalogPins, Arduino, GPIOPinMode
from sr.robot3.utils import BoardIdentity, singular

from .conftest import MockSerialWrapper


class MockArduino(NamedTuple):
    """A mock arduino board."""

    serial_wrapper: MockSerialWrapper
    arduino_board: Arduino


@pytest.fixture
def arduino_serial(monkeypatch) -> None:
    serial_wrapper = MockSerialWrapper([
        ("v", "SRduino:2.0"),  # Called by Arduino.__init__
    ])
    monkeypatch.setattr('sr.robot3.arduino.SerialWrapper', serial_wrapper)
    arduino_board = Arduino('test://', initial_identity=BoardIdentity(asset_tag='TEST123'))

    yield MockArduino(serial_wrapper, arduino_board)

    # Test that we made all the expected calls
    assert serial_wrapper.request_index == len(serial_wrapper.responses)


def test_arduino_board_identify(arduino_serial: MockArduino) -> None:
    """
    Test that we can create a arduino board with a mock serial wrapper.

    Uses the identify method to test that the mock serial wrapper is working.
    """
    serial_wrapper = arduino_serial.serial_wrapper
    serial_wrapper._add_responses([
        ("v", "SSRduino:2.0"),
    ])
    arduino_board = arduino_serial.arduino_board

    # Test that the port was correctly passed to the mock serial wrapper init
    assert serial_wrapper._port == 'test://'

    # Test that the identity is correctly set from the first *IDN? response
    assert arduino_board._identity.board_type == "SRduino"
    assert arduino_board._identity.asset_tag == "TEST123"

    # Test identify returns the identity
    assert arduino_board.identify().asset_tag == "TEST123"


def test_arduino_custom_command(arduino_serial: MockArduino) -> None:
    """
    Test that we can send a custom command to the arduino board.

    This test uses the mock serial wrapper to simulate the arduino.
    """
    arduino = arduino_serial.arduino_board
    arduino_serial.serial_wrapper._add_responses([
        ("test:f", "ACK123"),
    ])

    # Test that we can send a custom command
    pin_str = arduino.map_pin_number(5)
    assert pin_str == "f"  # zero indexed from 'a'
    assert arduino.command(f"test:{pin_str}") == "ACK123"


def test_arduino_pins(arduino_serial: MockArduino) -> None:
    """
    Test the arduino pins properties and methods.

    This test uses the mock serial wrapper to simulate the arduino.
    """
    arduino = arduino_serial.arduino_board
    arduino_serial.serial_wrapper._add_responses([
        ("oc", ""),  # pin 2 is set to output
        ("pk", ""),  # pin 10 is set to input pullup
        ("io", ""),  # pin 14 is set to input
    ])

    with pytest.raises(IOError):
        arduino.pins[2].mode = 1

    # Test that we can set the mode of a pin
    arduino.pins[2].mode = GPIOPinMode.OUTPUT
    arduino.pins[10].mode = GPIOPinMode.INPUT_PULLUP
    arduino.pins[AnalogPins.A0].mode = GPIOPinMode.INPUT

    # Test that we can get the mode of a pin
    assert arduino.pins[2].mode == GPIOPinMode.OUTPUT
    assert arduino.pins[10].mode == GPIOPinMode.INPUT_PULLUP
    assert arduino.pins[AnalogPins.A0].mode == GPIOPinMode.INPUT

    # Test that we can get the digital value of a pin
    arduino_serial.serial_wrapper._add_responses([
        ("rc", "h"),  # pin 2 read
        ("rk", "l"),  # pin 10 read
        ("ro", "h"),  # pin 14 read
    ])
    assert arduino.pins[2].digital_read() is True
    assert arduino.pins[10].digital_read() is False
    assert arduino.pins[AnalogPins.A0].digital_read() is True

    # Test that we can set the digital value of a pin
    arduino_serial.serial_wrapper._add_responses([
        ("hc", "ACK"),  # pin 2 write
        ("lc", "ACK"),  # pin 2 write
    ])
    arduino.pins[2].digital_write(True)
    arduino.pins[2].digital_write(False)
    with pytest.raises(IOError, match=r"Digital write is not supported.*"):
        arduino.pins[10].digital_write(False)
    with pytest.raises(IOError, match=r"Digital write is not supported.*"):
        arduino.pins[AnalogPins.A0].digital_write(True)

    # Test that we can get the analog value of a pin
    arduino_serial.serial_wrapper._add_responses([
        ("il", ""),  # pin 11 is set to input
        ("ao", "1000"),  # pin 14 analog read
    ])
    with pytest.raises(IOError, match=r"Analog read is not supported.*"):
        arduino.pins[2].analog_read()

    arduino.pins[11].mode = GPIOPinMode.INPUT
    with pytest.raises(IOError, match=r"Pin does not support analog read"):
        arduino.pins[11].analog_read()
    # 4.888 = round((5 / 1023) * 1000, 3)
    assert arduino.pins[AnalogPins.A0].analog_read() == 4.888


def test_invalid_properties(arduino_serial: MockArduino) -> None:
    """
    Test that settng invalid properties raise an AttributeError.
    """
    arduino_board = arduino_serial.arduino_board

    with pytest.raises(AttributeError):
        arduino_board.invalid_property = 1

    with pytest.raises(AttributeError):
        arduino_board.pins.invalid_property = 1

    with pytest.raises(AttributeError):
        arduino_board.pins[0].invalid_property = 1


def test_arduino_board_discovery(monkeypatch) -> None:
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

    serial_wrapper = MockSerialWrapper([
        ("v", "SRduino:2.0"),  # USB discovered board
        ("v", "Arduino:4.3"),  # USB invalid board
        ("v", "SRcustom:3.0"),  # Manually added board
        ("v", "OTHER:4.3"),  # Manual invalid board
        ("v", "SRduino:2.0"),  # identity check
        ("v", "SRcustom:3.0"),  # identity check
    ])
    monkeypatch.setattr('sr.robot3.arduino.SerialWrapper', serial_wrapper)
    monkeypatch.setattr('sr.robot3.arduino.comports', mock_comports)

    arduino_boards = Arduino._get_supported_boards(manual_boards=['test://2', 'test://4'])
    assert len(arduino_boards) == 2
    # Manually added boards use the serial port as the asset tag
    assert {'TEST123', 'test://2'} == set(arduino_boards.keys())

    identity = arduino_boards['TEST123'].identify()
    assert identity.board_type == "SRduino"
    assert identity.sw_version == "2.0"

    identity = arduino_boards['test://2'].identify()
    assert identity.board_type == "SRcustom"
    assert identity.sw_version == "3.0"


def test_arduino_board_new_sourcebots_identity(monkeypatch, caplog) -> None:
    """
    Test that we raise an error if the arduino board returns an old style identity.
    """
    serial_wrapper = MockSerialWrapper([
        ("v", "NACK:Invalid command"),  # Called by Arduino.__init__
    ])
    monkeypatch.setattr('sr.robot3.arduino.SerialWrapper', serial_wrapper)

    with caplog.at_level(logging.WARNING):
        arduino = Arduino._get_valid_board('test://', BoardIdentity(board_type="manual"))

    assert arduino is None
    assert caplog.records[0].message == (
        "Board returned type 'NACK', expected 'SR*'. Ignoring this device"
    )


def test_arduino_board_old_sourcebots_identity(monkeypatch, caplog) -> None:
    """
    Test that we raise an error if the arduino board returns an old style identity.
    """
    serial_wrapper = MockSerialWrapper([
        ("v", "Error, unknown command: v"),  # Called by Arduino.__init__
    ])
    monkeypatch.setattr('sr.robot3.arduino.SerialWrapper', serial_wrapper)

    with caplog.at_level(logging.WARNING):
        arduino = Arduino._get_valid_board('test://', BoardIdentity(board_type="manual"))

    assert arduino is None
    assert caplog.records[0].message == (
        "Board returned type 'Error, unknown command', expected 'SR*'. Ignoring this device"
    )


@pytest.mark.hardware
def test_physical_arduino_board_discovery() -> None:
    """Test that we can discover physical arduino boards."""
    arduino_boards = Arduino._get_supported_boards()
    assert len(arduino_boards) == 1, "Did not find exactly one arduino board."
    arduino_board = singular(arduino_boards)
    identity = arduino_board.identify()
    assert identity.board_type == "Arduino", "arduino board is not the correct type."
    asset_tag = identity.asset_tag
    assert arduino_board == arduino_boards[asset_tag], \
        "Singular arduino board is not the same as the one in the list of arduino boards."
