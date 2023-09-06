"""Test log_to_debug functions."""
import logging

from sr.robot3.logging import log_to_debug


def test_log_to_debug(caplog):
    """Test log_to_debug."""
    @log_to_debug
    def func(a, b, c):
        return a + b + c

    with caplog.at_level("DEBUG"):
        func(1, 2, c=3)

    assert caplog.record_tuples == [
        (
            "tests.test_logging", logging.DEBUG,
            "Calling test_log_to_debug.<locals>.func(1, 2, c=3)"
        ),
        (
            "tests.test_logging", logging.DEBUG,
            "'test_log_to_debug.<locals>.func' returned 6"
        ),
    ]


def test_log_to_debug_setter(caplog):
    """Test log_to_debug with setter."""
    @log_to_debug(setter=True)
    def func(a, b, c):
        return a + b + c

    with caplog.at_level("DEBUG"):
        func(1, 2, c=3)

    assert caplog.record_tuples == [
        (
            "tests.test_logging", logging.DEBUG,
            "Calling setter test_log_to_debug_setter.<locals>.func(1, 2, c=3)"
        ),
    ]
