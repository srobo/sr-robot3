"""The main entry point for the sr-robot3 package."""
from __future__ import annotations

import itertools
import logging
import os
import time
from pathlib import Path
from socket import socket
from types import MappingProxyType
from typing import Mapping, Optional

from . import game_specific, timeout
from ._version import __version__
from .arduino import Arduino
from .astoria import Metadata, RobotMode, init_astoria_mqtt
from .camera import AprilCamera, _setup_cameras
from .exceptions import MetadataNotReadyError
from .kch import KCH
from .logging import log_to_debug, setup_logging
from .motor_board import MotorBoard
from .power_board import Note, PowerBoard
from .raw_serial import RawSerial
from .servo_board import ServoBoard
from .simulator.time_server import TimeServer
from .utils import IN_SIMULATOR, ensure_atexit_on_term, obtain_lock, singular

logger = logging.getLogger(__name__)


class Robot:
    """
    The main robot class that provides access to all the boards.

    There can be only one instance of this class active in your operating
    system at a time, creating a second instance will raise an OSError.

    :param debug: Enable debug logging to the console, defaults to False
    :param wait_for_start: Wait in the constructor until the start button is pressed,
        defaults to True
    :param trace_logging: Enable trace level logging to the console, defaults to False
    :param ignored_arduinos: A list of Arduino serial numbers to avoid connecting to
    :param manual_boards: A dictionary of board types to a list of serial port paths
        to allow for connecting to boards that are not automatically detected, defaults to None
    :param raw_ports: A list of serial number, baudrate tuples to try connecting to.
    :param no_powerboard: If True, initialize the robot without a powerboard, defaults to False
    """
    __slots__ = (
        '_lock', '_metadata', '_power_board', '_motor_boards', '_servo_boards',
        '_arduinos', '_cameras', '_mqtt', '_astoria', '_kch', '_raw_ports',
        '_time_server', '_no_powerboard',
    )

    def __init__(
        self,
        *,
        debug: bool = False,
        wait_for_start: bool = True,
        trace_logging: bool = False,
        ignored_arduinos: Optional[list[str]] = None,
        manual_boards: Optional[dict[str, list[str]]] = None,
        raw_ports: Optional[list[tuple[str, int]]] = None,
        no_powerboard: bool = False,
    ) -> None:
        self._lock: TimeServer | socket | None
        if IN_SIMULATOR:
            self._lock = TimeServer.initialise()
            if self._lock is None:
                raise OSError(
                    'Unable to obtain lock, Is another robot instance already running?'
                )
        else:
            self._lock = obtain_lock()
        self._metadata: Optional[Metadata] = None
        self._no_powerboard = no_powerboard

        setup_logging(debug, trace_logging)
        ensure_atexit_on_term()

        logger.info(f"sr.robot3 version {__version__}")

        if IN_SIMULATOR:
            self._mqtt = None
            self._astoria = None
        else:
            self._mqtt, self._astoria = init_astoria_mqtt()

        if manual_boards:
            self._init_power_board(manual_boards.get(PowerBoard.get_board_type(), []))
        else:
            self._init_power_board()
        self._init_aux_boards(manual_boards, ignored_arduinos, raw_ports)
        self._init_camera()
        self._log_connected_boards()

        if wait_for_start:
            logger.debug("Waiting for start button.")
            self.wait_start()
        else:
            logger.debug("Not waiting for start button.")

    def _init_power_board(self, manual_boards: Optional[list[str]] = None) -> None:
        """
        Locate the PowerBoard and enable all the outputs to power the other boards.

        :param manual_boards: Serial port paths to also check for power boards,
            defaults to None
        :raises RuntimeError: If exactly one PowerBoard is not found
        """
        if self._no_powerboard:
            return

        power_boards = PowerBoard._get_supported_boards(manual_boards, sleep_fn=self.sleep)
        self._power_board = singular(power_boards)

        # Enable all the outputs, so that we can find other boards.
        self._power_board.outputs.power_on()

    def _init_aux_boards(
        self,
        manual_boards: Optional[dict[str, list[str]]] = None,
        ignored_arduinos: Optional[list[str]] = None,
        raw_ports: Optional[list[tuple[str, int]]] = None,
    ) -> None:
        """
        Locate the motor boards, servo boards, and Arduinos.

        All boards are located automatically, but additional serial ports can be
        provided using the manual_boards parameter. Located boards are queried for
        their identity and firmware version.

        :param manual_boards:  A dictionary of board types to a list of additional
            serial port paths that should be checked for boards of that type, defaults to None
        :param ignored_arduinos: A list of Arduino serial numbers to avoid connecting to
        :param raw_ports: A list of serial number, baudrate tuples to try connecting to
        """
        self._raw_ports: MappingProxyType[str, RawSerial] = MappingProxyType({})
        if manual_boards is None:
            manual_boards = {}

        manual_motorboards = manual_boards.get(MotorBoard.get_board_type(), [])
        manual_servoboards = manual_boards.get(ServoBoard.get_board_type(), [])
        manual_arduinos = manual_boards.get(Arduino.get_board_type(), [])

        self._kch = KCH()
        self._motor_boards = MotorBoard._get_supported_boards(manual_motorboards)
        self._servo_boards = ServoBoard._get_supported_boards(manual_servoboards)
        self._arduinos = Arduino._get_supported_boards(manual_arduinos, ignored_arduinos)
        if raw_ports:
            if not IN_SIMULATOR:
                self._raw_ports = RawSerial._get_supported_boards(raw_ports)
            else:
                logger.warning("Raw ports are not available in the simulator.")

    def _init_camera(self) -> None:
        """
        Locate cameras that we have calibration data for.

        These cameras are used for AprilTag detection and provide location data of
        markers in its field of view.
        """
        if IN_SIMULATOR:
            publish_fn = None
        else:
            assert self._mqtt is not None
            publish_fn = self._mqtt.wrapped_publish

        self._cameras = MappingProxyType(_setup_cameras(
            game_specific.MARKER_SIZES,
            publish_fn,
        ))

    def _log_connected_boards(self) -> None:
        """
        Log the board types and serial numbers of all the boards connected to the robot.

        Firmware versions are also logged at debug level.
        """
        # we only have one power board so make it iterable
        power_board = [] if self._no_powerboard else [self.power_board]
        boards = itertools.chain(
            power_board,
            self.motor_boards.values(),
            self.servo_boards.values(),
            self.arduinos.values(),
            self._cameras.values(),
            self.raw_serial_devices.values(),
        )
        for board in boards:
            identity = board.identify()
            board_type = board.__class__.__name__
            logger.info(f"Found {board_type}, serial: {identity.asset_tag}")
            logger.debug(
                f"Firmware Version of {identity.asset_tag}: {identity.sw_version}, "
                f"reported type: {identity.board_type}",
            )

    @property
    def kch(self) -> KCH:
        """
        Access the Raspberry Pi hat, including user-accessible LEDs.

        :returns: The KCH object
        """
        return self._kch

    @property
    def power_board(self) -> PowerBoard:
        """
        Access the power board connected to the robot.

        :return: The power board object
        """
        if self._no_powerboard:
            raise RuntimeError("No power board was initialized")

        return self._power_board

    @property
    def motor_boards(self) -> Mapping[str, MotorBoard]:
        """
        Access the motor boards connected to the robot.

        These are indexed by their serial number.

        :return: A mapping of serial numbers to motor boards
        """
        return self._motor_boards

    @property
    def motor_board(self) -> MotorBoard:
        """
        Access the motor board connected to the robot.

        This can only be used if there is exactly one motor board connected.

        :return: The motor board object
        :raises RuntimeError: If there is not exactly one motor board connected
        """
        return singular(self._motor_boards)

    @property
    def servo_boards(self) -> Mapping[str, ServoBoard]:
        """
        Access the servo boards connected to the robot.

        These are indexed by their serial number.

        :return: A mapping of serial numbers to servo boards
        """
        return self._servo_boards

    @property
    def servo_board(self) -> ServoBoard:
        """
        Access the servo board connected to the robot.

        This can only be used if there is exactly one servo board connected.

        :return: The servo board object
        :raises RuntimeError: If there is not exactly one servo board connected
        """
        return singular(self._servo_boards)

    @property
    def arduinos(self) -> Mapping[str, Arduino]:
        """
        Access the Arduinos connected to the robot.

        These are indexed by their serial number.

        :return: A mapping of serial numbers to Arduinos
        """
        return self._arduinos

    @property
    def arduino(self) -> Arduino:
        """
        Access the Arduino connected to the robot.

        This can only be used if there is exactly one Arduino connected.

        :return: The Arduino object
        :raises RuntimeError: If there is not exactly one Arduino connected
        """
        return singular(self._arduinos)

    @property
    def camera(self) -> AprilCamera:
        """
        Access the camera connected to the robot.

        This can only be used if there is exactly one camera connected.
        The robot class currently only supports one camera.

        :return: The camera object
        :raises RuntimeError: If there is not exactly one camera connected
        """
        return singular(self._cameras)

    @property
    def raw_serial_devices(self) -> Mapping[str, RawSerial]:
        """
        Access the raw serial devices connected to the robot.

        These are populated by the `raw_ports` parameter of the constructor,
        and are indexed by their serial number.

        :return: A mapping of serial numbers to raw serial devices
        """
        return self._raw_ports

    @log_to_debug
    def sleep(self, secs: float) -> None:
        """
        Sleep for a number of seconds.

        This is a convenience method that should be used instead of time.sleep()
        to make your code compatible with the simulator.

        :param secs: The number of seconds to sleep for
        """
        if IN_SIMULATOR:
            assert isinstance(self._lock, TimeServer)
            self._lock.sleep(secs)
        else:
            time.sleep(secs)

    @log_to_debug
    def time(self) -> float:
        """
        Get the number of seconds since the Unix Epoch.

        This is a convenience method that should be used instead of time.time()
        to make your code compatible with the simulator.

        NOTE: The robot's clock resets each time the robot is restarted, so this
        will not be the correct actual time but can be used to measure elapsed time.

        :returns: the number of seconds since the Unix Epoch.
        """
        if IN_SIMULATOR:
            assert isinstance(self._lock, TimeServer)
            return self._lock.get_time()
        else:
            return time.time()

    @property
    @log_to_debug
    def arena(self) -> str:
        """
        Get the arena that the robot is in.

        :return: The robot's arena
        :raises MetadataNotReadyError: If the start button has not been pressed yet
        """
        if self._metadata is None:
            raise MetadataNotReadyError()
        else:
            return self._metadata.arena

    @property
    @log_to_debug
    def zone(self) -> int:
        """
        Get the zone that the robot is in.

        :return: The robot's zone number
        :raises MetadataNotReadyError: If the start button has not been pressed yet
        """
        if self._metadata is None:
            raise MetadataNotReadyError()
        else:
            return self._metadata.zone

    @property
    @log_to_debug
    def mode(self) -> RobotMode:
        """
        Get the mode that the robot is in.

        :return: The robot's current mode
        :raises MetadataNotReadyError: If the start button has not been pressed yet
        """
        if self._metadata is None:
            raise MetadataNotReadyError()
        else:
            return self._metadata.mode

    @property
    def usbkey(self) -> Path:
        """
        The path of the USB code drive.

        :returns: path to the mountpoint of the USB code drive.
        """
        if IN_SIMULATOR:
            return Path(os.environ['SBOT_USBKEY_PATH'])
        else:
            assert self._astoria is not None
            return self._astoria.fetch_mount_path()

    @property
    def is_simulated(self) -> bool:
        """
        Determine whether the robot is simulated.

        :returns: True if the robot is simulated. False otherwise.
        """
        return IN_SIMULATOR

    @log_to_debug
    def wait_start(self) -> None:
        """
        Wait for the start button to be pressed.

        The power board will beep once when waiting for the start button.
        The power board's run LED will flash while waiting for the start button.
        Once the start button is pressed, the metadata will be loaded and the timeout
        will start if in competition mode.
        """
        def null_button_pressed() -> bool:
            return False

        if self._no_powerboard:
            # null out the start button function
            start_button_pressed = null_button_pressed
        else:
            start_button_pressed = self.power_board._start_button

        if IN_SIMULATOR:
            remote_start_pressed = null_button_pressed
        else:
            assert self._astoria is not None
            remote_start_pressed = self._astoria.get_start_button_pressed

        # ignore previous button presses
        _ = start_button_pressed()
        _ = remote_start_pressed()
        logger.info('Waiting for start button.')

        if not self._no_powerboard:
            self.power_board.piezo.buzz(Note.A6, 0.1)
            self.power_board._run_led.flash()
        self.kch._flash_start()

        while not start_button_pressed() or remote_start_pressed():
            self.sleep(0.1)
        logger.info("Start signal received; continuing.")
        if not self._no_powerboard:
            self.power_board._run_led.on()
        self.kch._start = False

        if IN_SIMULATOR:
            self._metadata = Metadata.parse_file(
                Path(os.environ['SBOT_METADATA_PATH']) / 'astoria.json'
            )
        else:
            assert self._astoria is not None
            # Load the latest metadata that we have received over MQTT
            self._metadata = self._astoria.fetch_current_metadata()

        # Simulator timeout is handled by the simulator supervisor
        if self._metadata.game_timeout and not IN_SIMULATOR:
            timeout.kill_after_delay(self._metadata.game_timeout)
