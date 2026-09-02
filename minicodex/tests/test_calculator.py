import pytest

from calculator import add, divide


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (2, 3, 5),                 # 两个正整数
        (-2, 3, 1),                # 正负数相加
        (-2, -3, -5),              # 两个负数
        (0, 0, 0),                 # 两个零
        (0, 7, 7),                 # 与零相加
        (1.5, 2.25, 3.75),         # 浮点数
        (1000000, 2000000, 3000000),  # 大整数
    ],
)
def test_add(a, b, expected):
    assert add(a, b) == expected


def test_divide():
    assert divide(10, 2) == 5


def test_divide_by_zero():
    with pytest.raises(ValueError):
        divide(10, 0)