"""同行数据采集适配层。

合规说明：微信视频号无公开数据 API，直接爬虫抓取存在违反平台协议与账号封禁风险。
本系统只定义标准采集接口 PeerCollector，生产环境应接入【已获授权的第三方数据平台】
（新榜/友望/视灯等视频号数据服务商的开放 API）作为合规数据源，
自有账号数据由运营从视频号后台导出后经 /api/import 导入。
默认内置 MockCollector，用于无数据源时完整跑通系统全流程。
"""
from abc import ABC, abstractmethod


class PeerCollector(ABC):
    """同行公开作品采集接口。返回结构化的原始数据，DB 映射由对标专员完成。"""

    @abstractmethod
    def scan(self, keywords, accounts):
        """巡检关键词与指定账号的新公开发布作品。
        返回: [{account, title, drama, hook_type, publish_time, cover_hue,
                violation, metrics:{play,likes,comments,shares,mount_clicks}}]
        """

    @abstractmethod
    def fetch_metrics(self, title, day_index):
        """拉取某作品第 day_index 天(1/2/3)的播放/互动/挂载转化。
        返回: {play,likes,comments,shares,mount_clicks}
        """

    @abstractmethod
    def check_rules(self):
        """巡检视频号平台规则/公告变动（用于主管触发全员同步）。
        返回: [str] 变动描述列表，无变动返回空列表。
        """
