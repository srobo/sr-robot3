"""KCH Driver."""
from __future__ import annotations

import atexit
import logging
import warnings
from enum import IntEnum, unique
from typing import Optional

from .exceptions import BoardDisconnectionError, IncorrectBoardError
from .serial_wrapper import SerialWrapper
from .utils import IN_SIMULATOR, Board, BoardIdentity, get_simulator_boards

try:
    import RPi.GPIO as GPIO  # isort: ignore
    HAS_HAT = True if not IN_SIMULATOR else False
except ImportError:
    HAS_HAT = False


logger = logging.getLogger(__name__)

# Only used in the simulator
BAUDRATE = 115200


@unique
class RobotLEDs(IntEnum):
    """Mapping of LEDs to GPIO Pins."""

    START = 9

    USER_A_RED = 24
    USER_A_GREEN = 10
    USER_A_BLUE = 25
    USER_B_RED = 27
    USER_B_GREEN = 23
    USER_B_BLUE = 22
    USER_C_RED = 4
    USER_C_GREEN = 18
    USER_C_BLUE = 17

    @classmethod
    def all_leds(cls) -> list[int]:
        """Get all LEDs."""
        return [c.value for c in cls]

    @classmethod
    def user_leds(cls) -> list[tuple[int, int, int]]:
        """Get the user programmable LEDs."""
        return [
            (cls.USER_A_RED, cls.USER_A_GREEN, cls.USER_A_BLUE),
            (cls.USER_B_RED, cls.USER_B_GREEN, cls.USER_B_BLUE),
            (cls.USER_C_RED, cls.USER_C_GREEN, cls.USER_C_BLUE),
        ]


@unique
class UserLED(IntEnum):
    """User Programmable LEDs."""

    A = 0
    B = 1
    C = 2


class Colour():
    """User LED colours."""

    OFF = (False, False, False)
    RED = (True, False, False)
    YELLOW = (True, True, False)
    GREEN = (False, True, False)
    CYAN = (False, True, True)
    BLUE = (False, False, True)
    MAGENTA = (True, False, True)
    WHITE = (True, True, True)


class KCH:
    """KCH Board."""
    __slots__ = ('_leds', '_pwm')

    def __init__(self) -> None:
        self._leds: tuple[LED, ...]

        if HAS_HAT:
            GPIO.setmode(GPIO.BCM)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")

                # If this is not the first time the code is run this init will
                # cause a warning as the gpio are already initialized, we can
                # suppress this as we know the reason behind the warning
                GPIO.setup(RobotLEDs.all_leds(), GPIO.OUT, initial=GPIO.LOW)
            self._pwm: Optional[GPIO.PWM] = None

            # We are not running cleanup so the LED state persists after the code completes,
            # this will cause a warning with `GPIO.setup()` which we can suppress
            # atexit.register(GPIO.cleanup)

            # Cleanup just the start LED to turn it off when the code exits
            # Mypy isn't aware of the version of atexit.register(func, *args)
            atexit.register(GPIO.cleanup, RobotLEDs.START)  # type: ignore[call-arg]

            self._leds = tuple(
                PhysicalLED(rgb_led) for rgb_led in RobotLEDs.user_leds()
            )
        elif IN_SIMULATOR:
            led_server = LedServer.initialise()
            if led_server is not None:
                self._leds = tuple(
                    SimulationLED(v, led_server)
                    for v in range(len(RobotLEDs.user_leds()))
                )
            else:
                self._leds = tuple(
                    LED() for _ in RobotLEDs.user_leds()
                )
        else:
            self._leds = tuple(
                LED() for _ in RobotLEDs.user_leds()
            )

    @property
    def _start(self) -> bool:
        """Get the state of the start LED."""
        return GPIO.input(RobotLEDs.START) if HAS_HAT else False

    @_start.setter
    def _start(self, value: bool) -> None:
        """Set the state of the start LED."""
        if HAS_HAT:
            if self._pwm:
                # stop any flashing the LED is doing
                self._pwm.stop()
                self._pwm = None
            GPIO.output(RobotLEDs.START, GPIO.HIGH if value else GPIO.LOW)

    def _flash_start(self) -> None:
        """Set the start LED flashing at 1Hz."""
        if HAS_HAT:
            self._pwm = GPIO.PWM(RobotLEDs.START, 1)
            self._pwm.start(50)

    @property
    def leds(self) -> tuple['LED', ...]:
        """User programmable LEDs."""
        return self._leds


