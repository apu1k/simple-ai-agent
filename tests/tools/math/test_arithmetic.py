"""
tests/tools/math/test_arithmetic.py
"""

from tools.math.arithmetic import add, subtract, multiply, divide, power


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(10, 4) == 6


def test_multiply():
    assert multiply(6, 7) == 42


def test_divide():
    assert divide(10, 2) == 5.0


def test_divide_by_zero():
    result = divide(5, 0)
    assert "Error" in str(result)


def test_power():
    assert power(3, 4) == 81
