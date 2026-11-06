"""定时作业：30分钟巡检 + 72小时追踪。"""
import threading

from .. import config, db
from ..agents.benchmark import BenchmarkAgent
from ..agents.supervisor import SupervisorAgent

_lock = threading.Lock()
pipeline_running = False


def patrol_job(benchmark: BenchmarkAgent, supervisor: SupervisorAgent):
    with _lock:
        try:
            benchmark.patrol()
        except Exception as e:   # 单点失败不拖垮调度
            benchmark.log("30分钟巡检", f"巡检异常：{e}", "error")


def track_job(benchmark: BenchmarkAgent):
    with _lock:
        try:
            benchmark.track()
        except Exception as e:
            benchmark.log("72小时追踪", f"追踪异常：{e}", "error")
