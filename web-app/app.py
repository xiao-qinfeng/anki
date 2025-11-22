import streamlit as st
import json
import genanki
import random
import re
import time
import os
import requests
import concurrent.futures
import trafilatura
from datetime import datetime
from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi
from pypdf import PdfReader
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

# === UI 配置 ===
st.set_page_config(page_title="KnowledgeMiner Pro", layout="wide")
DATA_DIR = "data"
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)

# === 0. 状态管理 ===
if 'global_cards' not in st.session_state: st.session_state.global_cards = []
if 'analysis_result' not in st.session_state: st.session_state.analysis_result = ""
if 'uploader_key' not in st.session_state: st.session_state.uploader_key = 0
if 'source_name' not in st.session_state: st.session_state.source_name = "未命名笔记"

# === 1. 提取层 ===
def extract_url(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded: raise ValueError("连接失败")
        text = trafilatura.extract(downloaded)
        if not text: raise ValueError("无正文")
        return text
    except Exception as e: raise ValueError(f"解析失败: {e}")

def extract_youtube(url, proxy=None):
    pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(pattern, url)
    if not match: raise ValueError("无效链接")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        transcript = YouTubeTranscriptApi.get_transcript(match.group(1), languages=['zh-Hans','en'], proxies=proxies)
        return " ".join([t['text'] for t in transcript])
    except Exception as e:
        raise ValueError(f"YouTube 抓取失败: {e}")

def extract_audio(file_obj, api_key, base_url):
    client = OpenAI(api_key=api_key, base_url=base_url)
    return client.audio.transcriptions.create(model="whisper-1", file=file_obj, response_format="text")

def extract_file(file):
    text = ""
    try:
        if file.name.endswith(".pdf"):
            reader = PdfReader(file)
            for page in reader.pages: text += page.extract_text() + "\n"
        elif file.name.endswith(".epub"):
            book = epub.read_epub(file)
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    text += soup.get_text() + "\n"
        elif file.name.endswith((".txt", ".md")):
            text = file.read().decode("utf-8")
    except Exception as e: raise ValueError(f"解析错误: {e}")
    return text

# === 2. AI 核心层 (V8.3 升级：自动重试与限流) ===
PROMPTS = {
    "💡 知识卡片提取": {
        "type": "json",
        "system": "生成可直接导入Anki的知识卡片。每张卡片测试一个知识点，正面提问，背面解答。\n\n输出JSON数组，每项包含：\n- Front: 简洁问题，触发主动回忆\n- Back: 详细答案，包含关键信息\n- Tags: 分类标签数组\n\n卡片类型：概念定义、原理机制、对比区分、应用场景、原因解释。\n示例：\n{\"Front\": \"过拟合是什么？\", \"Back\": \"模型在训练集表现好但测试集差的现象\", \"Tags\": [\"机器学习\", \"基础概念\"]}"
    },
    "🧠 填空记忆 (Cloze)": {"type": "json", "system": "转化为 Anki 挖空题。输出 JSON: Front (含 {{c1::}}), Back, Tags"},
    "✍️ 写作风格拆解": {
        "type": "text",
        "system": "分析爆款作品的成功要素：结构、心理机制、亮点技巧。Markdown输出可复用经验。"
    },
    "🎬 短视频文案":{
        "type": "text",
        "system": """你是极简洞察型短视频创作者，专注AI实用内容。语言直接有力，短句为主。

核心要求：
1. 1秒抓住注意力，开头必须反直觉
2. 语言极简，不用转场词，逻辑一条线
3. 结构：洞察+操作组合
4. 适配视频号/小红书的共鸣+解决方案模式

自动执行：
- 自动判断用洞察型还是教程型
- 自动压缩成最短表达
- 输出5个备选标题
- 输出3条字幕金句

输出格式：
【开头抓钩】
反直觉强力开场

【核心观点】
2-3句直说，不铺垫

【具体方法】
1-2个关键步骤

【收尾句】
让人想收藏的关注语

# 备选标题（5个）

# 字幕金句（3条）"""
    },
    "🌳 思维导图": {
        "type": "text", 
        "system": "使用Mermaid mindmap语法创建思维导图。要求：中心主题用(( ))，主要分支带emoji，子节点用▪️。层次清晰，关键词简洁。直接输出代码。"
    }
}

def call_ai_single(text_chunk, api_key, base_url, model, cfg):
    """包含动态重试机制的 AI 调用函数"""
    client = OpenAI(api_key=api_key, base_url=base_url)
    max_retries = 5  # 最大重试次数
    base_wait_time = 5  # 初始等待时间（秒）

    for attempt in range(max_retries):
        try:
            params = {
                "model": model,
                "messages": [{"role": "system", "content": cfg["system"]}, {"role": "user", "content": text_chunk}],
                "temperature": 0.3
            }
            if cfg["type"] == "json":
                params["response_format"] = {"type": "json_object"}

            resp = client.chat.completions.create(**params)
            content = resp.choices[0].message.content

            if cfg["type"] == "json":
                content_clean = content.replace("```json", "").replace("```", "").strip()
                try:
                    data = json.loads(content_clean)
                except json.JSONDecodeError as e:
                    return [{
                        "Front": "⚠️ JSON 解析失败",
                        "Back": f"AI 返回格式错误: {str(e)} | 原始内容: {content_clean[:200]}",
                        "Tags": ["Error"]
                    }]

                if isinstance(data, dict):
                    for k in ["cards", "items", "flashcards"]:
                        if k in data:
                            return data[k]
                return data if isinstance(data, list) else []
            return content

        except Exception as e:
            error_msg = str(e)
            # 如果是 429 (速率限制)，动态调整等待时间
            if "429" in error_msg or "Rate limit" in error_msg:
                wait_time = base_wait_time * (attempt + 1)  # 动态调整等待时间
                print(f"Rate limit hit. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue  # 进入下一次循环重试

            # 其他错误直接报错
            if cfg["type"] == "json":
                return [{
                    "Front": "❌ API 调用出错",
                    "Back": error_msg,
                    "Tags": ["Error"]
                }]
            return f"API Error: {error_msg}"

    # 重试耗尽
    return [{
        "Front": "❌ 超时失败",
        "Back": "重试5次仍被限流，请降低并发数或增加延迟",
        "Tags": ["Error"]
    }] if cfg["type"] == "json" else "重试耗尽"

def process_concurrency(text, api_key, base_url, model, cfg, max_workers, delay):
    """并发控制器，防止 WebSocket 超时"""
    if cfg["type"] == "text":
        return call_ai_single(text[:15000], api_key, base_url, model, cfg)
    
    chunk_size = 5000
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    all_results = []
    
    status_bar = st.progress(0)
    status_text = st.empty()
    completed = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交任务时增加间隔，避免瞬间并发过高
        futures = []
        for chunk in chunks:
            futures.append(executor.submit(call_ai_single, chunk, api_key, base_url, model, cfg))
            time.sleep(delay)  # === 关键：提交任务的间隔 ===
            
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if isinstance(res, list): all_results.extend(res)
            completed += 1
            # 定期更新进度条，防止 WebSocket 超时
            status_bar.progress(completed / len(chunks))
            status_text.text(f"已完成: {completed}/{len(chunks)}")
            time.sleep(0.1)  # 确保界面有时间刷新
            
    time.sleep(0.5)
    status_bar.empty()
    status_text.empty()
    return all_results

# === 3. 导出与同步 ===
def create_pkg(cards, name):
    if not cards: return None
    deck = genanki.Deck(random.randrange(1<<30, 1<<31), name)
    model = genanki.Model(random.randrange(1<<30, 1<<31), 'KM', fields=[{'name':'Q'},{'name':'A'}], 
                          templates=[{'name':'C1', 'qfmt':'{{Q}}', 'afmt':'{{FrontSide}}<hr>{{A}}'}])
    for c in cards:
        tags = c.get('Tags', [])
        deck.add_note(genanki.Note(model=model, fields=[c.get('Front',''), c.get('Back','')], tags=tags if isinstance(tags, list) else str(tags).split()))
    path = os.path.join(DATA_DIR, f"{name}.apkg")
    genanki.Package(deck).write_to_file(path)
    return path

def push_to_anki(cards, deck_name, note_type, field_front, field_back):
    url = "http://127.0.0.1:8765"
    actions = []
    for card in cards:
        if "Error" in card.get("Tags", []): continue
        actions.append({
            "action": "addNote", "version": 6,
            "params": {
                "note": {
                    "deckName": deck_name, 
                    "modelName": note_type,
                    "fields": {field_front: card.get("Front"), field_back: card.get("Back")},
                    "tags": card.get("Tags", []) if isinstance(card.get("Tags"), list) else str(card.get("Tags")).split(),
                    "options": {"allowDuplicate": False}
                }
            }
        })
    try:
        res = requests.post(url, json={"action": "multi", "version": 6, "params": {"actions": actions}})
        result = res.json()
        if result.get("error"): return False, result["error"]
        return True, len([x for x in result["result"] if x])
    except Exception as e: return False, str(e)

# === 4. 界面 ===
with st.sidebar:
    st.header("KnowledgeMiner V8.3")
    
    # API 设置
    with st.expander("🔌 API 设置", expanded=True):
        api_key = st.text_input("API Key", value=st.secrets.get("DEFAULT_API_KEY", ""), type="password")
        base_url = st.text_input("Base URL", value=st.secrets.get("DEFAULT_BASE_URL", "https://api.siliconflow.cn/v1"))
        model_name = st.text_input("Model", value=st.secrets.get("DEFAULT_MODEL", "deepseek-ai/DeepSeek-V2.5"))
    
    # 新增：速率限制设置
    with st.expander("⚡️ 速率限制 (解决429报错)", expanded=True):
        st.caption("如果你使用免费 Key 遇到 429 错误，请调低并发，调高延迟。")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            max_workers = st.number_input("并发线程", min_value=1, max_value=5, value=2, help="同时处理几个片段")
        with col_s2:
            request_delay = st.number_input("请求间隔(秒)", min_value=0.0, value=1.0, step=0.5, help="每个请求发出后的等待时间")

    with st.expander("📡 Anki 直连"):
        anki_note_type = st.text_input("模板名称", value="问答题")
        anki_field_front = st.text_input("正面字段", value="正面")
        anki_field_back = st.text_input("背面字段", value="背面")

    with st.expander("🌐 代理设置"):
        proxy = st.text_input("HTTP Proxy", placeholder="http://127.0.0.1:7890")

    mode = st.selectbox("模式", list(PROMPTS.keys()))
    if st.button("🗑️ 重置"):
        for key in list(st.session_state.keys()):
            if key != 'uploader_key': del st.session_state[key]
        st.session_state.uploader_key += 1
        st.rerun()

st.title("KnowledgeMiner")

tab1, tab2, tab3, tab4 = st.tabs(["📝 文本", "🔗 链接", "📄 文档", "🎙️ 音频"])
curr_text = ""

with tab1:
    txt_in = st.text_area("粘贴", height=150, key="txt_area") 
    if txt_in: 
        curr_text = txt_in
        if st.session_state.source_name == "未命名笔记": st.session_state.source_name = "剪贴板内容"
with tab2:
    url_in = st.text_input("URL", key="url_in")
    if url_in and st.button("解析"):
        try:
            curr_text = extract_youtube(url_in, proxy) if "youtu" in url_in else extract_url(url_in)
            st.session_state.cached_text = curr_text
            st.session_state.source_name = "Web_" + url_in.split("/")[-1][:20]
            st.success("解析成功")
        except Exception as e: st.error(str(e))
with tab3:
    file = st.file_uploader("文件", type=["pdf","epub","txt","md"], key=f"file_{st.session_state.uploader_key}")
    if file:
        try:
            curr_text = extract_file(file)
            st.session_state.cached_text = curr_text
            st.session_state.source_name = file.name.rsplit('.', 1)[0]
        except Exception as e: st.error(str(e))
with tab4:
    audio = st.file_uploader("音频", type=["mp3","m4a"], key=f"audio_{st.session_state.uploader_key}")
    w_key = st.text_input("Whisper Key", type="password")
    if audio and st.button("转录"):
        try:
            curr_text = extract_audio(audio, w_key, "https://api.groq.com/openai/v1")
            st.session_state.cached_text = curr_text
            st.session_state.source_name = audio.name.rsplit('.', 1)[0]
        except Exception as e: st.error(str(e))

if 'cached_text' in st.session_state and not curr_text: curr_text = st.session_state.cached_text

if curr_text:
    st.info(f"就绪 {len(curr_text)} 字 | 来源: {st.session_state.source_name}")
    
    if st.button("🚀 开始处理", type="primary"):
        if not api_key: st.error("请先在侧边栏填入 API Key")
        else:
            with st.spinner(f"AI 处理中 (并发:{max_workers}, 延迟:{request_delay}s)..."):
                cfg = PROMPTS[mode]
                # 传入用户设置的速率参数
                res = process_concurrency(curr_text, api_key, base_url, model_name, cfg, max_workers, request_delay)
                
                if cfg["type"] == "json":
                    if isinstance(res, list):
                        st.session_state.global_cards = res
                        st.session_state.analysis_result = ""
                        st.success(f"✅ 生成 {len(res)} 张卡片")
                    else: st.error(f"失败: {res}")
                else:
                    st.session_state.analysis_result = res
                    st.session_state.global_cards = []
                    st.success("✅ 分析完成")

st.divider()

if st.session_state.analysis_result:
    st.subheader("📝 结果")
    st.code(st.session_state.analysis_result, language="markdown")
    path = os.path.join(DATA_DIR, f"{st.session_state.source_name}_笔记.md")
    with open(path, "w", encoding="utf-8") as f: f.write(st.session_state.analysis_result)
    with open(path, "rb") as f: st.download_button("📥 下载 MD", f, file_name=os.path.basename(path))

elif st.session_state.global_cards:
    st.subheader(f"📦 卡片 ({len(st.session_state.global_cards)})")
    
    error_cards = [c for c in st.session_state.global_cards if "Error" in c.get("Tags", [])]
    if error_cards:
        st.warning(f"⚠️ 部分片段重试后仍失败 ({len(error_cards)}个)，详情见下方红色卡片")
        for err in error_cards:
            st.markdown(f"❌ {err.get('Back')}")

    st.json(st.session_state.global_cards[:2])
    
    today_str = datetime.now().strftime("%Y%m%d")
    default_deck_name = re.sub(r'[\\/*?:"<>|]', "", f"{today_str}_{st.session_state.source_name}")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        final_deck_name = st.text_input("牌组名称", value=default_deck_name)
        pkg_path = create_pkg(st.session_state.global_cards, final_deck_name)
        if pkg_path:
            with open(pkg_path, "rb") as f:
                st.download_button("📥 下载 .apkg", f, file_name=os.path.basename(pkg_path), use_container_width=True)
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("📡 直推 Anki", use_container_width=True):
            success, msg = push_to_anki(st.session_state.global_cards, final_deck_name, anki_note_type, anki_field_front, anki_field_back)
            if success: st.success(f"✅ 已推送 {msg} 张")
            else: st.error(f"❌ 失败: {msg}")