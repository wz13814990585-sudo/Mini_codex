"""``merge`` 的综合回归测试。

被测对象：``minicodex/tests/fixtures/autu_abcdefg.py::merge`` —— 一个不依赖
``heapq.merge`` 的手写多路（k-way）稳定归并实现，签名如下：

    merge(*iterables, key=None, reverse=False)

本测试文件于重写 merge 实现时同步重建，覆盖：

* 两个已排序数组合并（含左右大小交错、一侧整体更小等形态）
* 空数组 / 一个为空 / 两个为空 / 空参数调用
* 单元素输入
* 重复元素（多重集并集，保留全部重复项）
* 负数与浮点数
* 降序（reverse=True，输入按逆序排列）
* ``key`` 回调与稳定性（key 相同时先出现者在前）
* 任意可迭代输入（生成器、元组）
* 随机大数组与原生 ``sorted`` / ``heapq.merge`` 参考实现逐一对比
* 输入不被修改（不产生副作用）
* 模块 docstring 中的示例（doctest）
"""

import heapq
import itertools
import random

import pytest

from .fixtures.autu_abcdefg import merge


# ---------------------------------------------------------------- 基础用例
@pytest.mark.parametrize(
    "iterables,expected",
    [
        # 两个普通已排序数组
        (([1, 3, 5], [2, 4, 6]), [1, 2, 3, 4, 5, 6]),
        (([1, 2, 3], [4, 5, 6]), [1, 2, 3, 4, 5, 6]),
        (([4, 5, 6], [1, 2, 3]), [1, 2, 3, 4, 5, 6]),  # 右侧整体更小
        (([1, 2], [3, 4, 5]), [1, 2, 3, 4, 5]),
        (([1, 2, 3, 4, 5], [6]), [1, 2, 3, 4, 5, 6]),
        (([1], [2, 3, 4, 5, 6]), [1, 2, 3, 4, 5, 6]),
        # 空数组场景
        (([], []), []),
        (([], [1, 2, 3]), [1, 2, 3]),
        (([1, 2, 3], []), [1, 2, 3]),
        # 单元素
        (([5], [5]), [5, 5]),
        (([1], []), [1]),
        (([1, 2, 3],), [1, 2, 3]),  # 单个输入
        # 重复元素（多重集合并，保留所有重复项）
        (([1, 1, 2], [1, 3]), [1, 1, 1, 2, 3]),
        (([1, 1, 1], [1, 1]), [1, 1, 1, 1, 1]),
        # 负数
        (([-5, -1, 0], [-3, 2]), [-5, -3, -1, 0, 2]),
        # 浮点数
        (([1.5, 2.5], [1.0, 2.0, 3.0]), [1.0, 1.5, 2.0, 2.5, 3.0]),
        # 多路（k-way）
        (([1, 5, 9], [2, 6], [3, 7, 8]), [1, 2, 3, 5, 6, 7, 8, 9]),
        (([], [1], [2, 3], []), [1, 2, 3]),
        (([1, 3], [1, 4], [2, 5]), [1, 1, 2, 3, 4, 5]),
    ],
)
def test_merge_basic(iterables, expected):
    assert merge(*iterables) == expected


def test_merge_no_args_returns_empty_list():
    assert merge() == []


# ---------------------------------------------------------------- 降序模式
@pytest.mark.parametrize(
    "iterables,expected",
    [
        (([5, 3, 1], [4, 2]), [5, 4, 3, 2, 1]),  # docstring 示例
        (([], []), []),
        (([10, 9, 8], []), [10, 9, 8]),
        (([], [-1, -4]), [-1, -4]),
        (([-1, -2, -3], [-1, -4]), [-1, -1, -2, -3, -4]),  # 负数的逆序输入
        (([9, 7, 5], [8, 6], [4, 1]), [9, 8, 7, 6, 5, 4, 1]),  # k-way 降序
    ],
)
def test_merge_reverse(iterables, expected):
    assert merge(*iterables, reverse=True) == expected


def test_merge_reverse_with_key():
    left = [(2, "l2"), (1, "l1")]
    right = [(2, "r2"), (1, "r1")]
    result = merge(left, right, key=lambda p: p[0], reverse=True)
    assert result == [(2, "l2"), (2, "r2"), (1, "l1"), (1, "r1")]


