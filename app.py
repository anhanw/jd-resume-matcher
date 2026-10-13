"""Streamlit 界面：输入 JD 和简历 -> 调用 matcher.analyze -> 展示评分和逐条结果"""
import streamlit as st
import pandas as pd
from pypdf import PdfReader
from matcher import analyze

st.set_page_config(page_title="JD Resume Matcher", page_icon="🎯", layout="wide")

st.title("🎯 JD × 简历匹配度分析")
st.caption("粘贴岗位描述和简历，AI 自动解析岗位要求，逐条判断匹配情况，并给出评分与理由。")

col1, col2 = st.columns(2)
with col1:
    jd_text = st.text_area("岗位描述（JD）", height=360, placeholder="把招聘 JD 粘贴到这里")
with col2:
    uploaded = st.file_uploader("上传简历 PDF（可选）", type="pdf")
    resume_default = ""
    if uploaded:
        reader = PdfReader(uploaded)
        resume_default = "\n".join(page.extract_text() or "" for page in reader.pages)
    resume_text = st.text_area(
        "简历内容", value=resume_default, height=260,
        placeholder="上传 PDF 会自动填入，也可以直接粘贴简历文字",
    )

if st.button("开始分析", type="primary"):
    if not jd_text.strip() or not resume_text.strip():
        st.warning("请先填写 JD 和简历内容")
        st.stop()

    with st.spinner("正在解析 JD 并逐条比对，大约需要 20–40 秒…"):
        try:
            result = analyze(jd_text, resume_text)
        except Exception as e:
            st.error(f"分析出错：{e}")
            st.stop()

    matches = result["matches"]
    met = sum(1 for m in matches if m.get("status") == "满足")

    st.divider()
    st.subheader(f"岗位：{result['jd'].get('job_title', '未识别')}")
    st.write(result["jd"].get("summary", ""))

    m1, m2, m3 = st.columns(3)
    m1.metric("匹配度评分", f"{result['score']} / 100")
    m2.metric("匹配等级", result["level"])
    m3.metric("完全满足的要求", f"{met} / {len(matches)}")

    st.subheader("逐条匹配情况")
    icon = {"满足": "✅ 满足", "部分满足": "🟡 部分满足", "不满足": "❌ 不满足"}
    type_name = {"must_have": "必备", "nice_to_have": "加分"}
    df = pd.DataFrame([
        {
            "类型": type_name.get(m.get("type"), m.get("type")),
            "岗位要求": m.get("requirement"),
            "结果": icon.get(m.get("status"), m.get("status")),
            "简历依据": m.get("evidence"),
            "理由": m.get("reason"),
        }
        for m in matches
    ])
    st.dataframe(df, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("👍 优势")
        for s in result["strengths"]:
            st.markdown(f"- {s}")
    with c2:
        st.subheader("⚠️ 差距")
        for g in result["gaps"]:
            st.markdown(f"- {g}")

    st.subheader("✏️ 简历修改建议")
    for s in result["suggestions"]:
        st.markdown(f"- {s}")

    with st.expander("查看 JD 解析结果（原始 JSON）"):
        st.json(result["jd"])

    st.caption("评分规则：必备项占 70%、加分项占 30%；满足 = 1，部分满足 = 0.5，不满足 = 0。")
