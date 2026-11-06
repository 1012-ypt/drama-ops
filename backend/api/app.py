"""FastAPI 服务：REST 接口 + 静态工作台 + 后台调度。
启动：python -m backend.api.app
"""
import csv
import io
import threading

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import chat as teamchat
from .. import config, db, llm, seed
from ..agents.benchmark import BenchmarkAgent
from ..agents.content import ContentAgent
from ..agents.deconstruct import DeconstructAgent
from ..agents.strategy import StrategyAgent
from ..agents.supervisor import SupervisorAgent
from ..collectors.thirdparty import build_collector
from ..pipeline import daily, jobs
from ..pipeline.scheduler import Scheduler

app = FastAPI(title="视频号剧目挂载分佣 AI 自运营团队")

db.init()
seed.run_if_empty()
collector = build_collector()
agents = {
    "supervisor": SupervisorAgent(),
    "benchmark": BenchmarkAgent(collector),
    "deconstruct": DeconstructAgent(),
    "content": ContentAgent(),
    "strategy": StrategyAgent(),
}
scheduler = Scheduler(agents)


@app.on_event("startup")
def _startup():
    scheduler.start()


@app.on_event("shutdown")
def _shutdown():
    scheduler.stop()


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------- 总览 ----------------
@app.get("/api/overview")
def overview():
    kpi = {
        "today_new": db.one("SELECT COUNT(*) c FROM peer_videos WHERE discovered_at>=date('now','localtime') AND violation=0")["c"],
        "tracking": db.one("SELECT COUNT(*) c FROM peer_videos WHERE track_done=0 AND violation=0")["c"],
        "late_booms": db.one("SELECT COUNT(*) c FROM peer_videos WHERE is_late_boom=1")["c"],
        "pending_contents": db.one("SELECT COUNT(*) c FROM contents WHERE status='待审核'")["c"],
        "today_revenue": round(db.one("SELECT COALESCE(SUM(revenue),0) r FROM share_records WHERE day=date('now','localtime')")["r"], 2),
        "unhandled_alerts": db.one("SELECT COUNT(*) c FROM alerts WHERE handled=0")["c"],
    }
    team = []
    for key, ag in agents.items():
        last = db.one("SELECT * FROM agent_runs WHERE agent=? ORDER BY id DESC LIMIT 1", (ag.name,))
        cnt = db.one("SELECT COUNT(*) c FROM agent_runs WHERE agent=? AND started_at>=date('now','localtime')",
                     (ag.name,))["c"]
        team.append({"key": key, "name": ag.title, "color": ag.color,
                     "today_runs": cnt, "last": last})
    return {"kpi": kpi, "team": team, "pipeline_running": jobs.pipeline_running,
            "collector_mode": config.COLLECTOR_MODE, "llm": llm.configured(),
            "patrol_interval": scheduler.interval}


@app.get("/api/agents/{name}/runs")
def agent_runs(name: str, limit: int = 30):
    return db.q("SELECT * FROM agent_runs WHERE agent=? ORDER BY id DESC LIMIT ?",
                (name, limit))


@app.post("/api/agents/{name}/run")
def run_agent(name: str):
    def bg():
        if name == "benchmark":
            agents["benchmark"].patrol(); agents["benchmark"].track()
        elif name == "deconstruct":
            agents["deconstruct"].run()
        elif name == "content":
            agents["content"].run()
        elif name == "strategy":
            agents["strategy"].plan_new_dramas(); agents["strategy"].weekly_review()
        elif name == "supervisor":
            agents["supervisor"].morning_meeting()
    if name not in agents:
        return JSONResponse({"error": "unknown agent"}, 404)
    threading.Thread(target=bg, daemon=True).start()
    return {"status": "triggered"}


# ---------------- 对标台账 / 日报 ----------------
@app.get("/api/ledger")
def ledger():
    rows = db.q(
        "SELECT pv.*, pa.name account, pa.fans, d.title drama FROM peer_videos pv"
        " JOIN peer_accounts pa ON pa.id=pv.account_id"
        " JOIN dramas d ON d.id=pv.drama_id WHERE pv.violation=0"
        " ORDER BY pv.discovered_at DESC LIMIT 100")
    for r in rows:
        snaps = db.q("SELECT * FROM snapshots WHERE video_id=? ORDER BY day_index", (r["id"],))
        r["snaps"] = snaps
        r["plays"] = [s["play"] for s in snaps]
    return rows


@app.get("/api/reports/daily")
def daily_reports():
    return db.q("SELECT * FROM daily_reports ORDER BY day DESC LIMIT 7")


