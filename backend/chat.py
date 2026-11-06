"""群聊与开会：闲聊识别与短回复、群聊上下文、团队会议生成。

角色的业务数据回答仍在 agents/base.py，本模块负责：
- is_smalltalk / smalltalk_answer：闲聊识别与有人味的短回复
- recent_group_history / is_discuss_query / discuss_fallback：上下文讨论能力
- is_meeting_request / hold_meeting：团队开会（8~10 条群消息并落库）
"""
import random

from . import db

# 角色元信息（与 agents 各角色类保持一致，app 层也用它取 title/color）
TEAM = {
    "supervisor": {"title": "主管", "color": "#f472b6", "nick": "主管"},
    "benchmark": {"title": "全网对标专员", "color": "#22d3ee", "nick": "对标"},
    "deconstruct": {"title": "爆款拆解专员", "color": "#a78bfa", "nick": "拆解"},
    "content": {"title": "内容生成专员", "color": "#34d399", "nick": "内容"},
    "strategy": {"title": "策略迭代专员", "color": "#fbbf24", "nick": "策略"},
}

# ---------------- 闲聊识别 ----------------
_SMALLTALK_WORDS = (
    "在吗", "在不在", "都在吗", "都在不在", "在么", "在？", "在?", "人呢",
    "大家好", "你们好", "你好", "早上好", "晚上好", "下午好", "早啊",
    "吃了吗", "吃饭了没", "辛苦了", "谢谢", "感谢", "多谢",
    "好的", "好嘞", "收到", "嗯嗯", "哈哈", "嘿嘿", "牛逼", "厉害", "666",
    "哈喽", "嗨",
)
_SMALLTALK_EXACT = ("早", "嗯", "哦", "好", "在", "hi", "hello")
_BIZ_WORDS = (
    "数据", "播放", "分成", "对标", "爆款", "拆解", "内容", "脚本", "预案",
    "经验", "告警", "规则", "剧目", "视频", "报告", "情况", "汇报",
    "为什么", "怎么", "什么",
)
_MENTION_WORDS = (
    "所有人", "大家", "全员", "all", "All", "ALL",
    "全网对标专员", "爆款拆解专员", "内容生成专员", "策略迭代专员",
    "主管", "对标", "拆解", "爆款", "内容", "策略",
)


def _strip_mentions(message):
    text = message
    for w in _MENTION_WORDS:
        text = text.replace(f"@{w}", "")
    return text.strip()


def is_smalltalk(message):
    """短消息 + 命中闲聊词 + 不含业务词 → 闲聊。"""
    text = _strip_mentions(message.strip())
    if not text or len(text) >= 25:
        return False
    if any(b in text for b in _BIZ_WORDS):
        return False
    if text in _SMALLTALK_EXACT:
        return True
    return any(w in text for w in _SMALLTALK_WORDS)


def smalltalk_think(title, message):
    return (f"① 理解问题：「{message[:30]}」是打招呼/点名，非业务问题\n"
            "② 调取数据：只轻量看一眼本岗状态，不拉报表\n"
            "③ 观点形成：像同事一样简短回应即可")


def smalltalk_answer(key, title):
    """闲聊短回复：1~3 句、有人味、带角色性格，最多顺带一个轻量数据点。"""
    if key == "benchmark":
        total = db.one("SELECT COUNT(*) c FROM peer_videos WHERE violation=0")["c"]
        return random.choice([
            f"在的老板！刚巡检完一轮，台账{total}条，有爆款我随时喊你。",
            f"在呢在呢，同行那边我盯着呢，台账{total}条，有动静第一时间说。",
        ])
    if key == "deconstruct":
        pending = db.one(
            "SELECT COUNT(*) c FROM own_videos WHERE is_hot=1 AND id NOT IN"
            " (SELECT own_video_id FROM deconstructions)")["c"]
        if pending:
            return f"在～手上还有{pending}条爆款排队等拆，要不要我先拆一条给你看？"
        return "在呢老板，正研究昨天的爆款结构，有啥想让我拆的尽管丢过来。"
    if key == "content":
        pend = db.one("SELECT COUNT(*) c FROM contents WHERE status='待审核'")["c"]
        return random.choice([
            f"在呢，手里还有{pend}条待审内容，要不要我出一条新的？",
            f"在的在的，队列里压着{pend}条稿，你说发我就排期。",
        ])
    if key == "strategy":
        new_cnt = db.one("SELECT COUNT(*) c FROM dramas WHERE status='新剧'")["c"]
        if new_cnt:
            return f"在的，{new_cnt}部新剧的预案我都排好了，放心。"
        return "在呢，现有策略我盯着，低效的我随时淘汰。"
    # supervisor
    return random.choice([
        "都在，团队在正常运转。有事您吩咐。",
        "在呢，大家都各司其职，有事您直接说。",
    ])


