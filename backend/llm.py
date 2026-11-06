"""LLM 抽象：配置了 LLM_BASE/LLM_KEY 则走 OpenAI 兼容接口做叙事润色；
未配置时使用内置模板生成，保证系统无外部依赖也能完整自运行。"""
import requests

from . import config

_INTRO = {
    "benchmark": "【对标专员复盘】",
    "deconstruct": "【爆款拆解结论】",
    "content": "【内容生成说明】",
    "strategy": "【策略研判】",
    "meeting": "【主管早会纪要】",
}


def configured():
    return bool(config.LLM_BASE and config.LLM_KEY)


def chat(system, prompt, timeout=30):
    """真实 LLM 调用；失败时回退 None，调用方需有兜底。"""
    if not configured():
        return None
    try:
        r = requests.post(
            config.LLM_BASE.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {config.LLM_KEY}"},
            json={"model": config.LLM_MODEL,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": prompt}],
                  "temperature": 0.7},
            timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def narrative(kind, facts):
    """生成叙事文本。facts: 结构化的要点字符串列表。优先真实 LLM，否则模板拼装。"""
    joined = "\n".join(f"- {f}" for f in facts if f)
    if configured():
        sys = "你是视频号短剧挂载分佣运营专家，输出精炼的中文运营结论，不超过200字。"
        out = chat(sys, f"基于以下事实输出结论：\n{joined}")
        if out:
            return out
    # 模板兜底：要点直接成文，保证可读、可用
    body = "；".join(f.rstrip("。") for f in facts if f)
    return f"{_INTRO.get(kind, '')}{body}。"
