# 复现说明

本文档说明如何在本地复现并验证本仓库的 On-Call 助手（Phase 1～3）。与 [README.md](./README.md) 中的题目要求一致，便于阅卷或自查。

## 1. 环境要求

- **Python**：建议 3.10 及以上（标准库 `wsgiref` 即可运行 HTTP 服务）。
- **工作目录**：仓库根目录（含 `app.py`、`data/`、`phase1/`、`phase2/`、`phase3/`）。

可选依赖：

- **Phase 2 语义搜索**：需本地向量化模型与索引；未安装或未建索引时，`/v2` 会返回「不可用」类提示，属预期。
- **Phase 3 Agent**：需可用的 OpenAI 兼容 Chat Completions 接口（如 OpenRouter 或自建网关），并在配置中提供 **API Key** 与 **模型 ID**。

## 2. 启动 Web 服务

在仓库根目录执行：

```bash
cd /path/to/question-1
python3 app.py
```

默认监听 **`http://127.0.0.1:8000`**。可通过环境变量修改：

| 变量   | 含义     | 默认        |
| ------ | -------- | ----------- |
| `HOST` | 绑定地址 | `127.0.0.1` |
| `PORT` | 端口     | `8000`      |

启动后终端会提示 `/v1`、`/v2`、`/v3` 等路由前缀。

## 3. Phase 1：关键词检索

### 3.1 浏览器

浏览器打开：`http://127.0.0.1:8000/v1` ，在页面中输入关键词搜索。

### 3.2 命令行（与 README 验证表对应）

```bash
curl -sS 'http://127.0.0.1:8000/v1/search?q=OOM' | python3 -m json.tool
curl -sS 'http://127.0.0.1:8000/v1/search?q=%E6%95%85%E9%9A%9C' | python3 -m json.tool
curl -sS 'http://127.0.0.1:8000/v1/search?q=replication' | python3 -m json.tool
curl -sS 'http://127.0.0.1:8000/v1/search?q=CDN' | python3 -m json.tool
curl -sS 'http://127.0.0.1:8000/v1/search?q=%26' | python3 -m json.tool
```

期望要点（详见 README）：`OOM` 命中 sop-001；`故障` 多结果；`replication` 无正文命中；`CDN` 含 sop-003、sop-010；`q=&` 对 `&` 的编码查询能命中正文中含 `&` 的文档。

## 4. Phase 2：语义搜索

### 4.1 构建索引（首次或 `data/` 变更后）

需已安装 Phase 2 所用嵌入依赖（以你本机 `phase2` 模块及 `LocalBGEEmbeddingProvider` 为准），然后在仓库根目录执行：

```bash
python3 -m phase2.rebuild_index
```

索引默认目录为项目下的 **`.phase2_index`**，也可通过环境变量 **`PHASE2_INDEX_DIR`** 指定。

### 4.2 验证 API

```bash
curl -sS 'http://127.0.0.1:8000/v2/search?q=%E6%9C%8D%E5%8A%A1%E5%99%A8%E6%8C%82%E4%BA%86' | python3 -m json.tool
curl -sS 'http://127.0.0.1:8000/v2/search?q=%E9%BB%91%E5%AE%A2%E6%94%BB%E5%87%BB' | python3 -m json.tool
```

浏览器打开：`http://127.0.0.1:8000/v2` 。

若未建索引或依赖缺失，接口会返回说明性错误信息；先完成 4.1 再复现语义结果。

## 5. Phase 3：On-Call Agent

### 5.1 配置 LLM

在项目根目录准备 **`llm_config.json`**（可参考仓库内示例结构），至少包含：

- `api_key`：网关要求的密钥（也可用环境变量 **`OPENROUTER_API_KEY`** 或 **`OPENAI_API_KEY`** 覆盖）。
- `base_url`：Chat Completions 兼容地址，例如 `https://api.openrouter.ai/api/v1` 或你实际使用的镜像（末尾一般为 `/v1`）。
- `model`：该网关下**已开通、有可用渠道**的模型 ID（若报 `model_not_found` 或 503，需改为控制台中列出的可用模型名）。

可选字段：`openrouter_http_referer`、`openrouter_app_title`（部分 OpenRouter 兼容站需要）。

### 5.2 浏览器对话

打开：`http://127.0.0.1:8000/v3` 。

在输入框中发送 README 中的示例问题，例如：

- 「数据库主从延迟超过30秒怎么处理？」
- 「服务 OOM 了怎么办？」
- 「P0 故障的响应流程是什么？」

页面应展示 **工具调用**（`readFile`）及助手回复。上传功能为 **`POST /v3/upload`**，可在页面「上传到 data」区域操作。

### 5.3 可选环境变量（调试）

| 变量                     | 含义                 |
| ------------------------ | -------------------- |
| `OPENAI_MODEL`           | 覆盖配置文件中的模型 |
| `OPENAI_BASE_URL`        | 覆盖 API 基地址      |
| `PHASE3_MAX_TOOL_ROUNDS` | 工具轮次上限         |
| `PHASE3_MAX_FILE_CHARS`  | 单次读取最大字符数等 |

## 6. 自动化测试

在仓库根目录执行：

```bash
python3 -m unittest tests.test_phase1 tests.test_phase2 tests.test_phase3 -q
```

全部通过表示与当前测试用例约定一致；Phase 2 部分用例可能依赖索引或 mock，以 `tests/` 下具体用例为准。

## 7. 常见问题

1. **Phase 3 报 HTTP 4xx/5xx 或 `model_not_found`**：检查 `base_url` 与 `model` 是否与当前网关一致，密钥是否有效、该模型是否有可用上游渠道。  
2. **Phase 2 无结果或不可用**：先执行 `python3 -m phase2.rebuild_index`，并确认本机已安装嵌入相关依赖。  
3. **端口被占用**：设置 `PORT=8001` 等后重新启动 `python3 app.py`。

---

若需向他人交接，请同时提供：**Python 版本**、**是否已建 Phase2 索引**、**Phase3 所用网关类型（勿泄露真实 API Key）** 及上述验证步骤的执行结果摘要。
