"""Advanced, stable, k-way merge of already-sorted iterables.

本文件提供与之前实现完全等价的 ``merge`` 公共接口：把若干个已经各自
排好序的可迭代对象合并成一个排好序的列表，支持任意数量的输入（k-way）、
``key`` 回调函数以及 ``reverse``（降序）模式，并且保持稳定（相同 key
的元素始终保留“先出现者在前”的相对顺序）。

实现方式说明（与旧版本不同）：

* 不再委托给标准库 :func:`heapq.merge`；
* 也不再使用二叉堆（旧版手写 ``_MergeEntry`` + ``heapq`` 的方案已保留在
  git 历史中：``git show HEAD:minicodex/tests/fixtures/autu_abcdefg.py``）；
* 改用最朴素的 **多指针线性扫描**（双指针归并思想的多路推广）：每一轮
  在若干输入流当前的头部元素中线性挑选“下一个应输出”的元素——升序取
  key 最小者，降序取 key 最大者。只有在“严格更优”时才更新候选，因此
  相同 key 总是保留最早出现的输入流，从而得到与
  ``sorted(itertools.chain(*iterables))`` 一致的稳定结果。
"""


def merge(*iterables, key=None, reverse=False):
    """Merge sorted iterables into one sorted list.

    一个不依赖 ``heapq.merge``、完全手写的多路归并实现：

    * merges *any number* of sorted iterables (k-way merge),
    * accepts arbitrary iterables (lists, tuples, generators, ...),
    * supports a ``key`` function and ``reverse`` (descending) order,
    * is stable and keeps every duplicate element (multiset merge).

    Args:
        *iterables: One or more iterables, each already sorted in ascending
            order (or in descending order when ``reverse=True``).
        key: Optional function that maps each element to its sort key.
        reverse: If True, merge as if everything were sorted from largest
            to smallest.

    Returns:
        A new list containing all elements from ``iterables`` in sorted
        order.

    Examples:
        >>> merge([1, 3, 5], [2, 4, 6])
        [1, 2, 3, 4, 5, 6]
        >>> merge([], [1, 2])
        [1, 2]
        >>> merge([1, 1, 2], [1, 3])
        [1, 1, 1, 2, 3]
        >>> merge([1, 5, 9], [2, 6], [3, 7, 8])          # k-way
        [1, 2, 3, 5, 6, 7, 8, 9]
        >>> merge([(1, "a"), (3, "c")], [(2, "b")], key=lambda p: p[0])
        [(1, 'a'), (2, 'b'), (3, 'c')]
        >>> merge([5, 3, 1], [4, 2], reverse=True)
        [5, 4, 3, 2, 1]
    """
    keyfunc = (lambda x: x) if key is None else key

    # 每个“流”记录三个字段：[当前头部值, 输入序号, 迭代器]。
    # 输入序号用于在 key 相同时维持稳定顺序；空输入从一开始就跳过。
    streams = []
    for order, iterable in enumerate(iterables):
        it = iter(iterable)
        try:
            value = next(it)
        except StopIteration:
            continue
        streams.append([value, order, it])

    result = []
    while streams:
        # 线性扫描所有头部，找出“本轮应当先输出”的流。
        # 只在严格更优（升序更小 / 降序更大）时更新 best，所以当多个流的
        # key 相等时永远保留序号更小（更早出现）的流 —— 稳定归并。
        best_index = 0
        best_key = keyfunc(streams[0][0])
        for index in range(1, len(streams)):
            candidate_key = keyfunc(streams[index][0])
            if (not reverse and candidate_key < best_key) or (
                reverse and candidate_key > best_key
            ):
                best_index = index
                best_key = candidate_key

        best = streams[best_index]
        result.append(best[0])
        try:
            best[0] = next(best[2])  # 该流还有下一个元素，继续参与归并
        except StopIteration:
            streams.pop(best_index)  # 该流已耗尽，移除

    return result
