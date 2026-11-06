# 视频号剧目挂载分佣 AI 自运营团队

围绕「视频号公域剧目挂载分佣」业务的 AI 自运营系统：5 个角色 Agent 按每日流程自主运转，
以视频号后台真实分成/播放/转化数据为唯一决策依据，配可视化工作台。

## 快速启动

```bash
cd channels-drama-ops
pip install fastapi uvicorn
DEMO_ACCEL=1 python -m backend.api.app     # 演示模式：巡检60秒一次
# 生产节奏（巡检30分钟、早9点每日流程）：
python -m backend.api.app
```

打开 http://localhost:8000 进入工作台。首次启动自动注入演示数据。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `COLLECTOR_MODE` | `mock` | `mock` 模拟源 / `thirdparty` 第三方数据平台 |
| `THIRD_PARTY_API_BASE` / `THIRD_PARTY_API_KEY` | - | 第三方数据平台 API（新榜/友望类授权服务） |
| `LLM_BASE` / `LLM_KEY` / `LLM_MODEL` | - | OpenAI 兼容接口；不配则用内置模板生成 |
| `WATCH_KEYWORDS` / `WATCH_ACCOUNTS` | 内置 | 巡检关键词与同行账号清单 |
| `PATROL_INTERVAL_SEC` / `DAILY_FLOW_HOUR` | `1800` / `9` | 巡检间隔 / 每日流程时间 |
| `DEMO_ACCEL` | `0` | `1` = 演示加速（巡检60s） |

## 数据接入

- **同行公开作品**：`COLLECTOR_MODE=thirdparty` 并配置授权数据平台 API Key（合规路径；视频号无公开 API，不建议爬虫）
- **自有账号分成/播放**：视频号后台导出 CSV（列：`day,drama_title,play,conversions,revenue`），`POST /api/import/share_records` 上传导入

## 目录

```
backend/
  config.py        全局配置          db.py        SQLite 数据层
  llm.py           LLM 抽象+模板兜底  seed.py      演示数据
  collectors/      采集适配层（mock / 第三方平台）
  agents/          主管 / 对标 / 拆解 / 内容 / 策略 五角色
  pipeline/        30min巡检、72h追踪、每日自运行流程、调度器
  api/app.py       FastAPI：REST + 静态工作台 + 调度启动
frontend/index.html  可视化工作台（实时刷新）
docs/architecture.md 架构设计
```
