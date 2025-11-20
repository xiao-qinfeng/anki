import streamlit as st
import trafilatura
import pdfplumber
from openai import OpenAI
import pandas as pd
import json

# === 1. 页面基础设置 ===
st.set_page_config(
    page_title="KnowledgeMiner - 智能知识卡片生成器",
    page_icon="⛏️",
    layout="wide"
)

# 初始化 Session State (防止交互时数据丢失)
if "generated_df" not in st.session_state:
    st.session_state.generated_df = None
if "raw_text_cache" not in st.session_state:
    st.session_state.raw_text_cache = ""

st.title("⛏️ KnowledgeMiner: 你的知识炼金术师")
st.markdown("支持文章、PDF电子书、以及 **AI对话记录** 批量转为 Anki 卡片")

# === 2. 侧边栏：设置面板 ===
with st.sidebar:
    st.header("⚙️ 参数设置")
    
    # API 配置
    api_key = st.text_input("API Key (DeepSeek/OpenAI)", type="password", help="推荐使用 DeepSeek，性价比极高")
    base_url = st.text_input("Base URL", value="https://api.deepseek.com", help="DeepSeek 请填入 https://api.deepseek.com")
    model_name = st.text_input("模型名称", value="deepseek-chat")
    
    st.markdown("---")
    st.subheader("🎨 卡片生成模式")
    
    # 核心功能：模式选择器
    mode_selection = st.radio(
        "选择你的素材类型：",
        ("🤖 AI对话/聊天记录 (推荐)", "📄 概念解释/理论文章", "🔤 英语单词/语言学习"),
        index=0
    )

    # 根据选择，自动切换 Prompt
    if mode_selection == "🤖 AI对话/聊天记录 (推荐)":
        default_prompt = """
        你是一个专业的知识萃取专家。用户将提供一段“人类与AI”的对话记录。
        
        你的任务是：
        1. **降噪**：忽略所有的客套话（如“你好”、“谢谢”、“明白了”、“请问”等）。
        2. **提炼**：识别用户感到困惑的“核心问题”和AI提供的“关键解答”。
        3. **压缩**：将啰嗦的解释压缩为简练的笔记（Bullet points）。
        4. **格式**：输出严格的 JSON 列表。

        JSON 字段要求：
        - Front: 用户原本想问的核心概念或问题。
        - Back: 经过总结的答案（支持 HTML 换行 <br>）。
        - Tags: 自动生成标签。

        示例：
        [{"Front": "Python中列表和元组的区别？", "Back": "1. 列表(List)是可变的 [...]<br>2. 元组(Tuple)是不可变的 [...]", "Tags": "Python 数据结构"}]
        """
        
    elif mode_selection == "📄 概念解释/理论文章":
        default_prompt = """
        你是一个Anki制卡专家。请阅读文章，提取核心知识点。
        
        任务要求：
        1. 提取文中的专有名词、理论或反直觉的观点。
        2. 解释要通俗易懂，多用比喻。
        3. 严格输出 JSON 列表。
        
        JSON 字段要求：
        - Front: 概念名称或问题。
        - Back: 详细解释。
        - Tags: 标签。
        """
        
    else: # 英语学习模式
        default_prompt = """
        你是一个语言学习助手。请提取文中的生词或短语。
        
        JSON 字段要求：
        - Front: 英文单词/短语。
        - Back: 中文释义 + 一个双语例句（用 <br> 换行）。
        - Tags: 标签（如 #商务英语 #动词）。
        """

    system_prompt = st.text_area("系统提示词 (System Prompt)", value=default_prompt, height=250)
    
    # 添加重置按钮
    if st.button("🗑️ 清空当前结果"):
        st.session_state.generated_df = None
        st.rerun()


# === 3. 核心功能函数 ===

def extract_url(url):
    """从网址抓取正文"""
    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        raise Exception("无法连接到该网址，请检查链接是否有效。")
    return trafilatura.extract(downloaded)

def extract_pdf(uploaded_file):
    """解析 PDF 文本"""
    text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        # 考虑到Token限制，目前仅读取前 10 页
        for page in pdf.pages[:10]: 
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def generate_cards(text, api_key, base_url, model):
    """调用 AI 生成卡片"""
    client = OpenAI(api_key=api_key, base_url=base_url)
    
    truncated_text = text[:8000] 
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请处理以下内容：\n\n{truncated_text}"}
        ],
        temperature=0.1,
        response_format={ "type": "json_object" } 
    )
    return response.choices[0].message.content


