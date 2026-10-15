# Hindsight 记忆服务：重启记录 + 写入故障报告

> ## 一句话结论
> **服务已重启成功，读取正常；但写入仍然全部失败，根因是 DeepSeek 账户余额不足（402），
> 不是服务或代码 bug。充值后即可恢复写入与 reflect。**
>
> **复测（2026-10-14 晚）**：`hindsight_capture_initiative` 又返回了 `page_id` 且不报错，
> 但 `fact_count` 仍为 **31**、`last_write_at` 仍为 **2026-10-10**、`documents` 仍为 **3** ——
> **该记录同样没有落库**。工具返回成功**完全不可信**，必须以 `fact_count` / `documents` 为准。
>
> 本次任务的进度记录因此**未能存入 Hindsight**，已改为落在
> `_analysis/实现完成报告.md`（含「并行化改造 7.24× 提速」「回忆卡池 + 预算自动估算」两章）与本文档。

## 一、服务已重启（成功）

`C:\Users\ARIS\.hindsight\coding-agent.json` = **自托管**，指向 `http://127.0.0.1:8888`。
服务此前停止（最后成功事件 2026-10-14 12:14:42，之后 13:34 起全部 `ECONNREFUSED`）。

**启动命令**（官方脚本，勿自己拼命令）：

```powershell
powershell -File "$env:USERPROFILE\.hindsight\start-hindsight.ps1"
```

脚本做的事：从 `~\.dsh\.credentials.yaml` 读 `DEEPSEEK_API_KEY`（不回显）→ 设环境变量
（`PYTHONUTF8=1` 必需，否则 GBK 控制台下 banner 的 `▀` 会 `UnicodeEncodeError` 崩溃；
`HF_ENDPOINT=https://hf-mirror.com`；LLM=deepseek-v4-flash；embeddings=本地 bge-small-en-v1.5）
→ 执行 `~\.hindsight\venv\Scripts\hindsight-api.exe`。

**重启后实测**：
- `/health` → **HTTP 200**
- `hindsight_sync_status` → `bank=coding-agent::MGGBattleSimulation`，`gitlogPresent=true`，
  `pagesCount=9`，知识页完好
- 端口 8888 由 `hindsight-api`(pid 30240) / python(5776) 监听

> 注意：`hindsight_diagnose` **只报告配置，不探测连通性**。它显示 api_url 正确并不代表服务在跑。

## 二、发现一个更严重的问题：**写入全部失败，根因是 DeepSeek 余额不足**

重启只修好了「读」，**「写」是坏的**。**根因已定位并复现**：

```
POST /v1/default/banks/{bank}/memories
→ HTTP 500
{"detail":"Fact extraction failed: 1/1 chunks failed. First failures:
 chunk 0: APIStatusError: Error code: 402 -
 {'error': {'message': 'Insufficient Balance (request_id: 787eebc1-...)'}}"}
```

**机理**：本服务用 DeepSeek 做事实抽取（`HINDSIGHT_API_LLM_PROVIDER=deepseek`）。
写入时必须调用 LLM 抽取 facts；**余额不足 → 抽取失败 → 服务端在入库前就拒绝该文档**。
这与 10/13 的 `reflect_failed`（402 Insufficient Balance）是**同一个根因**，只是影响面更大：
- 之前只看到它影响 `reflect`（深度合成）；
- 实际上它也**阻断一切写入**（`retain`）。

**修复办法**：给 `~\.dsh\.credentials.yaml` 里那个 `DEEPSEEK_API_KEY` 对应的账户充值。
这不是代码问题，服务端无 bug——它如实返回了 500 + 402。

### 证据链（三重验证）
1. `hindsight_ingest_document` 返回 `{"ok": true, "doc_id": "..."}` —— **看起来成功，实为静默失败**。
2. `GET .../documents?limit=100` → **total 恒为 3**，我的 3 篇（含探针 `ZZPROBE-7f3a91`）一篇不在。
3. 直接 `GET .../documents/{doc_id}` → **404**。
4. `GET /banks` → `fact_count: 31`、`last_write_at: 2026-10-10T12:17:32` —— 无增长（等 45s 后复查仍不变）。
5. `GET .../memories/list?limit=200` 全量 31 条逐条 grep `ZZPROBE`/`派发粒度`/`ECONNREFUSED`/`战斗进程池`/`7.24`/`pickle` → **全部 0 命中**。
6. **REST 直连 `POST /memories`** → HTTP 500 + 402，**决定性证据**（绕开 MCP 工具仍失败，证明问题在服务端/LLM 侧，不在工具实现）。

### 两个必须记住的教训

**教训 A：`hindsight_ingest_document` 会在写入失败时仍返回 `ok: true`。**
不要相信它的返回值；要用 `documents` 列表 / `fact_count` / `last_write_at` / 直接 GET doc_id 来验证。

