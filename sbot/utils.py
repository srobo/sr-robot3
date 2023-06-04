import socket
from typing import NamedTuple


class BoardIdentity(NamedTuple):
    manufacturer: str
    board_type: str
    asset_tag: str
    sw_version: str


def map_to_int(x, in_min, in_max, out_min, out_max):
    if (x < in_min) or (x > in_max):
        raise ValueError(f'Value provided outside range, provided:{x}, min:{in_min}, max:{in_max}')
    value = (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min
    return int(value)


def map_to_float(x, in_min, in_max, out_min, out_max, precision=3):
    value = (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min
    return round(value, precision)


def singular(container):
    length = len(container)

    if length == 1:
        return next(container.values())
    elif length == 0:
        raise RuntimeError('No boards of this type found')
    else:
        raise RuntimeError(f'expected only one to be connected, but found {length}')


def obtain_lock(lock_port=10653):
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # We bind to a port to claim it and prevent another process using it
    try:
        lock.bind(("localhost", lock_port))
    except OSError:
        raise OSError('Unable to obtain lock, Is another robot instance already running')

    return lock