# ---------------- 群聊上下文 / 讨论能力 ----------------
_DISCUSS_WORDS = ("他", "她", "刚才", "上面", "同意", "觉得怎么", "怎么看", "你们说")
_DISCUSS_ACT = {
    "supervisor": "我来协调大家跟上",
    "benchmark": "我再去拉一轮同行数据验证",
    "deconstruct": "我把它跟我们自有爆款对着拆一遍",
    "content": "我可以直接按这个方向出一条内容试试",
    "strategy": "我评估一下要不要写进预案",
}


def recent_group_history(limit=8):
    """最近群聊消息（正序），作为各角色回复时的上下文。"""
    rows = db.q("SELECT sender,sender_title,content FROM group_messages"
                " ORDER BY id DESC LIMIT ?", (limit,))
    return list(reversed(rows))


def is_discuss_query(message):
    """老板是否在追问/评价群里别人刚说的内容。"""
    return any(w in message for w in _DISCUSS_WORDS)


_ROLE_ALIAS = {"对标": "benchmark", "拆解": "deconstruct", "爆款": "deconstruct",
               "内容": "content", "策略": "strategy", "主管": "supervisor"}


def discuss_fallback(key, facts, history, message=""):
    """追问场景的无 LLM 兜底：优先引用老板点名的角色，否则引用最近发言者。"""
    others = [h for h in history if h["sender"] not in ("boss", key) and h["content"]]
    if not others:
        return None
    named = next((k for a, k in _ROLE_ALIAS.items() if a in message and k != key), None)
    pool = [h for h in others if h["sender"] == named] if named else others
    last = (pool or others)[-1]
    said = last["content"].replace("\n", " ")[:24]
    text = f"{last['sender_title']}刚说的「{said}」，我看过相关数据了，确实值得跟。"
    if facts:
        text += f"我这边的情况是：{facts[0]}。"
    return text + _DISCUSS_ACT.get(key, "我这边配合推进") + "。"


# ---------------- 开会 ----------------
MEETING_WORDS = ("开会", "晨会", "复盘会", "开个会", "讨论一下")


def is_meeting_request(message):
    return any(w in message for w in MEETING_WORDS)


def derive_topic(message):
    """从老板原话推断议题。"""
    if "复盘" in message:
        return "分成复盘会"
    if "新剧" in message:
        return "新剧预案研讨会"
    return "今日运营晨会"


def _fmt_play(n):
    n = n or 0
    return f"{n / 10000:.1f}万" if n >= 10000 else str(int(n))


