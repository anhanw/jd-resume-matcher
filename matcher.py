"""
核心逻辑：两步 LLM 链路 + 代码计算评分
  第 1 步 parse_jd：把 JD 解析成结构化的要求清单（必备 / 加分）
  第 2 步 match_resume：逐条判断简历是否满足每条要求，给出证据和理由
  最后 compute_score：用规则把逐条结果加权算成总分（分数由代码算，不让模型拍脑袋）
"""
import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = "deepseek-chat"


def get_client():
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("没有找到 DEEPSEEK_API_KEY，请检查 .env 文件")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def call_llm_json(system_prompt: str, user_prompt: str) -> dict:
    """调用模型并强制返回 JSON；temperature=0 让结果尽量稳定、可复现"""
    client = get_client()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content)


# ---------- 第 1 步：JD 解析 ----------
JD_PARSE_PROMPT = """你是资深招聘专家。请从岗位描述（JD）中提取招聘要求，输出 JSON。

规则：
1. must_have：JD 中明确要求的条件（如"要求""必须""具备""熟练掌握"）
2. nice_to_have：加分项（如"优先""加分""者佳"）
3. 每条要求只包含一个可验证的点，不要把多项技能合并成一条
4. category 只能取：技能 / 经验 / 学历 / 专业 / 语言 / 软素质 / 其他
5. 只提取 JD 里写了的内容，不要编造

输出格式：
{
  "job_title": "岗位名称",
  "summary": "一句话概括岗位核心职责",
  "must_have": [{"requirement": "...", "category": "..."}],
  "nice_to_have": [{"requirement": "...", "category": "..."}]
}"""


def parse_jd(jd_text: str) -> dict:
    return call_llm_json(JD_PARSE_PROMPT, f"岗位描述如下：\n{jd_text}")


# ---------- 第 2 步：逐条匹配 ----------
MATCH_PROMPT = """你是严谨的招聘评估官。请逐条判断候选人简历是否满足每一条岗位要求，输出 JSON。

判定标准：
- 满足：简历中有明确、直接的证据
- 部分满足：有相关但不完全对应的经历（如相近技能、项目中涉及但不深入）
- 不满足：简历中找不到相关证据

要求：
1. 每条要求都必须判断，不能遗漏，requirement 和 type 照抄输入
2. evidence 写简历中的具体依据；不满足时写"无"
3. 只依据简历文本判断，不要推测，也不要因为候选人整体优秀而放宽单条标准

输出格式：
{
  "matches": [
    {"requirement": "...", "type": "must_have 或 nice_to_have",
     "status": "满足 / 部分满足 / 不满足", "evidence": "...", "reason": "..."}
  ],
  "strengths": ["候选人相对这个岗位的优势"],
  "gaps": ["主要差距"],
  "suggestions": ["针对这份 JD 修改简历的具体建议"]
}"""


def match_resume(jd_struct: dict, resume_text: str) -> dict:
    requirements = (
        [{"requirement": r["requirement"], "type": "must_have"} for r in jd_struct.get("must_have", [])]
        + [{"requirement": r["requirement"], "type": "nice_to_have"} for r in jd_struct.get("nice_to_have", [])]
    )
    user_prompt = (
        f"岗位要求清单：\n{json.dumps(requirements, ensure_ascii=False, indent=2)}\n\n"
        f"候选人简历：\n{resume_text}"
    )
    return call_llm_json(MATCH_PROMPT, user_prompt)


# ---------- 评分规则（代码计算，可解释、可调） ----------
STATUS_SCORE = {"满足": 1.0, "部分满足": 0.5, "不满足": 0.0}
MUST_WEIGHT = 0.7  # 必备项占 70%，加分项占 30%


def compute_score(matches: list) -> int:
    def avg(type_):
        items = [m for m in matches if m.get("type") == type_]
        if not items:
            return None
        return sum(STATUS_SCORE.get(m.get("status", "").strip(), 0) for m in items) / len(items)

    must, nice = avg("must_have"), avg("nice_to_have")
    if must is None and nice is None:
        return 0
    if nice is None:
        score = must
    elif must is None:
        score = nice
    else:
        score = MUST_WEIGHT * must + (1 - MUST_WEIGHT) * nice
    return round(score * 100)


def score_level(score: int) -> str:
    if score >= 75:
        return "高"
    if score >= 50:
        return "中"
    return "低"


def analyze(jd_text: str, resume_text: str) -> dict:
    jd_struct = parse_jd(jd_text)
    match_result = match_resume(jd_struct, resume_text)
    matches = match_result.get("matches", [])
    score = compute_score(matches)
    return {
        "jd": jd_struct,
        "matches": matches,
        "score": score,
        "level": score_level(score),
        "strengths": match_result.get("strengths", []),
        "gaps": match_result.get("gaps", []),
        "suggestions": match_result.get("suggestions", []),
    }
