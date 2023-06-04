import logging
import threading

import serial


def retry(times, exceptions):
    def decorator(func):
        def retryfn(*args, **kwargs):
            attempt = 0
            while attempt < times:
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    attempt += 1
            return func(*args, **kwargs)
        return retryfn
    return decorator


class SerialWrapper:
    def __init__(self, port, baud, timeout=0.5):
        self.logger = logging.getLogger(__name__)

        self._lock = threading.Lock()

        # Serial port parameters
        self.port = port
        self.baud = baud
        self.timeout = timeout

        # pyserial serial port
        self.serial = None

        # Current port state
        self.connected = False

    def start(self):
        self._connect()

    def stop(self):
        self._disconnect()

    @retry(times=3, exceptions=RuntimeError)
    def query(self, data):
        with self._lock:
            if not self.connected:
                if not self._connect():
                    print('Error')
                    raise RuntimeError('Board not connected')

            try:
                cmd = data + '\n'
                self.serial.write(cmd.encode())
                response = self.serial.readline()
                if b'\n' not in response:
                    raise serial.SerialException('readline timeout')
            except serial.SerialException:
                # Serial port was closed
                # Make sure port is cleaned up
                self._disconnect()
                raise RuntimeError('Board disconnected')

            return response.decode().strip()

    def write(self, data):
        with self._lock:
            response = self.query(data)
            if 'NACK' in response:
                _, error_msg = response.split(':', maxsplit=1)
                raise RuntimeError(error_msg)

    def _connect(self):
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=self.timeout
            )
            self.connected = True
        except serial.SerialException:
            return False

        self.logger.info('Connected')
        return True

    def _disconnect(self):
        if self.serial is not None:
            self.logger.info('Disconnected')
            self.connected = False
            self.serial.close()
            self.serial = None
