"""全局配置：全部可通过环境变量覆盖"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("OPS_DB", os.path.join(BASE_DIR, "ops.db"))

# ---- LLM（可选；不配置则使用内置模板化生成，系统仍可完整自运行）----
LLM_BASE = os.environ.get("LLM_BASE", "")          # OpenAI 兼容接口地址，如 https://api.openai.com/v1
LLM_KEY = os.environ.get("LLM_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

# ---- 同行数据采集 ----
# mock        : 内置模拟数据源（默认，开箱即用跑通全流程）
# thirdparty  : 第三方视频号数据平台 API（新榜/友望类，需授权 API Key，合规数据源）
COLLECTOR_MODE = os.environ.get("COLLECTOR_MODE", "mock")
THIRD_PARTY_API_BASE = os.environ.get("THIRD_PARTY_API_BASE", "")
THIRD_PARTY_API_KEY = os.environ.get("THIRD_PARTY_API_KEY", "")

# ---- 调度节奏 ----
PATROL_INTERVAL_SEC = int(os.environ.get("PATROL_INTERVAL_SEC", "1800"))  # 对标巡检：每30分钟
DAILY_FLOW_HOUR = int(os.environ.get("DAILY_FLOW_HOUR", "9"))             # 每日自运行流程：早9点
DEMO_ACCEL = os.environ.get("DEMO_ACCEL", "0") == "1"                     # 演示加速：巡检60s一次

# ---- 监控关键词与同行账号（巡检范围）----
WATCH_KEYWORDS = [k.strip() for k in os.environ.get(
    "WATCH_KEYWORDS", "短剧,逆袭,复仇,甜宠,战神,穿越,家庭伦理").split(",") if k.strip()]
WATCH_ACCOUNTS = [a.strip() for a in os.environ.get(
    "WATCH_ACCOUNTS", "剧有引力,短剧星球,火星小剧场,追剧少女酱,爆款放映厅").split(",") if a.strip()]

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
