# 飞书智能知识库助手 (Feishu RAG Bot)

这是一个基于 **RAG (Retrieval-Augmented Generation)** 架构的飞书智能问答机器人 Demo。它集成了阿里云通义千问大模型和 ChromaDB 本地向量库，支持文档解析、流式回答、图片识别以及交互式追问。

## 🌟 核心特性

- **流式输出 (Streaming)**：采用打字机效果实时展现回答内容，极速响应。
- **单轨 RAG 问答**：精准召回本地知识库内容，并注明引用来源。
- **智能追问**：回答结束后自动生成 3 个相关拓展问题，支持点击按钮直接提问。
- **多模态支持**：支持 PDF、Docx、TXT 格式文档上传，以及图片 OCR 识别存入知识库。
- **实时进度卡片**：文件处理与图片识别过程全程进度条化展示，拒绝盲等。
- **高性能异步**：全链路采用异步 IO 优化，支持高并发处理。

## 🛠️ 技术栈

- **后端框架**: [FastAPI](https://fastapi.tiangolo.com/)
- **大模型能力**: [阿里云 DashScope (通义千问)](https://help.aliyun.com/zh/dashscope/)
- **向量数据库**: [ChromaDB](https://www.trychroma.com/)
- **文档处理**: [LangChain](https://python.langchain.com/), [pypdf](https://pypi.org/project/pypdf/), [python-docx](https://python-docx.readthedocs.io/)
- **平台接入**: [飞书开放平台卡片消息](https://open.feishu.cn/document/ukTMukTMukTM/uEzM5QjLxMTO04SMzETN)

## 🚀 快速开始

### 1. 环境准备
确保您的环境中已安装 Python 3.9+。

### 2. 克隆项目
```bash
git clone https://github.com/your-username/feishu-rag-bot.git
cd feishu-rag-bot
```

### 3. 安装依赖
```bash
pip install -r requirements.txt
```

### 4. 配置环境变量
在项目根目录创建 `.env` 文件，并填入以下配置：
```env
# 飞书应用配置
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret

# 阿里云配置
DASHSCOPE_API_KEY=your_dashscope_api_key
```

### 5. 启动服务
```bash
python -m app.main
```
默认服务将运行在 `http://localhost:8000`。您可以使用 `ngrok` 或 `frp` 将其暴露到公网，并在飞书后台配置 Webhook 地址：`https://your-domain/feishu/webhook`。

## 📁 目录结构

```text
.
├── app/
│   ├── api/             # 接口层 (飞书 Webhook 处理)
│   ├── core/            # 核心能力 (飞书/阿里云客户端)
│   ├── services/         # 业务层 (RAG 调度/向量存储)
│   └── main.py          # 入口文件
├── data/                # 本地向量库持久化目录
├── Dockerfile           # 容器化部署
└── requirements.txt     # 项目依赖
```

## 📝 进阶优化建议

- [ ] **混合检索**: 引入 BM25 关键词检索，提升对专有名词的召回率。
- [ ] **长记忆支持**: 引入 Redis 存储会话上下文，实现跨消息的长轮对话理解。
- [ ] **分布式存储**: 当文档量级较大时，建议迁移至 Milvus 或 Qdrant。
- [ ] **多模态增强**: 增加对 PDF 表格和图片的深度解析能力。

## 📄 开源协议
MIT License
