"""模拟数据源：生成符合真实分布的同行作品与 72 小时增长曲线。
增长画像三档：fast(首日即爆) / steady(平稳爬坡) / late_boom(滞后起量爆款)。
同一标题的作品画像稳定，保证跨天追踪数据自洽。"""
import hashlib
import random
from datetime import datetime, timedelta

from .base import PeerCollector

_DRAMAS = [
    ("闪婚后傅总马甲藏不住了", "甜宠"), ("重生之我在80年代当后妈", "穿越"),
    ("无双剑尊", "战神"), ("千金归来之复仇游戏", "复仇"),
    ("穿越之农家小福女", "穿越"), ("都市绝品神医", "逆袭"),
    ("婆婆的镯子", "家庭伦理"), ("开局地摊卖大力", "逆袭"),
]
_HOOKS = ["悬念反转", "强冲突开场", "身份反差", "情绪共鸣", "数字冲击", "复仇爽点"]
_TITLES = [
    "她替妹妹出嫁，没想到新郎竟是{e}",
    "被全家赶出门那天，我激活了{e}",
    "结婚三年丈夫从不碰我，直到我发现他的{e}",
    "婆婆当众摔了我的镯子，下一秒她跪了{e}",
    "穿越第一天，我靠{e}震惊全村",
    "战神归来，发现女儿住在{e}",
    "摆摊第30天，系统奖励我{e}",
    "离婚后她成了首富，前夫{e}求复合",
    "全村都笑她傻，直到{e}上门提亲",
    "医生说他活不过三天，我偏要{e}",
    "重生回到80年代，我做的第一件事是{e}",
    "千金小姐隐姓埋名，只为查清{e}真相",
]
_ELEMS = ["千亿家产", "神秘系统", "隐藏身份", "十年布局", "惊天秘密", "绝世医术", "传家玉佩", "幕后黑手"]
_RNG = random.Random(42)


def _profile(title):
    h = int(hashlib.md5(title.encode()).hexdigest(), 16)
    r = h % 100
    if r < 25:
        return "fast"
    if r < 75:
        return "steady"
    return "late_boom"


class MockCollector(PeerCollector):
    def __init__(self):
        self._emitted = {}   # title -> {base, profile}
        self._tick = 0

    def _gen_video(self, accounts, now):
        drama, cat = _RNG.choice(_DRAMAS)
        title = _RNG.choice(_TITLES).format(e=_RNG.choice(_ELEMS))
        if title in self._emitted:
            return None
        base = _RNG.randint(3000, 40000)
        self._emitted[title] = {"base": base, "profile": _profile(title)}
        return {
            "account": _RNG.choice(accounts),
            "title": title,
            "drama": drama,
            "hook_type": _RNG.choice(_HOOKS),
            "publish_time": (now - timedelta(minutes=_RNG.randint(5, 180))).isoformat(timespec="seconds"),
            "cover_hue": _RNG.randint(0, 360),
            "violation": _RNG.random() < 0.06,   # 6% 概率命中违规，被过滤
            "metrics": self._metrics(title, 1),
        }

    def _metrics(self, title, day_index):
        info = self._emitted.get(title)
        if not info:
            # 未登记的标题（如历史种子数据）：按标题哈希确定性生成画像，保证跨天数据自洽
            h = int(hashlib.md5(title.encode()).hexdigest(), 16)
            info = {"base": 5000 + h % 35000, "profile": _profile(title)}
            self._emitted[title] = info
        base, prof = info["base"], info["profile"]
        mult = {"fast":     {1: 3.0, 2: 5.5, 3: 7.0},
                "steady":   {1: 1.0, 2: 1.6, 3: 2.1},
                "late_boom": {1: 0.8, 2: 1.1, 3: 8.5}}[prof][day_index]
        play = int(base * mult * _RNG.uniform(0.9, 1.1))
        return {
            "play": play,
            "likes": int(play * _RNG.uniform(0.02, 0.05)),
            "comments": int(play * _RNG.uniform(0.003, 0.01)),
            "shares": int(play * _RNG.uniform(0.004, 0.012)),
            "mount_clicks": int(play * _RNG.uniform(0.01, 0.035)),
        }

    def scan(self, keywords, accounts):
        self._tick += 1
        now = datetime.now()
        out = []
        # 每次巡检 60% 概率发现 0~3 条新作品
        if _RNG.random() < 0.6:
            for _ in range(_RNG.randint(1, 3)):
                v = self._gen_video(accounts, now)
                if v:
                    out.append(v)
        return out

    def fetch_metrics(self, title, day_index):
        return self._metrics(title, day_index)

    def check_rules(self):
        if _RNG.random() < 0.05:   # 偶发规则变动
            return ["视频号发布《短剧内容规范》更新：加强对夸张封面与诱导点击的审核"]
        return []