# ---------------- 拆解 / 内容 / 策略 / 经验 ----------------
@app.get("/api/deconstructions")
def deconstructions():
    return db.q(
        "SELECT dc.*, ov.title video_title, ov.play, ov.finish_rate, ov.conversions,"
        " d.title drama FROM deconstructions dc"
        " JOIN own_videos ov ON ov.id=dc.own_video_id JOIN dramas d ON d.id=dc.drama_id"
        " ORDER BY dc.id DESC LIMIT 20")


@app.get("/api/contents")
def contents():
    return db.q(
        "SELECT c.*, d.title drama, d.category FROM contents c"
        " JOIN dramas d ON d.id=c.drama_id ORDER BY c.id DESC LIMIT 50")


@app.post("/api/contents/{cid}/publish")
def publish_content(cid: int):
    r = agents["content"].publish(cid)
    return r or {"error": "不存在或已发布"}


@app.post("/api/contents/{cid}/drop")
def drop_content(cid: int):
    db.ex("UPDATE contents SET status='已淘汰' WHERE id=?", (cid,))
    return {"status": "ok"}


@app.get("/api/strategies")
def strategies():
    return db.q("SELECT s.*, d.title drama, d.category FROM strategies s"
                " JOIN dramas d ON d.id=s.drama_id ORDER BY s.id DESC LIMIT 20")


@app.get("/api/experience")
def experience():
    return db.q("SELECT * FROM experiences ORDER BY score DESC, id DESC LIMIT 50")


# ---------------- 会议 / 告警 / 趋势 ----------------
@app.get("/api/meetings")
def meetings():
    return db.q("SELECT * FROM meetings ORDER BY day DESC LIMIT 7")


@app.get("/api/alerts")
def alerts():
    return db.q("SELECT * FROM alerts ORDER BY id DESC LIMIT 50")


@app.get("/api/series/revenue")
def revenue_series():
    by_day = db.q("SELECT day, SUM(revenue) revenue, SUM(play) play, SUM(conversions) conv"
                  " FROM share_records GROUP BY day ORDER BY day DESC LIMIT 14")
    by_drama = db.q("SELECT d.title, SUM(s.revenue) revenue FROM share_records s"
                    " JOIN dramas d ON d.id=s.drama_id GROUP BY d.id ORDER BY revenue DESC")
    return {"by_day": list(reversed(by_day)), "by_drama": by_drama}


# ---------------- 团队群聊（@所有人 / @单个角色）----------------
ALIASES = {"主管": "supervisor", "对标": "benchmark", "全网对标专员": "benchmark",
           "拆解": "deconstruct", "爆款拆解专员": "deconstruct", "爆款": "deconstruct",
           "内容": "content", "内容生成专员": "content",
           "策略": "strategy", "策略迭代专员": "strategy"}
ALL_WORDS = ("所有人", "大家", "全员", "all", "All", "ALL")


def _parse_mentions(message):
    """返回 (目标agent key列表, 是否@所有人)。"""
    if any(f"@{w}" in message for w in ALL_WORDS):
        return list(agents.keys()), True
    targets = []
    for alias, key in sorted(ALIASES.items(), key=lambda x: -len(x[0])):
        if f"@{alias}" in message and key not in targets:
            targets.append(key)
    return targets, False


@app.get("/api/group/history")
def group_history(limit: int = 80):
    rows = db.q("SELECT * FROM group_messages ORDER BY id DESC LIMIT ?", (limit,))
    return list(reversed(rows))


@app.post("/api/group/meeting")
def group_meeting(body: dict):
    """发起一场团队会议：生成 8~10 条群消息并落库，前端逐条展示。"""
    topic = (body.get("topic") or "").strip() or "今日运营晨会"
    msgs = teamchat.hold_meeting(topic)
    for key in {m["key"] for m in msgs}:
        agents[key].log("团队开会", f"在「{topic}」中发言")
    return {"messages": [{"key": m["key"], "title": agents[m["key"]].title,
                          "color": agents[m["key"]].color, "think": m["think"],
                          "answer": m["answer"]} for m in msgs]}


