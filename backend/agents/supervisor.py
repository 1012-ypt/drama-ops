"""主管：早会统筹、任务分配、跨角色对齐、异常同步、每周经验库沉淀。"""
import json

from .. import db
from .base import Agent


class SupervisorAgent(Agent):
    name = "supervisor"
    title = "主管"
    color = "#f472b6"

    def chat_context(self):
        facts = []
        rev = db.one("SELECT COALESCE(SUM(revenue),0) r FROM share_records WHERE day=date('now','localtime')")["r"]
        prev = db.one("SELECT COALESCE(SUM(revenue),0) r FROM share_records WHERE day=date('now','localtime','-1 day')")["r"]
        facts.append(f"今日分成¥{rev:.0f}，昨日¥{prev:.0f}")
        alerts = db.q("SELECT type,content FROM alerts ORDER BY id DESC LIMIT 20")
        seen, uniq = set(), []
        for a in alerts:                       # 按内容去重，最多列3条
            k = (a["type"], a["content"][:60])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(a)
            if len(uniq) >= 3:
                break
        for a in uniq:
            facts.append(f"告警[{a['type']}]：{a['content'][:60]}")
        exp = db.one("SELECT COUNT(*) c FROM experiences")["c"]
        facts.append(f"经验库现存{exp}条")
        m = db.one("SELECT summary FROM meetings ORDER BY day DESC LIMIT 1")
        if m:
            facts.append(f"最近早会：{m['summary'][:100]}")
        return facts

    def fallback_reply(self, message, facts):
        if any(k in message for k in ("早会", "开会", "同步")):
            self.morning_meeting()
            return "早会已重新召开，最新纪要见「早会纪要」页签，异动已同步全员。"
        if any(k in message for k in ("怎么样", "情况", "汇报", "总结")):
            return "团队整体情况：\n" + "\n".join(f"· {f}" for f in facts) + \
                   "\n\n各角色都在按节奏自运行，有异动我会第一时间告警。"
        return super().fallback_reply(message, facts)

    # ---------- 每日早会 ----------
    def morning_meeting(self):
        started = db.now()
        day = db.today()
        alerts = db.q("SELECT * FROM alerts WHERE handled=0 ORDER BY id DESC LIMIT 20")
        report = db.one("SELECT * FROM daily_reports WHERE day=?", (day,))
        rev_today = db.one("SELECT COALESCE(SUM(revenue),0) r FROM share_records WHERE day=?",
                           (day,))["r"]
        rev_yest = db.one(
            "SELECT COALESCE(SUM(revenue),0) r FROM share_records WHERE day=date('now','localtime','-1 day')"
        )["r"]
        tasks = [
            {"角色": "全网对标专员", "任务": "继续30分钟巡检，重点追踪今日新入库作品的72小时曲线"},
            {"角色": "爆款拆解专员", "任务": "拆解昨日新增爆款，输出交叉验证结论"},
            {"角色": "内容生成专员", "任务": "按拆解结论产出今日发布内容，优先睡前黄金档"},
            {"角色": "策略迭代专员", "任务": "检查新剧预案覆盖，回溯低效策略"},
        ]
        findings = ([f"昨日对标日报：{report['content'][:120]}"] if report else []) + [
            f"今日分成¥{rev_today:.0f}，昨日¥{rev_yest:.0f}",
            f"未处理告警 {len(alerts)} 条",
        ]
        # 分成异常检测：环比下跌超30%触发全员同步
        if rev_yest > 0 and rev_today < rev_yest * 0.7:
            self.broadcast("分成异常",
                           f"今日分成¥{rev_today:.0f}，较昨日下跌"
                           f"{(1 - rev_today / rev_yest):.0%}，触发全员同步复盘", "critical")
            findings.append("检测到分成异常下跌，已触发全员同步")
        summary = self.narrate("meeting", findings)
        db.ex("INSERT OR REPLACE INTO meetings(day,summary,tasks) VALUES(?,?,?)",
              (day, summary, json.dumps(tasks, ensure_ascii=False)))
        for a in alerts:
            db.ex("UPDATE alerts SET handled=1 WHERE id=?", (a["id"],))
        self.log("每日早会", f"完成 {day} 早会：同步{len(alerts)}条异动，分配{len(tasks)}项任务",
                 "ok", started)
        return summary

    def broadcast(self, type_, content, level="warn"):
        """规则/异动/分成异常时第一时间全员同步。"""
        self.alert(type_, content, level)
        self.log("全员同步", f"[{type_}] {content}", "ok")

    # ---------- 每周经验库沉淀 ----------
    def weekly_experience_review(self):
        started = db.now()
        week = db.week_of()
        arts = {
            "拆解规律": db.one("SELECT COUNT(*) c FROM deconstructions WHERE created_at>=date('now','localtime','-7 day')")["c"],
            "对标规律": db.one("SELECT COUNT(*) c FROM daily_reports WHERE day>=date('now','localtime','-7 day')")["c"],
            "策略验证": db.one("SELECT COUNT(*) c FROM strategies WHERE created_at>=date('now','localtime','-7 day')")["c"],
        }
        for cat, cnt in arts.items():
            if cnt:
                self.add_experience(
                    "周度沉淀",
                    f"{week} 本周沉淀{cat}{cnt}条：已按转化表现打分入库，供全角色复用", 70)
        # 低分经验清理
        db.ex("DELETE FROM experiences WHERE score<40")
        total = db.one("SELECT COUNT(*) c FROM experiences")["c"]
        self.log("经验库周更", f"{week} 经验库更新完成，现存 {total} 条", "ok", started)
        return total
