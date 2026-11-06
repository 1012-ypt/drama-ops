"""每日自运行流程：
对标日报 → 主管早会同步异动 → 爆款拆解 → 内容产出 → 新剧预案 → 发布复盘 → 经验入库。
"""
from .. import db
from . import jobs


def run_daily_flow(agents):
    """agents: dict(supervisor=, benchmark=, deconstruct=, content=, strategy=)"""
    if jobs.pipeline_running:
        return {"status": "busy", "msg": "流程正在运行中"}
    jobs.pipeline_running = True
    steps = []

    def step(name, fn):
        try:
            r = fn()
            steps.append({"step": name, "status": "ok", "result": str(r)[:300]})
        except Exception as e:
            steps.append({"step": name, "status": "error", "result": str(e)})

    try:
        step("对标日报+跨天复盘", agents["benchmark"].daily_report)
        step("主管早会·同步异动", agents["supervisor"].morning_meeting)
        step("自有爆款拆解", agents["deconstruct"].run)
        step("当日内容产出", agents["content"].run)
        step("新剧预案更新", agents["strategy"].plan_new_dramas)
        step("发布分成复盘", _revenue_review)
        step("有效经验入库", agents["supervisor"].weekly_experience_review)
    finally:
        jobs.pipeline_running = False
    return {"status": "done", "steps": steps}


def _revenue_review():
    """发布后全员复盘分成涨幅，产出复盘记录。"""
    rows = db.q(
        "SELECT d.title, s.day, s.revenue,"
        " (SELECT revenue FROM share_records p WHERE p.drama_id=s.drama_id"
        "  AND p.day=date(s.day,'-1 day')) prev"
        " FROM share_records s JOIN dramas d ON d.id=s.drama_id"
        " WHERE s.day>=date('now','localtime','-2 day') ORDER BY s.revenue DESC")
    ups = [r for r in rows if r["prev"] and r["revenue"] > r["prev"] * 1.2]
    for r in ups:
        db.ex("INSERT INTO experiences(category,content,source,score,week,created_at)"
              " VALUES('分成复盘',?,?,?,?,?)",
              (f"《{r['title']}》{r['day']}分成¥{r['revenue']:.0f}，环比上涨"
               f"{(r['revenue'] / r['prev'] - 1):.0%}，该推广路径有效，加分复用",
               "发布复盘", 80, db.week_of(), db.now()))
    return f"复盘完成：{len(ups)} 部剧分成显著上涨"
