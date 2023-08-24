"""The Arduino module provides an interface to the Arduino firmware."""
from __future__ import annotations

import logging
from enum import Enum, IntEnum
from types import MappingProxyType

from serial.tools.list_ports import comports

from .exceptions import IncorrectBoardError
from .logging import log_to_debug
from .serial_wrapper import SerialWrapper
from .utils import Board, BoardIdentity, get_USB_identity, map_to_float

logger = logging.getLogger(__name__)
BAUDRATE = 115200

SUPPORTED_VID_PIDS = {
    (0x2341, 0x0043),  # Arduino Uno rev 3
    (0x2A03, 0x0043),  # Arduino Uno rev 3
    (0x1A86, 0x7523),  # Uno
    (0x10C4, 0xEA60),  # Ruggeduino
    (0x16D0, 0x0613),  # Ruggeduino
}


class GPIOPinMode(str, Enum):
    """The possible modes for a GPIO pin."""
    INPUT = 'INPUT'
    INPUT_PULLUP = 'INPUT_PULLUP'
    OUTPUT = 'OUTPUT'


class AnalogPins(IntEnum):
    """The analog pins on the Arduino."""
    A0 = 14
    A1 = 15
    A2 = 16
    A3 = 17
    A4 = 18
    A5 = 19


DIGITAL_READ_MODES = {GPIOPinMode.INPUT, GPIOPinMode.INPUT_PULLUP, GPIOPinMode.OUTPUT}
DIGITAL_WRITE_MODES = {GPIOPinMode.OUTPUT}
ANALOG_READ_MODES = {GPIOPinMode.INPUT}


class Arduino(Board):
    """
    The Arduino board interface.

    This is intended to be used with Arduino Uno boards running the sbot firmware.

    :param serial_port: The serial port to connect to.
    :param initial_identity: The identity of the board, as reported by the USB descriptor.
    """
    __slots__ = ('_serial_num', '_serial', '_pins', '_identity')

    @staticmethod
    def get_board_type() -> str:
        """
        Return the type of the board.

        :return: The literal string 'Arduino'.
        """
        return 'Arduino'

    def __init__(
        self,
        serial_port: str,
        initial_identity: BoardIdentity | None = None,
    ) -> None:
        if initial_identity is None:
            initial_identity = BoardIdentity()

        # The arduino firmware cannot access the serial number reported in the USB descriptor
        self._serial_num = initial_identity.asset_tag
        self._serial = SerialWrapper(
            serial_port,
            BAUDRATE,
            identity=initial_identity,
            delay_after_connect=2,  # Wait for the board to reset after connecting
        )

        self._pins = (
            tuple(  # Pins 0 and 1 are reserved for serial comms
                Pin(self._serial, index, supports_analog=False, disabled=True)
                for index in range(2))
            + tuple(Pin(self._serial, index, supports_analog=False) for index in range(2, 14))
            + tuple(Pin(self._serial, index, supports_analog=True) for index in range(14, 20))
        )

        self._identity = self.identify()
        # Arduino board type is not validated to allow for custom firmwares
        if not self._identity.board_type.startswith('SR'):
            raise IncorrectBoardError(self._identity.board_type, 'SR*')
        self._serial.set_identity(self._identity)

    @classmethod
    def _get_valid_board(
        cls,
        serial_port: str,
        initial_identity: BoardIdentity | None = None,
    ) -> None | Arduino:
        try:
            board = cls(serial_port, initial_identity)
        except IncorrectBoardError as err:
            logger.warning(
                f"Board returned type {err.returned_type!r}, "
                f"expected {err.expected_type!r}. Ignoring this device")
            return None
        except Exception:
            if initial_identity is not None and initial_identity.board_type == 'manual':
                logger.warning(
                    f"Manually specified Arduino at port {serial_port!r}, "
                    "could not be identified. Ignoring this device")
            else:
                logger.warning(
                    f"Found Arduino-like serial port at {serial_port!r}, "
                    "but it could not be identified. Ignoring this device")
            return None
        return board

    @classmethod
    def _get_supported_boards(
        cls,
        manual_boards: list[str] | None = None,
        ignored_serials: list[str] | None = None,
    ) -> MappingProxyType[str, Arduino]:
        """
        Discover the connected Arduinos, by matching the USB descriptor to SUPPORTED_VID_PIDS.

        :param manual_boards: A list of manually specified board port strings,
            defaults to None
        :return: A mapping of board serial numbers to Arduinos
        """
        boards = {}
        if ignored_serials is None:
            ignored_serials = []
        serial_ports = comports()
        for port in serial_ports:
            if (port.vid, port.pid) in SUPPORTED_VID_PIDS:
                # Create board identity from USB port info
                initial_identity = get_USB_identity(port)
                if initial_identity.asset_tag in ignored_serials:
                    continue

                if (board := cls._get_valid_board(port.device, initial_identity)) is None:
                    continue

                boards[board._identity.asset_tag] = board

        # Add any manually specified boards
        if isinstance(manual_boards, list):
            for manual_port in manual_boards:
                # Create board identity from the info given
                initial_identity = BoardIdentity(
                    board_type='manual',
                    asset_tag=manual_port,
                )

                if (board := cls._get_valid_board(manual_port, initial_identity)) is None:
                    continue

                boards[board._identity.asset_tag] = board
        return MappingProxyType(boards)

    @log_to_debug
    def identify(self) -> BoardIdentity:
        """
        Get the identity of the board.

        The asset tag of the board is the serial number from the USB descriptor.

        :return: The identity of the board.
        """
        response = self._serial.query('v', endl='')
        response_fields = response.split(':')

        # The arduino firmware cannot access the serial number reported in the USB descriptor
        return BoardIdentity(
            manufacturer=(
                "Student Robotics"
                if response_fields[0].startswith('SR')
                else "Arduino"),
            board_type=response_fields[0],
            asset_tag=self._serial_num,
            sw_version=response_fields[1],
        )

    @property
    @log_to_debug
    def pins(self) -> tuple[Pin, ...]:
        """
        The pins on the Arduino.

        :return: A tuple of the pins on the Arduino.
        """
        return self._pins

    def __repr__(self) -> str:
        return f"<{self.__class__.__qualname__}: {self._serial}>"


