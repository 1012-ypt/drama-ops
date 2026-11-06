"""内容生成专员：基于拆解结论与历史高转化模板，产出脚本/画面提示词/标题/发布时段。"""
from .. import db
from .base import Agent

_SLOTS = ["07:30 早高峰通勤", "12:00 午间休息", "18:30 晚高峰", "21:30 睡前黄金档"]


class ContentAgent(Agent):
    name = "content"
    title = "内容生成专员"
    color = "#34d399"

    def chat_context(self):
        facts = []
        pend = db.q("SELECT c.*, d.title drama FROM contents c JOIN dramas d ON d.id=c.drama_id"
                    " WHERE c.status='待审核' ORDER BY c.id DESC LIMIT 3")
        for c in pend:
            facts.append(f"待审内容：《{c['title_copy'][:18]}》→ 挂《{c['drama']}》，"
                         f"建议{c['slot']}发布")
        pub = db.q("SELECT ov.title, ov.play, ov.revenue FROM own_videos ov"
                   " ORDER BY ov.id DESC LIMIT 2")
        for p in pub:
            facts.append(f"最近发布：《{p['title'][:16]}》播放{p['play']}，分成¥{p['revenue']:.0f}")
        if not pend:
            facts.append("当前没有待审内容，点「跑整日自运行流程」我会立即产出")
        return facts

    def fallback_reply(self, message, facts):
        if any(k in message for k in ("写", "产出", "生成", "来一条", "内容")):
            self.run()
            return "收到，我已按最新拆解结论为每部在推剧目产出内容，去「内容队列」页签审稿，点「发布」即上线。"
        return super().fallback_reply(message, facts)

    def run(self):
        started = db.now()
        dramas = db.q("SELECT * FROM dramas WHERE status='在推'")
        made = 0
        for d in dramas:
            today_cnt = db.one(
                "SELECT COUNT(*) c FROM contents WHERE drama_id=? AND created_at>=date('now','localtime')",
                (d["id"],))["c"]
            if today_cnt >= 2:      # 每剧每日最多2条，避免刷屏
                continue
            self._make(d)
            made += 1
        self.log("内容产出", f"产出 {made} 条待发布推广内容", "ok", started)
        return made

    def _make(self, d):
        deco = db.one("SELECT * FROM deconstructions WHERE drama_id=? ORDER BY id DESC",
                      (d["id"],))
        tpl = db.one("SELECT * FROM experiences WHERE category IN ('拆解规律','滞后爆款规律')"
                     " ORDER BY score DESC LIMIT 1")
        base_structure = (deco["hook_logic"] if deco else
                          (tpl["content"] if tpl else "开场3秒强冲突+20秒反转+卡断挂载"))
        hook = "身份反差" if "反差" in base_structure else "强冲突开场"
        script = (
            f"【开场0-3秒】{d['title']}名场面前置：女主被诬陷当众受辱，弹幕情绪点拉满\n"
            f"【3-20秒】压迫升级：反派加码、主角隐忍，镜头快速切换留悬念\n"
            f"【20-40秒】反转点：隐藏身份揭晓，配乐骤停后爆发，制造“爽点峰值”\n"
            f"【40秒+】卡断在下一反转前，口播引导：全集更精彩，点击下方短剧观看")
        image_prompt = (f"short drama key visual, {d['category']} theme, dramatic confrontation "
                        f"scene, cinematic lighting, high saturation, vertical 9:16 poster, "
                        f"close-up expressions, tension atmosphere")
        title_copy = f"她忍辱三年，只为这一刻｜《{d['title']}》全集已上线"
        slot = _SLOTS[d["id"] % len(_SLOTS)]
        db.ex("INSERT INTO contents(drama_id,script,image_prompt,title_copy,slot,template,"
              "created_at) VALUES(?,?,?,?,?,?,?)",
              (d["id"], script, image_prompt, title_copy, slot,
               (tpl["content"][:60] if tpl else "默认结构"), db.now()))

    def publish(self, content_id):
        """内容发布：登记为自有作品，并生成投放后的表现记录（供复盘）。"""
        import random
        from datetime import datetime
        c = db.one("SELECT * FROM contents WHERE id=?", (content_id,))
        if not c or c["status"] == "已发布":
            return None
        rng = random.Random(content_id)
        play = rng.randint(20000, 300000)
        finish = round(rng.uniform(0.18, 0.45), 3)
        clicks = int(play * rng.uniform(0.02, 0.05))
        convs = int(clicks * rng.uniform(0.08, 0.2))
        drama = db.one("SELECT * FROM dramas WHERE id=?", (c["drama_id"],))
        revenue = round(convs * 1.5 * drama["share_rate"], 2)
        is_hot = 1 if play > 100000 else 0
        db.ex("UPDATE contents SET status='已发布' WHERE id=?", (content_id,))
        db.ex("INSERT INTO own_videos(title,drama_id,publish_time,play,likes,comments,"
              "finish_rate,mount_clicks,conversions,revenue,is_hot,segment_note)"
              " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              (c["title_copy"], c["drama_id"], datetime.now().isoformat(timespec="seconds"),
               play, int(play * 0.04), int(play * 0.006), finish, clicks, convs,
               revenue, is_hot, "强冲突前置：名场面开场"))
        day = db.today()
        db.ex("INSERT INTO share_records(day,drama_id,play,conversions,revenue) VALUES(?,?,?,?,?)"
              " ON CONFLICT(day,drama_id) DO UPDATE SET play=play+excluded.play,"
              " conversions=conversions+excluded.conversions, revenue=revenue+excluded.revenue",
              (day, c["drama_id"], play, convs, revenue))
        self.log("内容发布", f"《{c['title_copy']}》已发布：播放{play} 分成¥{revenue}")
        return {"play": play, "revenue": revenue, "is_hot": is_hot}