# ---------------------------------------------------------------- key 与稳定
def test_merge_with_key():
    left = [(1, "a"), (3, "c")]
    right = [(2, "b")]
    assert merge(left, right, key=lambda p: p[0]) == [
        (1, "a"),
        (2, "b"),
        (3, "c"),
    ]


def test_merge_is_stable_on_equal_keys():
    # key 相同时：先出现的输入/元素保持在前（稳定归并）
    left = [(1, "left-1"), (1, "left-2"), (2, "left-3")]
    right = [(1, "right-1"), (2, "right-2")]
    result = merge(left, right, key=lambda p: p[0])
    keys = [p[0] for p in result]
    assert keys == sorted(keys)
    # key == 1 的三个元素必须保持 left-1 < left-2 < right-1 的原始相对顺序
    key1 = [p[1] for p in result if p[0] == 1]
    assert key1 == ["left-1", "left-2", "right-1"]


def test_merge_key_accepts_any_callable():
    import operator

    left = [(1, "y"), (3, "x")]
    right = [(0, "w"), (2, "z")]
    # 输入必须已按 key 升序排列；合并时仅按 itemgetter(0) 比较
    assert merge(left, right, key=operator.itemgetter(0)) == [
        (0, "w"),
        (1, "y"),
        (2, "z"),
        (3, "x"),
    ]


# ---------------------------------------------------------------- 任意可迭代输入
def test_merge_accepts_generators_and_tuples():
    gen1 = (x for x in [1, 4, 7])
    gen2 = (x for x in [2, 5])
    tuple_input = (3, 6, 8)
    assert merge(gen1, gen2, tuple_input) == [1, 2, 3, 4, 5, 6, 7, 8]


# ---------------------------------------------------------------- 无副作用
def test_merge_does_not_mutate_inputs():
    left = [1, 3, 5]
    right = [2, 4]
    original_left = left.copy()
    original_right = right.copy()
    merge(left, right)
    assert left == original_left
    assert right == original_right

    # 嵌套元组元素也不应被改动
    left2 = [(1, "a"), (3, "c")]
    right2 = [(2, "b")]
    merge(left2, right2, key=lambda p: p[0])
    assert left2 == [(1, "a"), (3, "c")]
    assert right2 == [(2, "b")]


# ---------------------------------------------------------------- 随机属性测试
@pytest.mark.parametrize("seed", range(3))
def test_merge_matches_native_merge_on_random_large_arrays(seed):
    """随机大数组：与 ``sorted(left + right)`` 及 ``heapq.merge`` 对比。"""
    rng = random.Random(seed)
    for _ in range(120):
        n = rng.randint(0, 400)
        m = rng.randint(0, 400)
        left = sorted(rng.randint(-1_000_000, 1_000_000) for _ in range(n))
        right = sorted(rng.randint(-1_000_000, 1_000_000) for _ in range(m))

        merged = merge(left, right)

        assert merged == sorted(left + right)
        assert merged == sorted(merged)  # 结果本身有序
        assert len(merged) == n + m  # 元素数量守恒（不丢不重）
        assert merged == list(heapq.merge(left, right))


@pytest.mark.parametrize("seed", range(3))
def test_merge_property_kway_key_reverse(seed):
    """多路 + key + reverse 随机对比 sorted / heapq.merge 参考实现。"""
    rng = random.Random(seed)
    for _ in range(250):
        k = rng.randint(1, 6)
        reverse = rng.random() < 0.5
        use_key = rng.random() < 0.5
        streams = []
        for _ in range(k):
            size = rng.randint(0, 25)
            if use_key:
                data = [
                    (rng.randint(-10, 10), round(rng.random(), 4))
                    for _ in range(size)
                ]
                data.sort(key=lambda p: p[0], reverse=reverse)
            else:
                data = [rng.randint(-100, 100) for _ in range(size)]
                data.sort(reverse=reverse)
            streams.append(data)

        key = (lambda p: p[0]) if use_key else None
        got = merge(*streams, key=key, reverse=reverse)
        expect = sorted(itertools.chain(*streams), key=key, reverse=reverse)

        assert got == expect
        assert got == list(heapq.merge(*streams, key=key, reverse=reverse))
