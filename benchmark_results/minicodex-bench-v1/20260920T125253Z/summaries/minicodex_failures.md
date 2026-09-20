# 失败报告

共 8 次任务/运行；1 次通过；7 次失败。

## environment_failure (1)

- create_fastapi_login 运行 1: max_steps （步数=20，工具=21，llm=25，trace=benchmark_results/minicodex-bench-v1/20260920T125253Z/traces/minicodex/run_001/create_fastapi_login.jsonl）

## tool_error (1)

- already_health_ok 运行 1: max_steps （步数=20，工具=8，llm=22，trace=benchmark_results/minicodex-bench-v1/20260920T125253Z/traces/minicodex/run_001/already_health_ok.jsonl）

## wrong_validation_target (5)

- create_calculator_service 运行 1: max_steps （步数=20，工具=13，llm=23，trace=benchmark_results/minicodex-bench-v1/20260920T125253Z/traces/minicodex/run_001/create_calculator_service.jsonl）
- create_web_counter 运行 1: 有界复核后验证仍不稳定；无法据此得出回归结论。 （步数=16，工具=17，llm=19，trace=benchmark_results/minicodex-bench-v1/20260920T125253Z/traces/minicodex/run_001/create_web_counter.jsonl）
- modify_web_keyboard 运行 1: max_steps （步数=20，工具=16，llm=24，trace=benchmark_results/minicodex-bench-v1/20260920T125253Z/traces/minicodex/run_001/modify_web_keyboard.jsonl）
- modify_typescript_sum 运行 1: max_steps （步数=20，工具=17，llm=24，trace=benchmark_results/minicodex-bench-v1/20260920T125253Z/traces/minicodex/run_001/modify_typescript_sum.jsonl）
- fix_python_sort_key 运行 1: 有界复核后验证仍不稳定；无法据此得出回归结论。 （步数=9，工具=10，llm=12，trace=benchmark_results/minicodex-bench-v1/20260920T125253Z/traces/minicodex/run_001/fix_python_sort_key.jsonl）