class Pin:
    """
    A pin on the Arduino.

    :param serial: The serial wrapper to use to communicate with the board.
    :param index: The index of the pin.
    :param supports_analog: Whether the pin supports analog reads.
    """
    __slots__ = ('_serial', '_index', '_supports_analog', '_disabled', '_mode')

    def __init__(
        self,
        serial: SerialWrapper,
        index: int,
        supports_analog: bool,
        disabled: bool = False
    ):
        self._serial = serial
        self._index = index
        self._supports_analog = supports_analog
        self._disabled = disabled
        self._mode = GPIOPinMode.INPUT_PULLUP

    @property
    @log_to_debug
    def mode(self) -> GPIOPinMode:
        """
        Get the mode of the pin.

        This returns the cached value since thew board does not report this.

        :raises IOError: If this pin cannot be controlled.
        :return: The mode of the pin.
        """
        self._check_if_disabled()
        return self._mode

    @mode.setter
    @log_to_debug
    def mode(self, value: GPIOPinMode) -> None:
        """
        Set the mode of the pin.

        To do analog or digital reads set the mode to INPUT or INPUT_PULLUP.
        To do digital writes set the mode to OUTPUT.

        :param value: The mode to set the pin to.
        :raises IOError: If the pin mode is not a GPIOPinMode.
        :raises IOError: If this pin cannot be controlled.
        """
        self._check_if_disabled()
        if not isinstance(value, GPIOPinMode):
            raise IOError('Pin mode only supports being set to a GPIOPinMode')

        mode_char_map = {
            GPIOPinMode.INPUT: 'i',
            GPIOPinMode.INPUT_PULLUP: 'p',
            GPIOPinMode.OUTPUT: 'o',
        }
        mode_char = mode_char_map.get(value)
        if mode_char is None:
            raise IOError(f'Pin mode {value} is not supported')
        self._serial.write(self._build_command(mode_char), endl='')
        self._mode = value

    @log_to_debug
    def digital_read(self) -> bool:
        """
        Perform a digital read on the pin.

        :raises IOError: If the pin's current mode does not support digital read
        :raises IOError: If this pin cannot be controlled.
        :return: The digital value of the pin.
        """
        self._check_if_disabled()
        if self.mode not in DIGITAL_READ_MODES:
            raise IOError(f'Digital read is not supported in {self.mode}')
        response = self._serial.query(self._build_command('r'), endl='')
        return (response == '1')

    @log_to_debug
    def digital_write(self, value: bool) -> None:
        """
        Write a digital value to the pin.

        :param value: The value to write to the pin.
        :raises IOError: If the pin's current mode does not support digital write.
        :raises IOError: If this pin cannot be controlled.
        """
        self._check_if_disabled()
        if self.mode not in DIGITAL_WRITE_MODES:
            raise IOError(f'Digital write is not supported in {self.mode}')
        if value:
            self._serial.write(self._build_command('h'), endl='')
        else:
            self._serial.write(self._build_command('l'), endl='')

    @log_to_debug
    def analog_read(self) -> float:
        """
        Get the analog voltage on the pin.

        This is returned in volts. Only pins A0-A5 support analog reads.

        :raises IOError: If the pin or its current mode does not support analog read.
        :raises IOError: If this pin cannot be controlled.
        :return: The analog voltage on the pin, ranges from 0 to 5.
        """
        ADC_MAX = 1023  # 10 bit ADC
        ADC_MIN = 0

        self._check_if_disabled()
        if self.mode not in ANALOG_READ_MODES:
            raise IOError(f'Analog read is not supported in {self.mode}')
        if not self._supports_analog:
            raise IOError('Pin does not support analog read')
        response = self._serial.query(self._build_command('a'), endl='')
        # map the response from the ADC range to the voltage range
        return map_to_float(int(response), ADC_MIN, ADC_MAX, 0.0, 5.0)

    def _check_if_disabled(self) -> None:
        """
        Check if the pin is disabled.

        :raises IOError: If the pin is disabled.
        """
        if self._disabled:
            raise IOError('This pin cannot be controlled.')

    def _map_pin_number(self) -> str:
        """
        Map the pin number to the the serial format.
        Pin numbers are sent as printable ASCII characters, with 0 being 'a'.

        :return: The pin number in the serial format.
        """
        return chr(self._index + ord('a'))

    def _build_command(self, cmd_char: str) -> str:
        """
        Generate the command to send to the board.

        :param command: The command character to send.
        :return: The command string.
        """
        return f'{cmd_char}{self._map_pin_number()}'

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__qualname__} "
            f"index={self._index} analog={self._supports_analog} "
            f"disabled={self._disabled} {self._serial}>"
        )


