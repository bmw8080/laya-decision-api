## 改了什么

## 怎么验证的

```bash
# 贴真实命令与真实输出（不接受"应该可以"）
```

## 检查项

- [ ] `python tests/run_contract_tests.py` 全绿
- [ ] 契约未做破坏性改动（要改就新开 v2）
- [ ] 新增/修改的环境变量已写进 `.env.example` 与 `settings.py`
- [ ] 涉及字段/端点时，`docs/` 与 `README.md` 已同步
- [ ] `/wiki` 仍然只渲染 OpenAPI（没被塞进 README 内容）
- [ ] 跨语言 SDK 仍可编译/类型检查通过（改了契约时）
