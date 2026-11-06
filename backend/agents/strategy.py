"""策略迭代专员：新剧前置策划、每周回溯、淘汰低效策略。"""
import json

from .. import db
from .base import Agent


class StrategyAgent(Agent):
    name = "strategy"
    title = "策略迭代专员"
    color = "#fbbf24"

    def chat_context(self):
        facts = []
        plans = db.q("SELECT s.*, d.title drama FROM strategies s JOIN dramas d ON d.id=s.drama_id"
                     " ORDER BY s.id DESC LIMIT 3")
        for p in plans:
            facts.append(f"《{p['drama']}》预案[{p['status']}]适配度{p['fit']}：{p['direction'][:70]}")
        dropped = db.one("SELECT COUNT(*) c FROM strategies WHERE status='已淘汰'")["c"]
        facts.append(f"累计淘汰低效策略{dropped}条")
        new_cnt = db.one("SELECT COUNT(*) c FROM dramas WHERE status='新剧'")["c"]
        if new_cnt:
            facts.append(f"当前在库新剧{new_cnt}部")
        return facts

    def fallback_reply(self, message, facts):
        if any(k in message for k in ("新剧", "预案", "策划")):
            self.plan_new_dramas()
            return "已检查新剧库并补齐前置预案，去「策略预案」页签查看适配度判定和首周模板。"
        return super().fallback_reply(message, facts)

    # ---------- 新剧前置策划 ----------
    def plan_new_dramas(self):
        started = db.now()
        news = db.q("SELECT * FROM dramas WHERE status='新剧' AND id NOT IN"
                    " (SELECT drama_id FROM strategies WHERE status='生效中')")
        made = 0
        for d in news:
            peer_proof = db.one(
                "SELECT COUNT(*) c, MAX(s.play) mp FROM peer_videos pv"
                " JOIN snapshots s ON s.video_id=pv.id WHERE pv.drama_id=? AND pv.violation=0",
                (d["id"],))
            fit = ("高" if peer_proof and peer_proof["c"] >= 2 else
                   "中" if peer_proof and peer_proof["c"] == 1 else "待验证")
            templates = [
                {"模板": "冲突前置版", "结构": "3秒名场面→压迫升级→身份反转→卡断挂载",
                 "适配": "首周主推"},
                {"模板": "悬念钩子版", "结构": "结果倒放→回溯起因→悬念卡断",
                 "适配": "二轮放量"},
                {"模板": "情绪共鸣版", "结构": "共情痛点→代入视角→爽点释放",
                 "适配": "评论区互动高时启用"},
            ]
            direction = self.narrate("strategy", [
                f"新剧《{d['title']}》（{d['category']}）分成比例{d['share_rate']:.0%}",
                f"同行同款已发作品{peer_proof['c'] if peer_proof else 0}条，"
                f"峰值播放{peer_proof['mp'] if peer_proof else 0}，市场适配度判定：{fit}",
                "推广方向：首周以“冲突前置版”模板抢首发流量，二轮切换“悬念钩子版”拉长尾",
            ])
            db.ex("INSERT INTO strategies(drama_id,direction,templates,fit,created_at)"
                  " VALUES(?,?,?,?,?)",
                  (d["id"], direction, json.dumps(templates, ensure_ascii=False), fit, db.now()))
            made += 1
            self.alert("新剧预案", f"新剧《{d['title']}》推广预案已生成，适配度：{fit}", "info")
        self.log("新剧策划", f"生成 {made} 部新剧前置预案", "ok", started)
        return made

    # ---------- 每周回溯：淘汰低效策略 ----------
    def weekly_review(self):
        started = db.now()
        acts = db.q(
            "SELECT s.id sid, s.drama_id, d.title, COALESCE(SUM(sr.revenue),0) rev"
            " FROM strategies s JOIN dramas d ON d.id=s.drama_id"
            " LEFT JOIN share_records sr ON sr.drama_id=s.drama_id"
            "  AND sr.day>=date('now','localtime','-7 day')"
            " WHERE s.status='生效中' GROUP BY s.id")
        if not acts:
            self.log("每周回溯", "无生效中策略", "ok", started)
            return 0
        revs = sorted(a["rev"] for a in acts)
        threshold = revs[len(revs) // 2] * 0.4 if revs else 0
        dropped = 0
        for a in acts:
            if a["rev"] < threshold:
                db.ex("UPDATE strategies SET status='已淘汰',"
                      " review=? WHERE id=?",
                      (f"近7日分成¥{a['rev']:.0f}，低于团队中位线40%，判定低效淘汰", a["sid"]))
                self.add_experience("策略淘汰",
                                    f"《{a['title']}》推广策略近7日分成¥{a['rev']:.0f}，"
                                    "低效已淘汰：避免同类剧目复用", 65)
                dropped += 1
        self.log("每周回溯", f"评估 {len(acts)} 条策略，淘汰 {dropped} 条低效策略", "ok", started)
        return dropped
