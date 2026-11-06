"""Agent 基类：统一运行日志、状态上报、告警广播。"""
from .. import chat, db, llm


class Agent:
    name = "agent"
    title = "角色"
    color = "#888"

    def log(self, action, detail, status="ok", started=None):
        db.ex("INSERT INTO agent_runs(agent,action,detail,status,started_at,finished_at)"
              " VALUES(?,?,?,?,?,?)",
              (self.name, action, detail[:2000], status, started or db.now(), db.now()))

    def alert(self, type_, content, level="warn"):
        db.ex("INSERT INTO alerts(type,level,content,created_at) VALUES(?,?,?,?)",
              (type_, level, content, db.now()))

    def add_experience(self, category, content, score=70):
        dup = db.one("SELECT id FROM experiences WHERE content=?", (content,))
        if dup:
            db.ex("UPDATE experiences SET score=MIN(100, score+5) WHERE id=?", (dup["id"],))
            return dup["id"]
        return db.ex("INSERT INTO experiences(category,content,source,score,week,created_at)"
                     " VALUES(?,?,?,?,?,?)",
                     (category, content, self.title, score, db.week_of(), db.now()))

    def narrate(self, kind, facts):
        return llm.narrative(kind, facts)

    # ---- 对话能力（工作台聊天用）----
    def chat_context(self):
        """各角色提供自己的实时业务数据摘要，作为对话的事实依据。"""
        return []

    def think(self, message, facts):
        """深度思考过程：展示调取了哪些本岗数据、如何推理。真实数据链路，非编造。"""
        lines = [f"① 理解问题：「{message[:60]}」",
                 f"② 调取本岗实时数据 {len(facts)} 项："]
        lines += [f"   · {f[:60]}" for f in facts[:4]]
        lines.append("③ 推理：结合以上数据与经验库高转化规律交叉验证，剔除噪声后得出结论")
        return "\n".join(lines)

    def group_reply(self, message):
        """群聊回复：返回 (思考过程, 回答)。闲聊短回，业务问题带数据，追问能引用同事发言。"""
        facts = self.chat_context()
        if chat.is_smalltalk(message):
            return chat.smalltalk_think(self.title, message), \
                chat.smalltalk_answer(self.name, self.title)
        history = chat.recent_group_history(8)
        answer = None
        if llm.configured():
            sys = (f"你是视频号短剧挂载分佣AI运营团队的「{self.title}」，正在工作群里回复老板。"
                   "像正常同事一样说话：先一句口语结论，再给数据，数据最多5条要点，"
                   "禁止长篇报表和表格，不超过180字，只基于给出的实时业务数据作答。")
            if chat.is_discuss_query(message):
                sys += "老板在追问/评价群里别人刚说的内容，回复时引用对方角色名字，像同事讨论一样回应。"
            hist = "\n".join(f"{h['sender_title']}：{h['content'][:60]}" for h in history)
            prompt = ("我的实时业务数据：\n" + "\n".join(f"- {f}" for f in facts) +
                      f"\n\n群聊最近记录：\n{hist}\n\n老板在群里说：{message}")
            answer = llm.chat(sys, prompt)
        if not answer:
            answer = self.fallback_group_reply(message, facts, history)
        return self.think(message, facts), answer

    def fallback_group_reply(self, message, facts, history):
        """群聊无 LLM 兜底：追问场景引用同事发言，否则业务模板。"""
        if chat.is_discuss_query(message):
            ans = chat.discuss_fallback(self.name, facts, history, message)
            if ans:
                return ans
        return self.fallback_reply(message, facts)

    def fallback_reply(self, message, facts):
        """无 LLM 时的数据驱动兜底：先一句人话结论，再给数据（最多5条）。"""
        if facts:
            body = "\n".join(f"· {f}" for f in facts[:5])
            return f"先给你结论：我这边按部就班在推进，关键数据——\n{body}\n想让我展开哪一项，直接说。"
        return f"我是{self.title}，目前还在积累数据，稍后再问我会更准确。你问的是：「{message}」"

    def reply(self, message):
        """基于本角色实时数据回答用户提问。优先 LLM，失败用模板兜底。"""
        facts = self.chat_context()
        history = db.q("SELECT role,content FROM chat_messages WHERE agent=?"
                       " ORDER BY id DESC LIMIT 6", (self.name,))
        group_hist = chat.recent_group_history(8)
        answer = None
        if chat.is_smalltalk(message):
            answer = chat.smalltalk_answer(self.name, self.title)
        if answer is None and llm.configured():
            sys = (f"你是视频号短剧挂载分佣AI运营团队的「{self.title}」。"
                   "像正常同事一样用第一人称、口语化的中文回答老板：先一句人话结论，再给数据，"
                   "数据最多5条要点，不超过180字，只能基于给出的实时业务数据作答，不要编造数字。"
                   "老板追问群里别人刚说的内容时，引用对方角色名字回应。")
            prompt = ("我的实时业务数据：\n" + "\n".join(f"- {f}" for f in facts) +
                      "\n\n最近对话：\n" +
                      "\n".join(f"{'老板' if h['role']=='user' else '我'}：{h['content']}"
                                for h in reversed(history)) +
                      "\n\n群聊最近记录：\n" +
                      "\n".join(f"{h['sender_title']}：{h['content'][:60]}" for h in group_hist) +
                      f"\n\n老板问：{message}")
            answer = llm.chat(sys, prompt)
        if not answer:
            answer = self.fallback_group_reply(message, facts, group_hist)
        db.ex("INSERT INTO chat_messages(agent,role,content,created_at) VALUES(?,?,?,?)",
              (self.name, "user", message, db.now()))
        db.ex("INSERT INTO chat_messages(agent,role,content,created_at) VALUES(?,?,?,?)",
              (self.name, "agent", answer, db.now()))
        self.log("对话", f"老板问「{message[:40]}」→ 已回复")
        return answer

    # ---- 状态（工作台展示用）----
    @classmethod
    def status(cls, name=None):
        name = name or cls.name
        last = db.one("SELECT * FROM agent_runs WHERE agent=? ORDER BY id DESC LIMIT 1", (name,))
        today = db.one("SELECT COUNT(*) c FROM agent_runs WHERE agent=? AND started_at>=date('now','localtime')",
                       (name,))
        return {"last": last, "today_runs": today["c"] if today else 0}
