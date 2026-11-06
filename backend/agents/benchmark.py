"""全网对标专员：30分钟巡检、台账入库、72小时跨天追踪、滞后爆款挖掘、每日对标日报。"""
from datetime import datetime

from .. import config, db
from .base import Agent


class BenchmarkAgent(Agent):
    name = "benchmark"
    title = "全网对标专员"
    color = "#22d3ee"

    def __init__(self, collector):
        self.collector = collector

    # ---------- 对话上下文 ----------
    def chat_context(self):
        facts = []
        total = db.one("SELECT COUNT(*) c FROM peer_videos WHERE violation=0")["c"]
        today_new = db.one("SELECT COUNT(*) c FROM peer_videos WHERE discovered_at>=date('now','localtime') AND violation=0")["c"]
        tracking = db.one("SELECT COUNT(*) c FROM peer_videos WHERE track_done=0 AND violation=0")["c"]
        facts.append(f"对标台账共{total}条，24小时新入库{today_new}条，72小时追踪中{tracking}条")
        top = db.q("SELECT pv.title,pa.name account,s.play FROM peer_videos pv"
                   " JOIN peer_accounts pa ON pa.id=pv.account_id"
                   " JOIN snapshots s ON s.video_id=pv.id AND s.day_index=3"
                   " WHERE pv.violation=0 ORDER BY s.play DESC LIMIT 3")
        for t in top:
            facts.append(f"三日TOP：{t['title'][:16]}（{t['account']}，播放{t['play']}）")
        booms = db.q("SELECT pv.title FROM peer_videos pv WHERE pv.is_late_boom=1 LIMIT 3")
        for b in booms:
            facts.append(f"滞后爆款：《{b['title'][:18]}》，已提炼起量规律入经验库")
        rep = db.one("SELECT content FROM daily_reports ORDER BY day DESC LIMIT 1")
        if rep:
            facts.append(f"最新日报结论：{rep['content'][:120]}")
        return facts

    def fallback_reply(self, message, facts):
        if any(k in message for k in ("爆", "起量", "推荐")):
            booms = [f for f in facts if "滞后爆款" in f]
            if booms:
                return ("滞后爆款是我重点盯的方向：\n" + "\n".join(f"· {b}" for b in booms) +
                        "\n\n共性规律：首日播放低但完播率高，72小时内触发二次推流。"
                        "详细拆解可以去「对标日报」和「经验库」页签看。")
        return super().fallback_reply(message, facts)

    # ---------- 巡检 ----------
    def patrol(self):
        started = db.now()
        new_items = self.collector.scan(config.WATCH_KEYWORDS, config.WATCH_ACCOUNTS)
        inserted, filtered = 0, 0
        for it in new_items:
            if it.get("violation"):
                filtered += 1
                self.log("违规过滤", f"过滤疑似违规作品《{it['title']}》", "skip", started)
                continue
            acc = db.one("SELECT id FROM peer_accounts WHERE name=?", (it["account"],))
            if not acc:
                db.ex("INSERT INTO peer_accounts(name,fans) VALUES(?,?)",
                      (it["account"], 50000 + hash(it["account"]) % 900000))
                acc = db.one("SELECT id FROM peer_accounts WHERE name=?", (it["account"],))
            drama = self._drama(it.get("drama") or "未识别剧目")
            if db.one("SELECT id FROM peer_videos WHERE title=? AND account_id=?",
                      (it["title"], acc["id"])):
                continue
            vid = db.ex(
                "INSERT INTO peer_videos(account_id,drama_id,title,cover_hue,hook_type,"
                "publish_time,discovered_at) VALUES(?,?,?,?,?,?,?)",
                (acc["id"], drama["id"], it["title"], it.get("cover_hue", 200),
                 it.get("hook_type", ""), it["publish_time"], started))
            self._snapshot(vid, 1, it["metrics"])
            inserted += 1
            if drama["is_exclusive"]:
                self.alert("独家剧目", f"同行[{it['account']}]发布独家剧目《{drama['title']}》"
                           f"相关作品《{it['title']}》", "critical")
            if it.get("hook_type") in ("身份反差", "复仇爽点"):
                self.alert("差异化钩子", f"检测到差异化钩子[{it['hook_type']}]："
                           f"《{it['title']}》（{it['account']}）")
        # 平台规则巡检
        for change in self.collector.check_rules():
            self.alert("规则变动", change, "critical")
        self.log("30分钟巡检", f"新入库 {inserted} 条，过滤违规 {filtered} 条", "ok", started)
        return inserted

    def _drama(self, title):
        d = db.one("SELECT * FROM dramas WHERE title=?", (title,))
        if not d:
            db.ex("INSERT INTO dramas(title,status) VALUES(?,?)", (title, "在推"))
            d = db.one("SELECT * FROM dramas WHERE title=?", (title,))
        return d

    def _snapshot(self, vid, day_index, m):
        db.ex("INSERT OR IGNORE INTO snapshots(video_id,day_index,play,likes,comments,"
              "shares,mount_clicks,captured_at) VALUES(?,?,?,?,?,?,?,?)",
              (vid, day_index, m["play"], m["likes"], m["comments"], m["shares"],
               m["mount_clicks"], db.now()))

    # ---------- 72小时跨天追踪 ----------
    def track(self):
        started = db.now()
        pending = db.q("SELECT * FROM peer_videos WHERE track_done=0 AND violation=0")
        done, booms = 0, 0
        for v in pending:
            snaps = {s["day_index"]: s for s in
                     db.q("SELECT * FROM snapshots WHERE video_id=?", (v["id"],))}
            for day in (2, 3):
                if day not in snaps:
                    m = self.collector.fetch_metrics(v["title"], day)
                    self._snapshot(v["id"], day, m)
                    snaps[day] = m
            d1, d3 = snaps.get(1), snaps.get(3)
            if d1 and d3:
                d1p, d3p = d1["play"], d3["play"]
                late = d1p < 20000 and d3p > d1p * 4
                db.ex("UPDATE peer_videos SET track_done=1, is_late_boom=? WHERE id=?",
                      (1 if late else 0, v["id"]))
                done += 1
                drama = db.one("SELECT title FROM dramas WHERE id=?", (v["drama_id"],))
                if late:
                    booms += 1
                    reason = self.narrate("benchmark", [
                        f"《{v['title']}》首日播放仅{d1p}，第三日冲至{d3p}（{d3p // max(d1p,1)}倍）",
                        f"钩子类型[{v['hook_type']}]，挂载剧目《{drama['title']}》",
                        "判定为滞后起量爆款：前期推荐池冷启动慢，完播率累积后触发二次推流",
                    ])
                    self.alert("滞后爆款", f"挖到滞后起量爆款《{v['title']}》："
                               f"首日{d1p}→第三日{d3p}", "critical")
                    self.add_experience("滞后爆款规律", reason, 85)
                elif d3p > d1p * 3:
                    self.add_experience(
                        "起量规律",
                        f"钩子[{v['hook_type']}]在《{drama['title']}》类目3日放大{d3p // max(d1p,1)}倍，"
                        f"首日{d1p}→第三日{d3p}，可复用", 75)
        self.log("72小时追踪", f"完成追踪 {done} 条，滞后爆款 {booms} 条", "ok", started)
        return done

    # ---------- 每日对标日报 ----------
    def daily_report(self):
        started = db.now()
        day = db.today()
        new_videos = db.q(
            "SELECT pv.*, pa.name account, d.title drama FROM peer_videos pv"
            " JOIN peer_accounts pa ON pa.id=pv.account_id"
            " JOIN dramas d ON d.id=pv.drama_id"
            " WHERE pv.discovered_at>=datetime('now','localtime','-1 day') AND pv.violation=0")
        booms = db.q(
            "SELECT pv.*, pa.name account, d.title drama FROM peer_videos pv"
            " JOIN peer_accounts pa ON pa.id=pv.account_id"
            " JOIN dramas d ON d.id=pv.drama_id WHERE pv.is_late_boom=1")
        top = db.q(
            "SELECT pv.title, pv.hook_type, pa.name account, d.title drama,"
            " MAX(s.play) max_play FROM peer_videos pv"
            " JOIN snapshots s ON s.video_id=pv.id"
            " JOIN peer_accounts pa ON pa.id=pv.account_id"
            " JOIN dramas d ON d.id=pv.drama_id"
            " GROUP BY pv.id ORDER BY max_play DESC LIMIT 5")
        hook_stat = db.q(
            "SELECT hook_type, COUNT(*) c FROM peer_videos WHERE violation=0"
            " GROUP BY hook_type ORDER BY c DESC")
        findings = []
        if top:
            findings.append(f"今日对标TOP：《{top[0]['title']}》（{top[0]['account']}，"
                            f"钩子[{top[0]['hook_type']}]，峰值播放{top[0]['max_play']}）")
        if booms:
            findings.append(f"累计滞后爆款 {len(booms)} 条，共性：首日播放<2万、72小时内≥4倍放大")
        if hook_stat:
            findings.append(f"同行高频钩子：{hook_stat[0]['hook_type']}（{hook_stat[0]['c']}条）")
        findings.append(f"24小时新入库 {len(new_videos)} 条，违规内容已自动过滤")
        summary = self.narrate("benchmark", findings)
        db.ex("INSERT OR REPLACE INTO daily_reports(day,content,findings) VALUES(?,?,?)",
              (day, summary, "\n".join(findings)))
        self.log("对标日报", f"生成 {day} 日报：{len(findings)} 条结论", "ok", started)
        return summary