class LED:
    """
    User programmable LED.

    This is a dummy class to handle the case where this is run on neither the
    Raspberry Pi nor the simulator.
    As such, this class does nothing.
    """
    __slots__ = ('_led',)

    @property
    def r(self) -> bool:
        """Get the state of the Red LED segment."""
        return False

    @r.setter
    def r(self, value: bool) -> None:
        """Set the state of the Red LED segment."""

    @property
    def g(self) -> bool:
        """Get the state of the Green LED segment."""
        return False

    @g.setter
    def g(self, value: bool) -> None:
        """Set the state of the Green LED segment."""

    @property
    def b(self) -> bool:
        """Get the state of the Blue LED segment."""
        return False

    @b.setter
    def b(self, value: bool) -> None:
        """Set the state of the Blue LED segment."""

    @property
    def colour(self) -> tuple[bool, bool, bool]:
        """Get the colour of the user LED."""
        return False, False, False

    @colour.setter
    def colour(self, value: tuple[bool, bool, bool]) -> None:
        """Set the colour of the user LED."""
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            raise ValueError("The LED requires 3 values for it's colour")


class PhysicalLED(LED):
    """
    User programmable LED.

    Used when running on the Raspberry Pi to control the actual LEDs.
    """
    __slots__ = ('_led',)

    def __init__(self, led: tuple[int, int, int]):
        self._led = led

    @property
    def r(self) -> bool:
        """Get the state of the Red LED segment."""
        return GPIO.input(self._led[0])

    @r.setter
    def r(self, value: bool) -> None:
        """Set the state of the Red LED segment."""
        GPIO.output(self._led[0], GPIO.HIGH if value else GPIO.LOW)

    @property
    def g(self) -> bool:
        """Get the state of the Green LED segment."""
        return GPIO.input(self._led[1])

    @g.setter
    def g(self, value: bool) -> None:
        """Set the state of the Green LED segment."""
        GPIO.output(self._led[1], GPIO.HIGH if value else GPIO.LOW)

    @property
    def b(self) -> bool:
        """Get the state of the Blue LED segment."""
        return GPIO.input(self._led[2])

    @b.setter
    def b(self, value: bool) -> None:
        """Set the state of the Blue LED segment."""
        GPIO.output(self._led[2], GPIO.HIGH if value else GPIO.LOW)

    @property
    def colour(self) -> tuple[bool, bool, bool]:
        """Get the colour of the user LED."""
        return (
            GPIO.input(self._led[0]),
            GPIO.input(self._led[1]),
            GPIO.input(self._led[2]),
        )

    @colour.setter
    def colour(self, value: tuple[bool, bool, bool]) -> None:
        """Set the colour of the user LED."""
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            raise ValueError("The LED requires 3 values for it's colour")

        GPIO.output(
            self._led,
            tuple(
                GPIO.HIGH if v else GPIO.LOW for v in value
            ),
        )


