# ⛏️ KnowledgeMiner (知识矿工)

KnowledgeMiner 是一个利用 AI (大语言模型) 自动生成 Anki 记忆卡片的工具集。
它包含两个部分：一个用于批量处理大文件的 **Web 应用**，和一个用于碎片化学习的 **浏览器插件**。

## 📦 项目结构

```text
knowledge-miner/
├── web-app/           # Python Streamlit 应用 (处理 PDF/对话记录/长文)
└── extension/         # Chrome/Edge 浏览器插件 (一键导入当前网页)

## 🔑 准备工作
在开始之前，你需要：
一个 AI API Key (推荐 DeepSeek, 便宜且强大)。
Anki 电脑版 (用于存储和同步卡片)。
## 🛠️ 模块一：Web 应用 (批量处理)
适合场景：导入 PDF 电子书、导入 AI 对话记录、长文章深度分析。
1. 安装依赖
进入 web-app 目录：
code
Bash
cd web-app
python3 -m venv .venv
source .venv/bin/activate   # Windows 使用 .venv\Scripts\activate
pip install -r requirements.txt
2. 运行应用
code
Bash
python -m streamlit run app.py
浏览器会自动打开 http://localhost:8501。
3. 使用说明
AI 对话模式：复制 ChatGPT/Claude 的对话全文，粘贴进去，系统会自动去除客套话，提取核心问答。
PDF 模式：上传 PDF，自动提取文字并制卡。
导出：生成的结果可下载为 .csv，在 Anki 中选择 文件 -> 导入 (分隔符选 Tab) 即可。

🧩 模块二：浏览器插件 (一键导入)
适合场景：浏览技术博客、新闻、文档时，想快速把当前页面变成卡片。
1. Anki 配置 (关键步骤)
为了让浏览器能直接把卡片推送到 Anki，你需要安装 AnkiConnect 插件。
打开 Anki -> 工具 -> 附加组件 -> 获取附加组件 -> 代码填 2055492159。
安装后重启 Anki。
配置 AnkiConnect：
在附加组件列表中选中 AnkiConnect -> 点击 配置。
确保 "webBindAddress": "127.0.0.1"。
2. 安装插件到浏览器
打开 Chrome 或 Edge，地址栏输入 chrome://extensions。
开启右上角的 开发者模式 (Developer mode)。
点击 加载已解压的扩展程序 (Load unpacked)。
选择本项目中的 extension 文件夹。
## 3. 使用说明
确保 Anki 软件是打开状态。
在任意网页点击浏览器右上角的 ⛏️ 图标。
填入 API Key。
点击 "生成并导入 Anki"，等待约 20 秒，卡片即会自动出现在 Anki 默认牌组中。
📝 注意事项
API 费用：本项目需要你提供自己的 API Key，费用由模型提供商收取 (DeepSeek 极低)。
网络问题：如果遇到安装依赖超时，请尝试切换 pip 源；如果 AnkiConnect 连接失败，请检查防火墙是否阻挡了 8765 端口。