**教训 B：`recall` 的「命中」会骗人。**
用 `ZZPROBE-7f3a91` 走 recall 曾返回 1~2 条，看似写入成功；但 recall 是语义+关键词检索，
会因词汇重叠返回**旧文档**，实际内容与探针无关。
**判断写入成功不能靠 recall 条数。**

### 读 vs 写（当前状态）
| 能力 | 状态 | 是否需要 LLM |
| --- | --- | --- |
| `recall`（检索既有记忆） | ✅ 正常（HTTP 200，能取回 10/10 的 ACL 记忆） | 否 |
| 知识页（9 个，含本仓库 initiative 页） | ✅ 可读 | 否 |
| `reflect`（深度合成） | ❌ 402 | 是 |
| `retain` / `ingest_document`（写入） | ❌ 402（500） | 是 |

**结论：读能用，写不能用。** 需要充值 DeepSeek 才能恢复写入与 reflect。

### 影响
- 本次任务（优化器并行化改造）的进度记录**未能写入 Hindsight**，已改为落在
  `_analysis/实现完成报告.md`（含「并行化改造 7.24× 提速」章节）与本文档。
- 更早两次 ingest（`更正：bundled Python 3.12 属 agent 工具链`、`新配装优化器实现完成（P1-P6）`）
  当时服务健康（12:13 有 `pages_ok`），**但仍需按上述方法核实是否真已落库**，不可假定已保存。
- `hindsight_capture_initiative` 同样返回了 `page_id` 且未报错——**该页是否真的更新，同样存疑**。


## 三、另外两个既有故障（与本次中断不同，勿混淆）

### 3.1 LLM 余额不足（2026-10-13 的三次 reflect 失败）
`plugin.log`：
```
WARN [dsh] reflect failed — session runs without memory
{"error":"reflect 500 {\"detail\":\"Error code: 402 -
 {'error': {'message': 'Insufficient Balance ...'}}"}
```
**这与第二节的写入失败是同一个根因**（DeepSeek 余额），只是当时只体现在 reflect 上。
当时 `pages_ok` 仍正常（检索不需要 LLM）。

### 3.2 `inject_ok` 会在记忆失败时仍报 ok
2026-10-14 13:39:35 同时出现 `pages_failed` 与 `inject_ok`。
说明 inject 走了**回退路径**（reflect 失败 → 知识页检索 → 原始 recall）。
**看到 `inject_ok` 不代表一切正常**，必须同时看 pages/reflect 是否 failed。

## 四、排查清单（下次「记忆像丢了」按序做）

1. `Get-NetTCPConnection -LocalPort 8888 -State Listen` —— 端口真的在监听吗。
2. `Invoke-WebRequest http://127.0.0.1:8888/health` —— 期望 **200**（`/` 返回 404 属正常，根路径非端点）。
3. `hindsight_sync_status` —— 看 `synced`、`pagesCount`、`activeOps`。
4. 读 `~\.hindsight\coding-agents-logs\diag.jsonl` 末尾 —— 最后一次 `retain_ok`/`inject_ok` 的时间戳
   给出**服务何时消失**。
5. 读 `plugin.log` 末尾 —— 区分 ECONNREFUSED（服务不在）与 402/5xx（LLM 侧）。
6. **验证写入**（关键，别只看工具返回值）：
   `GET /v1/default/banks/coding-agent::MGGBattleSimulation/documents?limit=100` 看 total 是否增长，
   以及 `GET /banks` 的 `fact_count` / `last_write_at`。
7. **要确认根因，直接打 REST**（绕开 MCP 工具，能拿到真实错误体）：
   ```powershell
   $bank='coding-agent::MGGBattleSimulation'
   $body = @{ items = @(@{ content='探针文本'; context='probe'; document_id='probe-1' }) } | ConvertTo-Json -Depth 6
   Invoke-WebRequest -Uri "http://127.0.0.1:8888/v1/default/banks/$bank/memories" `
     -Method Post -Body $body -ContentType 'application/json' -UseBasicParsing
   ```
   成功 → 200；**失败会返回 500 并在 detail 里说明真实原因**（本次即 402 Insufficient Balance）。

## 五、环境事实
- 端口 8888；日志目录 `C:\Users\ARIS\.hindsight\coding-agents-logs\`
  （`diag.jsonl` 结构化、`plugin.log` 人读、`usage.jsonl` 工具使用率）。
- 该目录**不是**数据目录；记忆本体在服务侧（内置 pg0）。客户端无状态可清。
- PATH 上无 `hindsight`/`hindsight-api`，也无全局 pip 安装；一切走
  `~\.hindsight\venv\Scripts\hindsight-api.exe`（venv 内含 fastapi/uvicorn 等）。
- 本机已存在两个 bank：`coding-agent::MGGBattleSimulation`（facts=31）、
  `coding-agent::MGGAutoScript`（facts=190）。