@app.post("/api/group/chat")
async def group_chat(body: dict):
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, 400)
    db.ex("INSERT INTO group_messages(sender,sender_title,color,content,created_at)"
          " VALUES('boss','老板','#64748b',?,?)", (message, db.now()))
    if teamchat.is_meeting_request(message):      # 老板喊开会 → 直接开一场
        topic = teamchat.derive_topic(message)
        msgs = teamchat.hold_meeting(topic)
        for key in {m["key"] for m in msgs}:
            agents[key].log("团队开会", f"老板群里喊开会，在「{topic}」中发言")
        replies = [{"key": m["key"], "title": agents[m["key"]].title,
                    "color": agents[m["key"]].color, "think": m["think"],
                    "answer": m["answer"]} for m in msgs]
        return {"replies": replies, "meeting": True, "topic": topic}
    targets, is_all = _parse_mentions(message)
    if not targets:
        targets = ["supervisor"]          # 没人被@时，主管统筹应答
    replies = []
    for key in targets:
        ag = agents[key]
        think, answer = await __import__("asyncio").to_thread(ag.group_reply, message)
        db.ex("INSERT INTO group_messages(sender,sender_title,color,think,content,created_at)"
              " VALUES(?,?,?,?,?,?)", (key, ag.title, ag.color, think, answer, db.now()))
        ag.log("群聊回复", f"群里被{'@所有人' if is_all else '@'}点名，回复「{message[:40]}」")
        replies.append({"key": key, "title": ag.title, "color": ag.color,
                        "think": think, "answer": answer})
    return {"replies": replies, "mentioned_all": is_all}


# ---------------- 与角色对话 ----------------
@app.get("/api/chat/{name}/history")
def chat_history(name: str, limit: int = 50):
    rows = db.q("SELECT role,content,created_at FROM chat_messages WHERE agent=?"
                " ORDER BY id DESC LIMIT ?", (name, limit))
    return list(reversed(rows))


@app.post("/api/chat/{name}")
async def chat_with_agent(name: str, body: dict):
    if name not in agents:
        return JSONResponse({"error": "unknown agent"}, 404)
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, 400)
    # 对话放后台线程跑，避免 LLM 调用阻塞；但为简化前端，这里同步返回
    answer = await __import__("asyncio").to_thread(agents[name].reply, message)
    return {"answer": answer}


# ---------------- 流程触发 / 数据导入 ----------------
@app.post("/api/pipeline/daily")
def trigger_daily():
    threading.Thread(target=daily.run_daily_flow, args=(agents,), daemon=True).start()
    return {"status": "triggered"}


@app.post("/api/jobs/patrol")
def trigger_patrol():
    threading.Thread(target=lambda: (jobs.patrol_job(agents["benchmark"], agents["supervisor"]),
                                     jobs.track_job(agents["benchmark"])), daemon=True).start()
    return {"status": "triggered"}


@app.post("/api/import/share_records")
async def import_share_records(file: UploadFile):
    """导入视频号后台导出的分成 CSV：day,drama_title,play,conversions,revenue"""
    text = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"day", "drama_title", "play", "conversions", "revenue"}
    missing = required - set(row.strip() for row in (reader.fieldnames or []))
    if missing:
        return JSONResponse({"error": f"CSV 缺少必需列: {','.join(sorted(missing))}，"
                                     "请下载页面上的模板对照"}, status_code=400)
    n = 0
    for row in reader:
        d = db.one("SELECT id FROM dramas WHERE title=?", (row["drama_title"].strip(),))
        if not d:
            db.ex("INSERT INTO dramas(title) VALUES(?)", (row["drama_title"].strip(),))
            d = db.one("SELECT id FROM dramas WHERE title=?", (row["drama_title"].strip(),))
        db.ex("INSERT OR REPLACE INTO share_records(day,drama_id,play,conversions,revenue)"
              " VALUES(?,?,?,?,?)",
              (row["day"].strip(), d["id"], int(row["play"]), int(row["conversions"]),
               float(row["revenue"])))
        n += 1
    return {"imported": n}


@app.post("/api/import/share_manual")
def import_share_manual(data: dict):
    """手动录入一条分成数据：day,drama_title,play,conversions,revenue"""
    day = (data.get("day") or db.now()[:10]).strip()
    title = (data.get("drama_title") or "").strip()
    if not title:
        return JSONResponse({"error": "剧名不能为空"}, status_code=400)
    d = db.one("SELECT id FROM dramas WHERE title=?", (title,))
    if not d:
        db.ex("INSERT INTO dramas(title) VALUES(?)", (title,))
        d = db.one("SELECT id FROM dramas WHERE title=?", (title,))
    db.ex("INSERT OR REPLACE INTO share_records(day,drama_id,play,conversions,revenue)"
          " VALUES(?,?,?,?,?)",
          (day, d["id"], int(float(data.get("play") or 0)),
           int(float(data.get("conversions") or 0)), float(data.get("revenue") or 0)))
    return {"ok": True, "drama": title, "day": day}


