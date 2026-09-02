import pytest

from autu_abcdefg import merge


@pytest.mark.parametrize(
    "left,right,expected",
    [
        # 普通情况
        ([1, 3, 5], [2, 4, 6], [1, 2, 3, 4, 5, 6]),
        ([1, 2, 3], [4, 5, 6], [1, 2, 3, 4, 5, 6]),
        ([4, 5, 6], [1, 2, 3], [1, 2, 3, 4, 5, 6]),
        # 空输入
        ([], [], []),
        ([], [1, 2, 3], [1, 2, 3]),
        ([1, 2, 3], [], [1, 2, 3]),
        # 长度不同
        ([1, 2, 3, 4, 5], [6], [1, 2, 3, 4, 5, 6]),
        ([1], [2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6]),
        # 重复元素
        ([1, 1, 2], [1, 3], [1, 1, 1, 2, 3]),
        ([1, 1, 1], [1, 1], [1, 1, 1, 1, 1]),
        # 单元素
        ([5], [5], [5, 5]),
        # 负数与浮点数
        ([-5, -1, 0], [-3, 2], [-5, -3, -1, 0, 2]),
        ([1.5, 2.5], [1.0, 2.0, 3.0], [1.0, 1.5, 2.0, 2.5, 3.0]),
    ],
)
def test_merge(left, right, expected):
    assert merge(left, right) == expected


def test_merge_does_not_mutate_inputs():
    left = [1, 3, 5]
    right = [2, 4]
    original_left = left.copy()
    original_right = right.copy()
    merge(left, right)
    assert left == original_left
    assert right == original_right


def test_merge_result_is_sorted():
    import random

    for _ in range(50):
        left = sorted(random.randint(-100, 100) for _ in range(random.randint(0, 20)))
        right = sorted(random.randint(-100, 100) for _ in range(random.randint(0, 20)))
        merged = merge(left, right)
        assert merged == sorted(left + right)
        assert merged == sorted(merged)
