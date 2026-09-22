# Calculator demo workspace

[简体中文](README.md) · **English**

This deliberately small project powers the five-minute MiniCodex demo. Copy the directory before running the agent so the repository example stays unchanged.

## Initial state

- `src/calculator.py` provides working `add` and `divide` functions.
- `tests/test_calculator.py` covers ordinary addition and division.
- `divide(a, b)` does not yet convert division by zero into a clear domain error, and no regression test covers it.

## Suggested task

```text
Update src/calculator.py so divide(a, b) raises ValueError when b is zero, add a regression test to tests/test_calculator.py, and run the tests.
```

## Run

```bash
demo_dir="$(mktemp -d)/calculator_demo"
cp -R examples/calculator_demo "$demo_dir"

minicodex run \
  "Update src/calculator.py so divide(a, b) raises ValueError when b is zero, add a regression test to tests/test_calculator.py, and run the tests." \
  --workspace "$demo_dir" \
  --output verbose

python -m pytest -q "$demo_dir/tests"
```

The expected result is an implementation and test update, followed by a final report listing changed files and passing validation.
