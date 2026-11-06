"""第三方视频号数据平台适配器（生产合规数据源）。
适用于新榜/友望/视灯等提供开放 API 的服务商：将下述端点映射替换为所购服务的实际接口即可。
需要环境变量 THIRD_PARTY_API_BASE / THIRD_PARTY_API_KEY。"""
import requests

from .. import config
from .base import PeerCollector


class NotConfigured(RuntimeError):
    pass


class ThirdPartyCollector(PeerCollector):
    def __init__(self):
        if not (config.THIRD_PARTY_API_BASE and config.THIRD_PARTY_API_KEY):
            raise NotConfigured(
                "第三方数据平台未配置：请设置 THIRD_PARTY_API_BASE / THIRD_PARTY_API_KEY，"
                "或将 COLLECTOR_MODE 设为 mock 使用内置模拟源。")
        self.base = config.THIRD_PARTY_API_BASE.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {config.THIRD_PARTY_API_KEY}"

    def _get(self, path, **params):
        r = self.session.get(self.base + path, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def scan(self, keywords, accounts):
        # 端点映射示例：GET /videos/search?keyword=&account=&since=
        data = self._get("/videos/search", keyword=",".join(keywords),
                         account=",".join(accounts), limit=50)
        out = []
        for it in data.get("items", []):
            out.append({
                "account": it.get("account_name", ""),
                "title": it.get("title", ""),
                "drama": it.get("drama_title", ""),
                "hook_type": it.get("hook_type", ""),
                "publish_time": it.get("publish_time", ""),
                "cover_hue": hash(it.get("title", "")) % 360,
                "violation": bool(it.get("violation", False)),
                "metrics": {k: int(it.get(k, 0)) for k in
                            ("play", "likes", "comments", "shares", "mount_clicks")},
            })
        return out

    def fetch_metrics(self, title, day_index):
        data = self._get("/videos/metrics", title=title, day=day_index)
        return {k: int(data.get(k, 0)) for k in
                ("play", "likes", "comments", "shares", "mount_clicks")}

    def check_rules(self):
        data = self._get("/platform/rules", platform="channels")
        return [r.get("title", "") for r in data.get("changes", [])]


def build_collector():
    """按配置返回采集器实例。"""
    if config.COLLECTOR_MODE == "thirdparty":
        return ThirdPartyCollector()
    from .mock import MockCollector
    return MockCollector()
