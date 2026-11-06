"""轻量调度器：后台线程按节奏触发巡检/追踪/每日流程。
DEMO_ACCEL=1 时巡检缩短为60秒，便于演示。"""
import threading
import time
from datetime import datetime

from .. import config
from . import daily, jobs


class Scheduler:
    def __init__(self, agents):
        self.agents = agents
        self._stop = threading.Event()
        self._last_patrol = 0.0
        self._last_daily_day = None
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def interval(self):
        return 60 if config.DEMO_ACCEL else config.PATROL_INTERVAL_SEC

    def _loop(self):
        while not self._stop.is_set():
            now = time.time()
            if now - self._last_patrol >= self.interval:
                self._last_patrol = now
                jobs.patrol_job(self.agents["benchmark"], self.agents["supervisor"])
                jobs.track_job(self.agents["benchmark"])
            dt = datetime.now()
            if dt.hour >= config.DAILY_FLOW_HOUR and self._last_daily_day != dt.date():
                self._last_daily_day = dt.date()
                daily.run_daily_flow(self.agents)
            self._stop.wait(5)
