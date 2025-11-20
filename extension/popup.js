document.addEventListener('DOMContentLoaded', () => {
  // 1. 初始化：加载上次保存的设置
  chrome.storage.local.get(['apiKey', 'baseUrl', 'model', 'deckName', 'noteType'], (result) => {
    if (result.apiKey) document.getElementById('apiKey').value = result.apiKey;
    if (result.baseUrl) document.getElementById('baseUrl').value = result.baseUrl;
    if (result.model) document.getElementById('model').value = result.model;
    
    // 优先使用保存的值，如果没有保存过，就用 HTML 里写的默认值 ("inbox" 和 "问答题")
    if (result.deckName) document.getElementById('deckName').value = result.deckName;
    if (result.noteType) document.getElementById('noteType').value = result.noteType;
  });

  document.getElementById('runBtn').addEventListener('click', async () => {
    const statusDiv = document.getElementById('status');
    const btn = document.getElementById('runBtn');
    
    // 获取界面输入
    const apiKey = document.getElementById('apiKey').value.trim();
    const baseUrl = document.getElementById('baseUrl').value.trim();
    const model = document.getElementById('model').value.trim();
    const deckName = document.getElementById('deckName').value.trim();
    const noteType = document.getElementById('noteType').value.trim();

    // === 关键修复：点击按钮立即保存设置，包括 API Key ===
    chrome.storage.local.set({ apiKey, baseUrl, model, deckName, noteType });

    if (!apiKey) {
      statusDiv.textContent = "❌ 请先输入 API Key";
      return;
    }

    try {
      btn.disabled = true;
      statusDiv.textContent = "🔍 正在读取当前网页...";

      // 1. 抓取网页
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const injectionResults = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => document.body.innerText 
      });
      
      if (!injectionResults || !injectionResults[0]) throw new Error("无法读取页面");
      const pageText = injectionResults[0].result.substring(0, 5000); // 截取前5000字

      // 2. 呼叫 AI
      statusDiv.textContent = "🤖 AI 正在总结与制卡...";
      
      const prompt = `
        你是一个 Anki 制卡专家。请总结以下内容，提取核心知识点。
        输出必须是严格的 JSON 列表。
        
        卡片字段要求：
        - "front": 问题
        - "back": 答案 (支持HTML)
        - "tags": 标签数组
        
        内容: ${pageText}
      `;

      const aiResponse = await fetch(`${baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`
        },
        body: JSON.stringify({
          model: model,
          messages: [{ role: "user", content: prompt }],
          temperature: 0.1,
          response_format: { type: "json_object" }
        })
      });

      if (!aiResponse.ok) throw new Error("AI API 连接失败，请检查 Key");
      
      const aiData = await aiResponse.json();
      let content = aiData.choices[0].message.content;
      // 清洗可能存在的 Markdown 符号
      content = content.replace(/```json/g, "").replace(/```/g, ""); 
      
      let cards = JSON.parse(content);
      if (cards.cards) cards = cards.cards; // 兼容 {"cards": [...]} 格式
      if (!Array.isArray(cards)) cards = [cards];

      // 3. 导入 Anki
      statusDiv.textContent = `📥 正在向 Anki 写入 ${cards.length} 张卡片...`;

      const actions = cards.map(card => ({
        action: "addNote",
        version: 6,
        params: {
          note: {
            deckName: deckName,   // 使用 "inbox"
            modelName: noteType,  // 使用 "问答题"
            fields: {
              "正面": card.front || card.Front, // 对应您的模版字段
              "背面": card.back || card.Back    // 对应您的模版字段
            },
            tags: Array.isArray(card.tags) ? card.tags : (card.tags || "").split(" "),
            options: {
              allowDuplicate: false
            }
          }
        }
      }));

      const ankiResponse = await fetch('http://127.0.0.1:8765', {
        method: 'POST',
        body: JSON.stringify({
          action: "multi",
          version: 6,
          params: { actions: actions }
        })
      });

      const ankiResult = await ankiResponse.json();
      
      if (ankiResult.error) throw new Error("Anki 报错: " + ankiResult.error);
      
      // 检查结果数组中是否有 null (null 代表该条失败)
      const failures = ankiResult.result.filter(r => r === null);
      
      if (failures.length === 0) {
        statusDiv.textContent = `✅ 成功导入 ${cards.length} 张卡片到 [${deckName}]！`;
      } else {
        // 如果全部失败
        if (failures.length === cards.length) {
            throw new Error(`导入失败！请检查 Anki 中是否有"${noteType}"这个模板，且字段名必须完全匹配"正面"和"背面"。`);
        }
        statusDiv.textContent = `⚠️ 部分成功: ${cards.length - failures.length} 条，失败 ${failures.length} 条`;
      }
      
    } catch (err) {
      console.error(err);
      statusDiv.textContent = `❌ 出错: ${err.message}`;
      if (err.message.includes("Failed to fetch")) {
        statusDiv.textContent += " (请确认 Anki 软件已打开)";
      }
    } finally {
      btn.disabled = false;
    }
  });
});