def _meeting_facts():
    f = {}
    f["total"] = db.one("SELECT COUNT(*) c FROM peer_videos WHERE violation=0")["c"]
    f["today_new"] = db.one(
        "SELECT COUNT(*) c FROM peer_videos WHERE discovered_at>=date('now','localtime')"
        " AND violation=0")["c"]
    f["tracking"] = db.one(
        "SELECT COUNT(*) c FROM peer_videos WHERE track_done=0 AND violation=0")["c"]
    f["top"] = db.q(
        "SELECT pv.title, pa.name account, s.play FROM peer_videos pv"
        " JOIN peer_accounts pa ON pa.id=pv.account_id"
        " JOIN snapshots s ON s.video_id=pv.id AND s.day_index=3"
        " WHERE pv.violation=0 ORDER BY s.play DESC LIMIT 2")
    booms = db.q("SELECT pv.id, pv.title, pv.drama_id FROM peer_videos pv"
                 " WHERE pv.is_late_boom=1 LIMIT 3")
    for b in booms:
        snaps = {s["day_index"]: s["play"] for s in
                 db.q("SELECT day_index,play FROM snapshots WHERE video_id=?", (b["id"],))}
        b["d1"], b["d3"] = snaps.get(1) or 0, snaps.get(3) or 0
        d = db.one("SELECT title FROM dramas WHERE id=?", (b["drama_id"],))
        b["drama"] = d["title"] if d else ""
        b["own"] = db.one(
            "SELECT title,play,finish_rate FROM own_videos WHERE drama_id=?"
            " ORDER BY play DESC LIMIT 1", (b["drama_id"],))
    f["booms"] = booms
    f["pending_contents"] = db.one(
        "SELECT COUNT(*) c FROM contents WHERE status='待审核'")["c"]
    f["own"] = db.q(
        "SELECT ov.title, ov.play, ov.finish_rate, ov.revenue, d.title drama"
        " FROM own_videos ov JOIN dramas d ON d.id=ov.drama_id ORDER BY ov.id DESC LIMIT 3")
    f["new_dramas"] = db.q("SELECT * FROM dramas WHERE status='新剧'")
    f["strategies"] = db.q(
        "SELECT s.*, d.title drama FROM strategies s JOIN dramas d ON d.id=s.drama_id"
        " WHERE s.status='生效中' ORDER BY s.id DESC LIMIT 5")
    f["rev_today"] = db.one(
        "SELECT COALESCE(SUM(revenue),0) r FROM share_records"
        " WHERE day=date('now','localtime')")["r"]
    f["rev_yest"] = db.one(
        "SELECT COALESCE(SUM(revenue),0) r FROM share_records"
        " WHERE day=date('now','localtime','-1 day')")["r"]
    ex = db.one("SELECT content FROM alerts WHERE type='独家剧目'"
                " ORDER BY id DESC LIMIT 1")
    f["exclusive_alert"] = ex["content"] if ex else ""
    return f


def _mthink(who, topic, data, view):
    return (f"① 议题理解：本次「{topic}」，轮到我（{who}）发言\n"
            f"② 调取数据：{data}\n"
            f"③ 观点形成：{view}")


def hold_meeting(topic=""):
    """生成一场 8~10 条的团队会议，逐条写入 group_messages，返回 [{key,think,answer}]。"""
    topic = (topic or "").strip() or "今日运营晨会"
    mode = "review" if "复盘" in topic else ("newdrama" if "新剧" in topic else "daily")
    f = _meeting_facts()
    msgs = _compose_meeting(mode, topic, f)
    for m in msgs:
        db.ex("INSERT INTO group_messages(sender,sender_title,color,think,content,created_at)"
              " VALUES(?,?,?,?,?,?)",
              (m["key"], TEAM[m["key"]]["title"], TEAM[m["key"]]["color"],
               m["think"], m["answer"], db.now()))
    return msgs


