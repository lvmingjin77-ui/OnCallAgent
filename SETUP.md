# 运行说明

## 1. conda 环境

如果你本机已经有 `oncallAgent`，直接：

```bash
conda activate oncallAgent
cd /Users/susu/Desktop/月之暗面/coding-exam-main/question-1
```

如果要新建环境，执行：

```bash
conda create -n oncallAgent python=3.10 -y
conda activate oncallAgent
pip install numpy torch sentence-transformers huggingface_hub
```

## 2. 拉取 Phase 2 本地模型

项目默认优先读取：

```text
.local_models/bge-base-zh-v1.5
```

直接执行：

```bash
cd /Users/susu/Desktop/月之暗面/coding-exam-main/question-1
mkdir -p .local_models
huggingface-cli download BAAI/bge-base-zh-v1.5 \
  --local-dir .local_models/bge-base-zh-v1.5
```

拉取完成后，代码会自动优先使用这个本地目录，不需要额外改 `PHASE2_MODEL_NAME`。

## 3. 构建 Phase 2 索引

```bash
conda activate oncallAgent
cd /Users/susu/Desktop/月之暗面/coding-exam-main/question-1
python -m phase2.rebuild_index
```

成功后会生成：

```text
.phase2_index/
```

## 4. 配置 Phase 3 的 LLM API

编辑项目根目录的 [llm_config.json](/Users/susu/Desktop/月之暗面/coding-exam-main/question-1/llm_config.json)：

```json
{
  "api_key": "YOUR_API_KEY",
  "base_url": "https://openrouter.fans/v1",
  "model": "claude-opus-4-6",
  "openrouter_http_referer": "http://127.0.0.1:8000",
  "openrouter_app_title": "On-Call Assistant"
}
```

最关键的是这 3 项：

- `api_key`
- `base_url`
- `model`

如果你的网关不支持 `claude-opus-4-6`，就改成该网关实际支持的模型名。

## 5. 检查 API 是否可用

```bash
conda activate oncallAgent
cd /Users/susu/Desktop/月之暗面/coding-exam-main/question-1
python scripts/check_llm_api.py
```

## 6. 启动项目

```bash
conda activate oncallAgent
cd /Users/susu/Desktop/月之暗面/coding-exam-main/question-1
python app.py
```

默认地址：

- `http://127.0.0.1:8000/v1`
- `http://127.0.0.1:8000/v2`
- `http://127.0.0.1:8000/v3`

如果要改端口：

```bash
HOST=127.0.0.1 PORT=8001 python app.py
```

## 7. 一次跑通的最短命令顺序

```bash
conda activate oncallAgent
cd /Users/susu/Desktop/月之暗面/coding-exam-main/question-1
mkdir -p .local_models
huggingface-cli download BAAI/bge-base-zh-v1.5 --local-dir .local_models/bge-base-zh-v1.5
python -m phase2.rebuild_index
python scripts/check_llm_api.py
python app.py
```

## 8. 当前实现要点

- `v1` 只依赖 Python 标准库
- `v2` 依赖 `numpy + torch + sentence-transformers + 本地/可下载 BGE 模型`
- `v3` 当前会先用 `v2` 语义检索筛候选文件，再调用 LLM 做 `readFile` 工具问答，所以 `v3` 也依赖 `v2` 环境可用