# PIN:<n>:MODE:GET?
# PIN:<n>:MODE:SET:<value>
# PIN:<n>:DIGITAL:GET?
# PIN:<n>:DIGITAL:SET:<1/0>
# PIN:<n>:ANALOG:GET?
# ULTRASOUND:<pulse>:<echo>:MEASURE?

if __name__ == '__main__':  # pragma: no cover
    arduinos = Arduino._get_supported_boards()
    for serial_num, board in arduinos.items():
        print(serial_num)

        board.pins[4].mode = GPIOPinMode.INPUT
        board.pins[4].mode = GPIOPinMode.INPUT_PULLUP

        # Digital write
        board.pins[13].mode = GPIOPinMode.OUTPUT
        board.pins[13].digital_write(True)
        digital_write_value = board.pins[13].digital_read()
        print(f'Set pin 13 to output and set to {digital_write_value}')

        # Digital read
        board.pins[4].mode = GPIOPinMode.INPUT
        digital_read_value = board.pins[4].digital_read()
        print(f'Input 4 = {digital_read_value}')

        board.pins[5].mode = GPIOPinMode.INPUT_PULLUP
        digital_read_value = board.pins[5].digital_read()
        print(f'Input 5 = {digital_read_value}')

        # Analog read
        board.pins[AnalogPins.A0].mode = GPIOPinMode.INPUT
        analog_read_value = board.pins[AnalogPins.A0].analog_read()
        print(f'Analog input A0 = {analog_read_value}')