def _compose_meeting(mode, topic, f):
    top1 = f["top"][0] if f["top"] else None
    boom = f["booms"][0] if f["booms"] else None
    own = (boom.get("own") if boom and boom.get("own") else None) or \
          (f["own"][0] if f["own"] else None)
    nd = f["new_dramas"][0] if f["new_dramas"] else None
    nd_fit = "待验证"
    if nd:
        for s in f["strategies"]:
            if s["drama"] == nd["title"]:
                nd_fit = s["fit"]
                break
    msgs = []
    add = msgs.append

    # ---- 1. 主管开场 ----
    if mode == "review":
        pct = ((f["rev_today"] - f["rev_yest"]) / f["rev_yest"] * 100) if f["rev_yest"] else 0
        opening = (f"都到齐了吧，开个复盘会，议题：{topic}。核心一件事：分成昨天"
                   f"¥{f['rev_yest']:.0f}、今天¥{f['rev_today']:.0f}，"
                   f"{'涨' if pct >= 0 else '跌'}了{abs(pct):.0f}%。到底是外部大盘的问题"
                   "还是我们自己的问题，今天聊透。对标先说外部情况。")
        oview = "把分成涨跌的原因聊透，当场定改进动作"
    elif mode == "newdrama":
        opening = (f"都到齐了，今天议题：{topic}。新剧"
                   f"{('《' + nd['title'] + '》') if nd else '这几部'}要不要上、怎么上，"
                   "今天定下来。对标先说同行验证情况。")
        oview = "围绕新剧预案把同行验证、产出、风险聊透，当场拍板"
    else:
        opening = (f"都到齐了吧，咱开个短会，今天议题：{topic}。还是老顺序：对标先说大盘，"
                   "拆解、内容、策略依次跟，有分歧当场聊，最后我定分工。对标，你先。")
        oview = "按惯例过一遍大盘、拆解、产出和新剧，当场定今日分工"
    add({"key": "supervisor",
         "think": _mthink("主管", topic, "团队5人在线状态、今日各角色运行情况", oview),
         "answer": opening})

    # ---- 2. 对标发言（真实台账数据）----
    b_data = (f"对标台账{f['total']}条、24h新入库{f['today_new']}条、"
              f"72h追踪中{f['tracking']}条、TOP作品与滞后爆款")
    b_ans = (f"我先说大盘。过去24小时新入库{f['today_new']}条，台账一共{f['total']}条，"
             f"{f['tracking']}条还在72小时追踪里。")
    if top1:
        b_ans += (f"目前跑得最好的是{top1['account']}的《{top1['title']}》，"
                  f"三日播放冲到{_fmt_play(top1['play'])}。")
    if boom:
        b_ans += (f"还有件事我得多说一句：挖到个滞后爆款《{boom['title']}》，"
                  f"首日才{_fmt_play(boom['d1'])}，第三天干到{_fmt_play(boom['d3'])}，"
                  "这种慢热钩子咱们还没试过，我建议今天重点聊它。")
    else:
        b_ans += "滞后爆款这期没有新增，追踪中的我继续盯。"
    add({"key": "benchmark",
         "think": _mthink("对标", topic, b_data, "大盘量稳，滞后爆款值得团队跟进"),
         "answer": b_ans})

    # ---- 3. 拆解发言（引用对标）----
    if boom:
        ref = f"对标刚提到的《{boom['title']}》"
    elif top1:
        ref = f"对标刚说的《{top1['title']}》"
    else:
        ref = "对标刚说的大盘"
    if own:
        d_ans = (f"{ref}，我专门去对了一下。我们自有同剧的数据：{own['title']}，"
                 f"播放{_fmt_play(own['play'])}、完播{own['finish_rate']:.0%}。"
                 "我的判断是：它那套钩子我们能学，但它挂载引导做得糙，"
                 "咱们的卡断式引导转化明显更好——学钩子，引导保留咱们自己的。")
    else:
        d_ans = (f"{ref}，结构确实凶。咱们自有内容还差在开头3秒的情绪浓度，"
                 "这一点我今天补进拆解结论，内容侧直接能用。")
    add({"key": "deconstruct",
         "think": _mthink("拆解", topic,
                          f"对标说的作品 + 自有视频{own['title'][:16] if own else '（暂无）'}"
                          f"（完播{own['finish_rate']:.0%}）" if own else "对标作品与自有爆款对照",
                          "钩子可学、引导保留我们自己的卡断式"),
         "answer": d_ans})

    # ---- 4. 内容发言（基于前两人给产出计划）----
    drama_focus = (boom["drama"] if boom and boom.get("drama") else
                   (own["drama"] if own and own.get("drama") else "在推剧目"))
    c_ans = (f"那今天产出方向就清楚了：我按对标说的慢热钩子给《{drama_focus}》出两条，"
             "引导按拆解说的用卡断式，排21:30睡前黄金档。"
             f"队列里还压着{f['pending_contents']}条待审，老板抽空过一眼，过了我就排期发。")
    add({"key": "content",
         "think": _mthink("内容", topic,
                          f"待审队列{f['pending_contents']}条、在推剧目、拆解结论",
                          "按慢热钩子+卡断引导出2条，睡前黄金档优先"),
         "answer": c_ans})

    # ---- 5. 策略发言（新剧预案+风险）----
    if nd:
        risk = ("它分成比例高但同行验证还少，首发量别一下打满，先小步试水"
                if not f["exclusive_alert"] else
                f"{f['exclusive_alert'][:55]}——窗口期估计就这几天，要么快跟要么绕开")
        s_ans = (f"新剧我补一下。在库新剧{len(f['new_dramas'])}部，《{nd['title']}》预案已生效，"
                 f"适配度{nd_fit}，首周走冲突前置版抢首发，二轮切悬念钩子版拉长尾。"
                 f"风险有一个：{risk}。")
    else:
        s_ans = ("新剧库这期没有新增，我把现有生效预案又核了一遍，"
                 "低效的我直接淘汰，流量集中在跑得动的剧目上。")
    add({"key": "strategy",
         "think": _mthink("策略", topic,
                          (f"新剧{len(f['new_dramas'])}部、《{nd['title']}》预案适配度{nd_fit}"
                           if nd else "生效策略回溯"),
                          "预案已就位，但首发要控制节奏防风险"),
         "answer": s_ans})

    # ---- 6/7. 讨论轮：分歧 + 折中，互相@ ----
    target = f"《{nd['title']}》" if nd else (f"《{boom['title']}》" if boom else "这个新方向")
    if mode == "review":
        d1 = ("@拆解 我提个风险：大盘稳不假，但同行那套夸张封面咱们抄不了，"
              "审核最近收紧了，别到时候流量没蹭到先吃违规。你拆过同行那条，你觉得呢？")
        d2 = ("@对标 这提醒对，夸张封面确实不能碰。折中一下：钩子学它的情绪点，"
              "封面用我们自己的风格，@内容 今晚那条就按这个来，明天看数据说话。")
        d1_key, d2_key = "benchmark", "deconstruct"
        d1_data = "同行封面风格 + 近期审核规则告警"
        d2_data = "拆解过的封面合规案例 + 自有爆款结构"
    elif nd:
        d1 = (f"@拆解 我插个不同意见。{target}同行数据现在就那么几条，直接押首发我心里没底，"
              "怕是伪需求。你拆过同类钩子，你怎么看？")
        d2 = (f"@对标 你这担心有道理，不过同类钩子我拆过，完播数据其实不差。折中一下："
              "先小批量出2条试水，跑48小时，数据过线再加大，不过线就撤。"
              "@内容 你按这个节奏排，行吧？")
        d1_key, d2_key = "benchmark", "deconstruct"
        d1_data = f"{target}同行作品数与峰值播放"
        d2_data = "同类钩子历史拆解结论与完播均值"
    else:
        d1 = (f"@拆解 我有个不同看法。{target}这种慢热型万一只是个案呢，直接全量跟风险不小，"
              "要不再观察两条同类？你怎么看？")
        d2 = ("@对标 稳一点我赞成，但等太久红利就没了。折中：先出2条试水，跑48小时，"
              "数据过线再全量，@内容 今晚先排一条试试？")
        d1_key, d2_key = "benchmark", "deconstruct"
        d1_data = f"{target}的首日/三日曲线形态"
        d2_data = "滞后爆款共性与历史试水转化"
    add({"key": d1_key,
         "think": _mthink(TEAM[d1_key]["nick"], topic, d1_data,
                          "对这个方向有风险顾虑，当场提出来"),
         "answer": d1})
    add({"key": d2_key,
         "think": _mthink(TEAM[d2_key]["nick"], topic, d2_data,
                          "认可风险但不想错失窗口，给小步快跑的折中方案"),
         "answer": d2})

    # ---- 8. 主管总结：结论+分工 ----
    boom_t = f"《{boom['title']}》" if boom else "追踪中的作品"
    own_t = own["title"][:20] if own else "自有爆款"
    if mode == "review":
        summary = (f"结论清楚了：分成波动主因在内部，是完播和转化的问题。分工——对标盯紧滞后爆款"
                   f"和审核规则；拆解把完播低的逐条复盘；内容今晚按新钩子出一条，明早看数据；"
                   "策略把垫底策略淘汰掉、新剧预案补上。明天同一时间再对一次数，散会！")
        s_view = "分成波动主因在内部，定四条改进动作，明天复盘"
    elif mode == "newdrama" and nd:
        summary = (f"定了：《{nd['title']}》今晚首发一条试温，明早看数据决定第二条。"
                   "分工——对标盯同行有没有新动作；拆解今晚跟首发数据，完播一掉就报；"
                   "内容把两条都备好；策略预案按折中节奏执行。散会，干活。")
        s_view = "新剧小步首发，明早用数据决定加不加码"
    else:
        summary = (f"行，就这么定：新方向先小步试水，不押重注。分工——对标继续盯{boom_t}的"
                   f"72小时曲线；拆解今天把{own_t}的完整拆解出了；内容按拆解说的出2条试水，"
                   "睡前黄金档优先；策略把新剧预案的风险再核一遍。有异动我随时同步，散会！")
        s_view = "小步试水不押重注，四条分工落实到人"
    add({"key": "supervisor",
         "think": _mthink("主管", topic, "刚才全员的发言与分歧点", s_view),
         "answer": summary})
    return msgs