@app.post("/api/import/video_manual")
def import_video_manual(data: dict):
    """手动录入一条自有视频数据：title,drama_title 必填，其余可空"""
    title = (data.get("title") or "").strip()
    drama_title = (data.get("drama_title") or "").strip()
    if not title or not drama_title:
        return JSONResponse({"error": "视频标题和剧名不能为空"}, status_code=400)
    d = db.one("SELECT id FROM dramas WHERE title=?", (drama_title,))
    if not d:
        db.ex("INSERT INTO dramas(title) VALUES(?)", (drama_title,))
        d = db.one("SELECT id FROM dramas WHERE title=?", (drama_title,))
    num = lambda k: int(float(data.get(k) or 0))
    flt = lambda k: float(data.get(k) or 0)
    exist = db.one("SELECT id FROM own_videos WHERE title=? AND drama_id=?",
                   (title, d["id"]))
    if exist:
        db.ex("UPDATE own_videos SET play=?,likes=?,comments=?,finish_rate=?,"
              "mount_clicks=?,conversions=?,revenue=? WHERE id=?",
              (num("play"), num("likes"), num("comments"), flt("finish_rate"),
               num("mount_clicks"), num("conversions"), flt("revenue"), exist["id"]))
    else:
        db.ex("INSERT INTO own_videos(title,drama_id,publish_time,play,likes,comments,"
              "finish_rate,mount_clicks,conversions,revenue) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (title, d["id"], db.now(), num("play"), num("likes"), num("comments"),
               flt("finish_rate"), num("mount_clicks"), num("conversions"), flt("revenue")))
    return {"ok": True, "title": title}


@app.post("/api/import/own_videos")
async def import_own_videos(file: UploadFile):
    """导入自有账号视频数据 CSV：
    title,drama_title,publish_time,play,likes,comments,finish_rate,mount_clicks,conversions,revenue
    仅 title 和 drama_title 必填，其余可空。按 视频标题+剧目 去重更新。"""
    text = (await file.read()).decode("utf-8-sig")
    n = 0
    for row in csv.DictReader(io.StringIO(text)):
        title = (row.get("title") or "").strip()
        drama_title = (row.get("drama_title") or "").strip()
        if not title or not drama_title:
            continue
        d = db.one("SELECT id FROM dramas WHERE title=?", (drama_title,))
        if not d:
            db.ex("INSERT INTO dramas(title) VALUES(?)", (drama_title,))
            d = db.one("SELECT id FROM dramas WHERE title=?", (drama_title,))
        num = lambda k: int(float(row.get(k) or 0)) if (row.get(k) or "").strip() else 0
        flt = lambda k: float(row.get(k) or 0) if (row.get(k) or "").strip() else 0.0
        exist = db.one("SELECT id FROM own_videos WHERE title=? AND drama_id=?",
                       (title, d["id"]))
        if exist:
            db.ex("UPDATE own_videos SET play=?,likes=?,comments=?,finish_rate=?,"
                  "mount_clicks=?,conversions=?,revenue=? WHERE id=?",
                  (num("play"), num("likes"), num("comments"), flt("finish_rate"),
                   num("mount_clicks"), num("conversions"), flt("revenue"), exist["id"]))
        else:
            db.ex("INSERT INTO own_videos(title,drama_id,publish_time,play,likes,comments,"
                  "finish_rate,mount_clicks,conversions,revenue) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (title, d["id"], (row.get("publish_time") or db.now()).strip(),
                   num("play"), num("likes"), num("comments"), flt("finish_rate"),
                   num("mount_clicks"), num("conversions"), flt("revenue")))
        n += 1
    return {"imported": n}


# ---------------- 静态工作台 ----------------
import os
FRONTEND = os.path.join(config.BASE_DIR, "frontend")


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND, "index.html"))


@app.get("/api/backup")
def backup_db():
    tmp = "/tmp/ops_backup_download.db"
    db.backup_to(tmp)
    return FileResponse(tmp, filename="ops_backup.db", media_type="application/octet-stream")


@app.post("/api/restore")
async def restore_db(file: UploadFile = File(...)):
    raw = await file.read()
    tmp = "/tmp/ops_restore_upload.db"
    with open(tmp, "wb") as f:
        f.write(raw)
    try:
        db.restore_from(tmp)
    except Exception as e:
        return JSONResponse({"error": f"恢复失败：{e}（请确认上传的是本系统下载的备份文件）"}, status_code=400)
    return {"ok": True}


@app.get("/manifest.json")
def manifest():
    return FileResponse(os.path.join(FRONTEND, "manifest.json"))


@app.get("/sw.js")
def service_worker():
    return FileResponse(os.path.join(FRONTEND, "sw.js"), media_type="application/javascript")


@app.get("/icons/{name}")
def pwa_icon(name: str):
    return FileResponse(os.path.join(FRONTEND, "icons", name))


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
