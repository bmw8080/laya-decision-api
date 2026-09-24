# 贡献指南

谢谢愿意帮忙。这个仓库的目标是**一个稳定、可被别的语言接的决策服务契约**，
所以「契约优先、有实测」比「功能多」重要。

## 提 issue 之前

1. 先看 [README](README.md) 与 `docs/`（语义、SDK、运维都在里面）。
2. 服务是否健康：`curl -s localhost:8765/healthz`；模型是否加载：`curl -s 'localhost:8765/readyz?warm=1'`。
3. 带上可复现的最小请求体（去掉真实业务数据），以及 `/v1/status` 输出。

## 开发

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"       # 后端另装：.[mlx]（macOS）或 .[torch]（Linux）

bash scripts/run.sh                      # 前台起服务（默认 127.0.0.1:8765）
python tests/run_contract_tests.py       # 契约 + 语义 + HTTP 全量测试（不需要 pytest）
```

**没装推理后端也能跑测试**：依赖模型前向的用例会自动标记 `SKIP`，其余照跑，退出码仍为 0
（CI 就是这种情形，不下载 644MB 权重）。本地带后端时应是 `21 passed, 0 failed`。

跨语言 SDK 也要能跑（改了契约就得跟着改）：

```bash
javac -encoding UTF-8 -d out $(find sdk/java/src -name '*.java')
node sdk/ts/demo.ts http://127.0.0.1:8765
npx -p typescript@5.9.2 tsc --noEmit -p sdk/ts
```

## 提交要求

- **契约是兼容性红线**：对 `contract/decision.v1.schema.json` 的破坏性改动必须新开 `v2`，
  不允许在 v1 里改字段含义。
- 改字段/端点 → 同步更新 `src/laya_api/models.py`（OpenAPI 真源）、`tests/golden/cases.json`、`docs/`。
- 新增环境变量 → 同步写进 `.env.example`，并在 `settings.py` 里给默认值（文档与实现必须同源）。
- 提交信息分类写清，便于回溯：`bug修复:` / `系统优化:` / `安全加固:` / `文档更新:` / `重构:`
  （例：`bug修复: 修复 choice 标签重复时未返回 400 的问题`）。
- PR 说明里请写：**改了什么、怎么验证的**（贴命令与真实输出，不接受"应该可以"）。

## 不接受的改动

- 服务端替调用方拍阈值（比如内置「置信度低于 x 就丢给大模型」的隐式行为）。
- 没有实测支撑的性能断言或"兼容性说明"。
- 把 README 内容塞回 `/wiki`（`/wiki` 只渲染 OpenAPI，见 `tests/run_contract_tests.py` 的守门断言）。

## 许可

提交即表示同意以 [Apache License 2.0](LICENSE) 授权你的贡献。
