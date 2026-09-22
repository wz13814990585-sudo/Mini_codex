# 计算器演示工作区

**简体中文** · [English](README.en.md)

这个刻意保持简单的项目用于 MiniCodex 五分钟演示。运行 Agent 前请复制目录，避免修改仓库中的原始示例。

## 初始状态

- `src/calculator.py` 提供可工作的 `add` 与 `divide`。
- `tests/test_calculator.py` 覆盖普通加法和除法。
- `divide(a, b)` 尚未把除零转换为清晰的领域错误，也没有对应回归测试。

## 建议任务

```text
修改 src/calculator.py，让 divide(a, b) 在 b 为 0 时抛出 ValueError，并在 tests/test_calculator.py 增加回归测试，然后运行测试。
```

## 运行

```bash
demo_dir="$(mktemp -d)/calculator_demo"
cp -R examples/calculator_demo "$demo_dir"

minicodex run \
  "修改 src/calculator.py，让 divide(a, b) 在 b 为 0 时抛出 ValueError，并在 tests/test_calculator.py 增加回归测试，然后运行测试。" \
  --workspace "$demo_dir" \
  --output verbose

python -m pytest -q "$demo_dir/tests"
```

预期结果是 Agent 修改实现与测试，并在最终报告中列出变更文件和通过的验证。