class LedServer(Board):
    """
    LED control over a socket.

    Used when running in the simulator to control the simulated LEDs.
    """

    @staticmethod
    def get_board_type() -> str:
        """
        Return the type of the board.

        :return: The literal string 'KCHv1B'.
        """
        return 'KCHv1B'

    def __init__(
        self,
        serial_port: str,
        initial_identity: BoardIdentity | None = None,
    ) -> None:
        if initial_identity is None:
            initial_identity = BoardIdentity()
        self._serial = SerialWrapper(
            serial_port,
            BAUDRATE,
            identity=initial_identity,
        )

        self._identity = self.identify()
        if self._identity.board_type != self.get_board_type():
            raise IncorrectBoardError(self._identity.board_type, self.get_board_type())
        self._serial.set_identity(self._identity)

        # Reset the board to a known state
        self._serial.write('*RESET')

    @classmethod
    def initialise(cls) -> 'LedServer' | None:
        """Initialise the LED server using simulator discovery."""
        # The filter here is the name of the emulated board in the simulator
        boards = get_simulator_boards('LedBoard')

        if not boards:
            return None

        board_info = boards[0]

        # Create board identity from the info given
        initial_identity = BoardIdentity(
            manufacturer='sbot_simulator',
            board_type=board_info.type_str,
            asset_tag=board_info.serial_number,
        )

        try:
            board = cls(board_info.url, initial_identity)
        except BoardDisconnectionError:
            logger.warning(
                f"Simulator specified LED board at port {board_info.url!r}, "
                "could not be identified. Ignoring this device")
            return None
        except IncorrectBoardError as err:
            logger.warning(
                f"Board returned type {err.returned_type!r}, "
                f"expected {err.expected_type!r}. Ignoring this device")
            return None

        return board

    def identify(self) -> BoardIdentity:
        """
        Get the identity of the board.

        :return: The identity of the board.
        """
        response = self._serial.query('*IDN?')
        return BoardIdentity(*response.split(':'))

    def set_leds(self, led_num: int, value: tuple[bool, bool, bool]) -> None:
        """Set the colour of the LED."""
        self._serial.write(f'LED:{led_num}:SET:{value[0]:d}:{value[1]:d}:{value[2]:d}')

    def get_leds(self, led_num: int) -> tuple[bool, bool, bool]:
        """Get the colour of the LED."""
        response = self._serial.query(f'LED:{led_num}:GET?')
        red, green, blue = response.split(':')
        return bool(int(red)), bool(int(green)), bool(int(blue))


class SimulationLED(LED):
    """
    User programmable LED.

    Used when running in the simulator to control the simulated LEDs.
    """
    __slots__ = ('_led_num', '_server')

    def __init__(self, led_num: int, server: LedServer) -> None:
        self._led_num = led_num
        self._server = server

    @property
    def r(self) -> bool:
        """Get the state of the Red LED segment."""
        return self._server.get_leds(self._led_num)[0]

    @r.setter
    def r(self, value: bool) -> None:
        """Set the state of the Red LED segment."""
        # Fetch the current state of the LED so we can update only the red value
        current = self._server.get_leds(self._led_num)
        self._server.set_leds(self._led_num, (value, current[1], current[2]))

    @property
    def g(self) -> bool:
        """Get the state of the Green LED segment."""
        return self._server.get_leds(self._led_num)[1]

    @g.setter
    def g(self, value: bool) -> None:
        """Set the state of the Green LED segment."""
        # Fetch the current state of the LED so we can update only the green value
        current = self._server.get_leds(self._led_num)
        self._server.set_leds(self._led_num, (current[0], value, current[2]))

    @property
    def b(self) -> bool:
        """Get the state of the Blue LED segment."""
        return self._server.get_leds(self._led_num)[2]

    @b.setter
    def b(self, value: bool) -> None:
        """Set the state of the Blue LED segment."""
        # Fetch the current state of the LED so we can update only the blue value
        current = self._server.get_leds(self._led_num)
        self._server.set_leds(self._led_num, (current[0], current[1], value))

    @property
    def colour(self) -> tuple[bool, bool, bool]:
        """Get the colour of the user LED."""
        return self._server.get_leds(self._led_num)

    @colour.setter
    def colour(self, value: tuple[bool, bool, bool]) -> None:
        """Set the colour of the user LED."""
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            raise ValueError("The LED requires 3 values for it's colour")

        self._server.set_leds(self._led_num, value)
