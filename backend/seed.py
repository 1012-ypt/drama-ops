"""首次启动时注入演示数据：剧目、同行账号、历史台账+72h快照、自有作品、14天分成趋势。
让工作台开箱即有完整业务画面；真实运行时由采集器与各Agent持续写入。"""
import random
from datetime import datetime, timedelta

from . import db

_DRAMAS = [
    ("闪婚后傅总马甲藏不住了", "甜宠", 0.65, "在推", 0),
    ("重生之我在80年代当后妈", "穿越", 0.60, "在推", 0),
    ("无双剑尊", "战神", 0.70, "新剧", 0),
    ("千金归来之复仇游戏", "复仇", 0.65, "在推", 0),
    ("婆婆的镯子", "家庭伦理", 0.55, "完结", 0),
    ("开局地摊卖大力", "逆袭", 0.68, "新剧", 1),   # 独家
]
_ACCOUNTS = [("剧有引力", 820000), ("短剧星球", 450000), ("火星小剧场", 1200000),
             ("追剧少女酱", 260000), ("爆款放映厅", 690000)]
_HOOKS = ["悬念反转", "强冲突开场", "身份反差", "情绪共鸣", "数字冲击", "复仇爽点"]
_TITLES = [
    "她替妹妹出嫁，新郎身份震惊全场", "被赶出家门那天，我继承了千亿",
    "结婚三年，我发现丈夫的秘密身份", "婆婆摔了我的镯子，下一秒跪地求饶",
    "穿越第一天，我靠一道菜震惊全村", "战神归来，女儿却住在桥洞",
    "摆摊第30天，系统奖励我一条街", "离婚后她成首富，前夫跪求复合",
    "全村笑她傻，首富上门提亲那天", "医生判他死刑，我偏要逆天改命",
    "重生80年代，我做的第一件事", "千金隐姓埋名，只为查清真相",
]


def run_if_empty():
    if db.one("SELECT id FROM dramas LIMIT 1"):
        return False
    rng = random.Random(7)
    now = datetime.now()

    drama_ids = []
    for t, cat, rate, status, excl in _DRAMAS:
        drama_ids.append(db.ex(
            "INSERT INTO dramas(title,category,share_rate,status,is_exclusive) VALUES(?,?,?,?,?)",
            (t, cat, rate, status, excl)))
    acc_ids = []
    for name, fans in _ACCOUNTS:
        acc_ids.append(db.ex("INSERT INTO peer_accounts(name,fans) VALUES(?,?)", (name, fans)))

    # ---- 历史台账：14条同行作品 + 72h快照 ----
    for i, title in enumerate(_TITLES):
        aid = rng.choice(acc_ids)
        did = rng.choice(drama_ids[:4])
        days_ago = rng.randint(0, 6)
        pub = (now - timedelta(days=days_ago, hours=rng.randint(0, 20)))
        late = (i % 5 == 4)          # 每5条埋1条滞后爆款
        base = rng.randint(3000, 25000)
        vid = db.ex(
            "INSERT INTO peer_videos(account_id,drama_id,title,cover_hue,hook_type,"
            "publish_time,discovered_at,track_done,is_late_boom) VALUES(?,?,?,?,?,?,?,?,?)",
            (aid, did, title, rng.randint(0, 360), rng.choice(_HOOKS),
             pub.isoformat(timespec="seconds"),
             (pub + timedelta(minutes=40)).isoformat(timespec="seconds"),
             1 if days_ago >= 2 else 0, 1 if late else 0))
        mults = {1: 1.0, 2: (1.3 if late else rng.uniform(1.5, 4.0)),
                 3: (9.0 if late else rng.uniform(2.0, 6.0))}
        for day in (1, 2, 3):
            if days_ago >= day - 1:   # D1必有，D2需满1天，D3需满2天
                play = int(base * mults[day])
                db.ex("INSERT OR REPLACE INTO snapshots(video_id,day_index,play,likes,comments,"
                      "shares,mount_clicks,captured_at) VALUES(?,?,?,?,?,?,?,?)",
                      (vid, day, play, int(play * 0.035), int(play * 0.006),
                       int(play * 0.008), int(play * 0.02),
                       (pub + timedelta(days=day)).isoformat(timespec="seconds")))

    # ---- 自有作品 + 14天分成趋势 ----
    for i in range(10):
        did = rng.choice(drama_ids[:4])
        days_ago = rng.randint(0, 12)
        play = rng.randint(15000, 400000)
        hot = 1 if play > 120000 else 0
        finish = round(rng.uniform(0.15, 0.48), 3)
        clicks = int(play * rng.uniform(0.02, 0.05))
        convs = int(clicks * rng.uniform(0.08, 0.22))
        rev = round(convs * 1.5 * 0.65, 2)
        pub = (now - timedelta(days=days_ago, hours=rng.randint(0, 12)))
        db.ex("INSERT INTO own_videos(title,drama_id,publish_time,play,likes,comments,"
              "finish_rate,mount_clicks,conversions,revenue,is_hot,segment_note)"
              " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              (f"她忍辱三年只为这一刻｜第{i + 1}弹", did, pub.isoformat(timespec="seconds"),
               play, int(play * 0.04), int(play * 0.007), finish, clicks, convs, rev, hot,
               "强冲突前置：名场面开场"))
    for d_off in range(14):
        day = (now - timedelta(days=13 - d_off)).strftime("%Y-%m-%d")
        for did in drama_ids[:4]:
            growth = 1 + d_off * 0.06
            play = int(rng.randint(20000, 90000) * growth)
            convs = int(play * rng.uniform(0.002, 0.005))
            db.ex("INSERT OR REPLACE INTO share_records(day,drama_id,play,conversions,revenue)"
                  " VALUES(?,?,?,?,?)",
                  (day, did, play, convs, round(convs * 1.5 * 0.65, 2)))

    # ---- 历史告警与经验 ----
    db.ex("INSERT INTO alerts(type,level,content,created_at,handled) VALUES(?,?,?,?,1)",
          ("差异化钩子", "warn", "同行[爆款放映厅]使用身份反差钩子起量，建议跟进",
           (now - timedelta(days=2)).isoformat(timespec="seconds")))
    db.ex("INSERT INTO experiences(category,content,source,score,week,created_at)"
          " VALUES('模板','冲突前置+卡断挂载结构在近两周爆款中命中率72%','主管',88,?,?)",
          (db.week_of(), (now - timedelta(days=3)).isoformat(timespec="seconds")))
    db.ex("INSERT INTO experiences(category,content,source,score,week,created_at)"
          " VALUES('规律','滞后爆款共性：首日播放<2万且完播率>35%，第三日触发二次推流','对标专员',85,?,?)",
          (db.week_of(), (now - timedelta(days=1)).isoformat(timespec="seconds")))
    return True
