# weights/ —— 构建时打进镜像的权重目录

把模型权重按 `<模型名>/...` 放进来，构建时会 `COPY weights/ /models/`，容器启动即自带权重
（默认 `LAYA_MODEL_DIR=/models/multilingual`）。

```bash
# 方式一：从 ModelScope 拉（国内直连）
bash scripts/fetch-weights.sh ./weights

# 方式二：已有权重直接拷进来（mlx 与 torch 共用同一份 safetensors）
cp -R ~/.cache/laya-models/multilingual ./weights/
```

目录结构（entrypoint 会校验这几个文件）：

```
weights/multilingual/
├── model.safetensors          # 必需
├── rl_agent_config.json       # 必需
├── encoder/config.json        # 必需
└── tokenizer/{tokenizer.json,tokenizer_config.json}
```

**不想把权重打进镜像**（镜像小 644MB）就让本目录只留 `.gitkeep`，
运行时改用只读挂载：`-v /opt/laya-models:/models:ro`（`scripts/docker-run.sh` 里 `LAYA_MOUNT_MODELS=1`）。

> 本目录内容不进 Git（见 `.gitignore`），只作为构建上下文。