# === 4. 主界面布局 ===

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📥 第一步：导入素材")
    tab_text, tab_pdf, tab_url = st.tabs(["📝 粘贴文本/对话", "📄 上传 PDF", "🔗 解析 URL"])
    
    raw_text = ""
    
    # 文本/对话输入框
    with tab_text:
        st.info("💡 提示：如果是对话记录，直接全选复制，粘贴到这里即可。")
        text_input = st.text_area("在此处粘贴", height=300, placeholder="User: 什么是递归？\nAI: 递归就是...")
        if text_input:
            raw_text = text_input

    # PDF 上传框
    with tab_pdf:
        uploaded_pdf = st.file_uploader("上传 PDF 文件", type="pdf")
        if uploaded_pdf:
            with st.spinner("正在读取 PDF..."):
                try:
                    raw_text = extract_pdf(uploaded_pdf)
                    st.success(f"读取成功！共提取 {len(raw_text)} 个字符。")
                except Exception as e:
                    st.error(f"PDF 读取失败: {e}")

    # URL 输入框
    with tab_url:
        url_input = st.text_input("输入文章链接")
        if url_input:
            with st.spinner("正在抓取网页..."):
                try:
                    raw_text = extract_url(url_input)
                    st.success("抓取成功！")
                except Exception as e:
                    st.error(f"抓取失败: {e}")

    # 预览区域
    if raw_text:
        st.session_state.raw_text_cache = raw_text # 缓存当前文本
        with st.expander("👀 预览提取的内容 (点击展开)", expanded=False):
            st.text(raw_text[:2000] + "...")

    # === 生成按钮 (触发后将结果存入 Session State) ===
    st.markdown("---")
    btn_disabled = not (raw_text and api_key)
    
    if st.button("🚀 开始生成卡片", type="primary", use_container_width=True, disabled=btn_disabled):
        if not api_key:
            st.error("请先在左侧侧边栏填入 API Key！")
        else:
            with st.spinner("🤖 AI 正在大脑风暴中... (通常需要 10-30 秒)"):
                try:
                    json_str = generate_cards(raw_text, api_key, base_url, model_name)
                    json_str = json_str.replace("```json", "").replace("```", "").strip()
                    data = json.loads(json_str)
                    
                    if isinstance(data, dict):
                        for key in ["cards", "flashcards", "items", "list"]:
                            if key in data:
                                data = data[key]
                                break
                    if not isinstance(data, list):
                        data = [data]

                    # 重点：将结果存入 session_state，而不是直接显示
                    st.session_state.generated_df = pd.DataFrame(data)
                    
                except Exception as e:
                    st.error(f"生成出错: {e}")
                    with st.expander("查看 AI 原始返回内容 (用于排查)"):
                        st.code(json_str)

# === 5. 结果显示区域 (独立于按钮之外) ===
# 只要 session_state 里有数据，就会一直显示

with col2:
    st.subheader("📤 第二步：获取结果")
    
    if st.session_state.generated_df is not None:
        df = st.session_state.generated_df
        
        st.success(f"成功生成 {len(df)} 张卡片！")
        
        # 编辑器
        edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")
        
        # 导出 CSV
        csv = edited_df.to_csv(index=False, header=False, sep='\t')
        
        st.download_button(
            label="💾 下载 Anki 导入文件 (.csv)",
            data=csv,
            file_name="anki_cards.csv",
            mime="text/csv",
            type="primary"
        )
        
        st.markdown("""
        **💡 如何导入 Anki?**
        1. 打开电脑版 Anki -> 文件 -> 导入。
        2. 选择下载的 `.csv` 文件。
        3. 字段分隔符选择：**Tab (制表符)**。
        4. 确保 `Allow HTML in fields` (允许在字段中使用 HTML) 已勾选。
        """)
    else:
        if not raw_text:
             st.info("👈 请先在左侧选择并导入您的素材")
        else:
             st.info("👈 素材已就绪，请点击左侧“开始生成”按钮")