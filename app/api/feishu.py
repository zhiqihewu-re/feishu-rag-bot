from fastapi import APIRouter, Request, BackgroundTasks
import os
import json
import logging
from app.core.feishu_client import feishu_client
from app.services.rag_service import rag_service
from app.services.vector_store import vector_store

from app.core.aliyun_client import aliyun_client
import asyncio
from http import HTTPStatus

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# --- 核心优化：去重缓存与历史记录 ---
from collections import deque
processed_event_ids = deque(maxlen=1000)
user_chat_history = {} # {chat_id: [{"role": "user", "content": "..."}, ...]}

def build_rag_card(question, answer, followup_questions=None):
    """构建 RAG 问答结果卡片，包含交互式拓展问题按钮"""
    elements = [
        {
            "tag": "div",
            "text": {
                "content": f"**问题：**\n{question}",
                "tag": "lark_md"
            }
        },
        {
            "tag": "hr"
        },
        {
            "tag": "div",
            "text": {
                "content": f"{answer}",
                "tag": "lark_md"
            }
        }
    ]

    # 如果有拓展问题，添加交互式按钮
    if followup_questions:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "content": "💡 **你可能还想问：**",
                "tag": "lark_md"
            }
        })
        
        # 将拓展问题包装成按钮，用户点击即可自动发送
        actions = []
        for q in followup_questions:
            actions.append({
                "tag": "button",
                "text": {
                    "content": q,
                    "tag": "plain_text"
                },
                "type": "default",
                "value": {
                    "direct_send_text": q # 自定义标记，方便后续处理
                }
            })
        
        elements.append({
            "tag": "action",
            "actions": actions
        })

    elements.append({
        "tag": "note",
        "elements": [
            {
                "tag": "plain_text",
                "content": "基于上传知识库生成 | 仅供参考"
            }
        ]
    })

    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "template": "blue",
            "title": {
                "content": "🤖 智能助手回答",
                "tag": "plain_text"
            }
        },
        "elements": elements
    }

def build_progress_card(title, steps, current_step_index, template="orange"):
    """构建带进度的状态卡片"""
    elements = []
    for i, step in enumerate(steps):
        status = "✅" if i < current_step_index else ("⏳" if i == current_step_index else "⚪")
        elements.append({
            "tag": "div",
            "text": {
                "content": f"{status} {step}",
                "tag": "lark_md"
            }
        })
    
    return {
        "header": {
            "template": template,
            "title": {
                "content": title,
                "tag": "plain_text"
            }
        },
        "elements": elements
    }

def build_status_card(title, content, template="green"):
    """构建通用状态卡片"""
    return {
        "header": {
            "template": template,
            "title": {
                "content": title,
                "tag": "plain_text"
            }
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "content": content,
                    "tag": "lark_md"
                }
            }
        ]
    }

async def handle_message(chat_id: str, text: str):
    # --- 指令处理逻辑 ---
    cmd = text.strip().lower()
    
    if cmd == "/list":
        files = await vector_store.get_all_filenames()
        if not files:
            content = "目前知识库为空"
        else:
            content = "**📁 已加载的文档列表：**\n\n"
            for i, f in enumerate(files, 1):
                content += f"{i}. {f}\n"
            content += "\n\n发送 `/del 序号` 即可删除对应文档。"
        
        card = build_status_card("知识库清单", content, "blue")
        await feishu_client.send_interactive_card(chat_id, card)
        return

    if cmd.startswith("/del "):
        try:
            index = int(cmd.split(" ")[1]) - 1
            files = await vector_store.get_all_filenames()
            if 0 <= index < len(files):
                filename = files[index]
                await vector_store.delete_document_by_name(filename)
                card = build_status_card("删除成功", f"✅ 已从知识库中移除文档：\n**{filename}**", "green")
            else:
                card = build_status_card("删除失败", "❌ 序号超出范围，请发送 `/list` 确认正确序号。", "red")
        except (ValueError, IndexError):
            card = build_status_card("格式错误", "❌ 请输入正确的格式，例如：`/del 1`", "red")
        
        await feishu_client.send_interactive_card(chat_id, card)
        return

    if cmd == "/clear":
        await vector_store.clear_all()
        user_chat_history[chat_id] = [] # 同时清空当前用户记忆
        card = build_status_card("系统重置", "✅ 知识库已彻底清空，对话记忆已重置。", "red")
        await feishu_client.send_interactive_card(chat_id, card)
        return

    if cmd == "/help":
        help_text = """**🤖 机器人指令说明：**
- `/list`：查看当前知识库中的文档
- `/clear`：清空知识库数据
- `/help`：显示此帮助菜单
- 直接输入：进行知识库问答"""
        card = build_status_card("帮助菜单", help_text, "grey")
        await feishu_client.send_interactive_card(chat_id, card)
        return

    # --- 正常的 RAG 问答逻辑 ---
    # 1. 获取该用户的历史记录
    history = user_chat_history.get(chat_id, [])
    
    # 2. 发送“正在思考”的状态卡片
    loading_card = build_status_card("🤖 智能助手正在思考", f"正在检索知识库并生成回答，请稍候...", "blue")
    resp = await feishu_client.send_interactive_card(chat_id, loading_card)
    msg_id = resp.get("data", {}).get("message_id")

    # 3. 执行 RAG 问答 (流式输出)
    try:
        # 调用 RAG 服务获取流式响应
        gen = await rag_service.answer_question(text, history, stream=True)
        
        full_answer = ""
        last_update_time = asyncio.get_event_loop().time()
        
        # 遍历生成器，实时更新卡片
        for response in gen:
            if response.status_code == HTTPStatus.OK:
                # 获取增量内容并拼接
                chunk = response.output.choices[0].message.content
                full_answer += chunk
                
                # 优化点：减小更新频率到 0.8s，平衡流畅度与频控
                current_time = asyncio.get_event_loop().time()
                if current_time - last_update_time >= 0.8:
                    if msg_id:
                        # 实时更新内容
                        # 优化点：使用异步任务去更新卡片，不阻塞当前的 Token 接收循环
                        asyncio.create_task(feishu_client.update_interactive_card(msg_id, build_rag_card(text, full_answer + " ▌")))
                    last_update_time = current_time
            else:
                logger.error(f"流式生成出错: {response.code} - {response.message}")
        
        # 4. 生成 3 个后续拓展问题 (在回答完成后生成)
        followup_questions = await aliyun_client.generate_followup_questions(text, full_answer)
        
        # 5. 更新历史记录
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": full_answer})
        user_chat_history[chat_id] = history[-6:]
        
        # 6. 更新最终完整卡片 (包含拓展问题)
        final_card = build_rag_card(text, full_answer, followup_questions)
        if msg_id:
            await feishu_client.update_interactive_card(msg_id, final_card)
        else:
            await feishu_client.send_interactive_card(chat_id, final_card)

    except Exception as e:
        logger.error(f"RAG 问答出错: {e}")
        error_card = build_status_card("❌ 问答失败", f"抱歉，处理您的提问时出现了错误：{str(e)}", "red")
        if msg_id:
            await feishu_client.update_interactive_card(msg_id, error_card)
        else:
            await feishu_client.send_interactive_card(chat_id, error_card)

async def handle_file(chat_id: str, message_id: str, file_key: str, filename: str):
    # 先发送一个“处理中”的进度卡片
    steps = ["下载文件", "提取文本", "向量化存储"]
    loading_card = build_progress_card(f"⏳ 正在处理：{filename}", steps, 0)
    resp = await feishu_client.send_interactive_card(chat_id, loading_card)
    msg_id = resp.get("data", {}).get("message_id")

    # 步骤1：下载文件
    content_bytes = await feishu_client.download_file(file_key, message_id)
    if not content_bytes:
        error_card = build_status_card("❌ 处理失败", f"文件《{filename}》下载失败，请重试。", "red")
        if msg_id:
            await feishu_client.update_interactive_card(msg_id, error_card)
        else:
            await feishu_client.send_interactive_card(chat_id, error_card)
        return
    
    # 更新进度到步骤2
    if msg_id:
        await feishu_client.update_interactive_card(msg_id, build_progress_card(f"⏳ 正在处理：{filename}", steps, 1))

    # 步骤2 & 3：提取与存储（目前在 process_document 中统一处理，我们简单模拟进度）
    count = await rag_service.process_document(content_bytes, filename)
    
    # 完成
    success_card = build_status_card("✅ 处理完成", f"文件《{filename}》已处理完成！\n共切分为 **{count}** 个知识块，现在可以开始提问了。", "green")
    if msg_id:
        await feishu_client.update_interactive_card(msg_id, success_card)
    else:
        await feishu_client.send_interactive_card(chat_id, success_card)

async def handle_image(chat_id: str, message_id: str, image_key: str):
    # 1. 发送处理中状态进度卡片
    steps = ["下载图片", "多模态识别", "存入知识库"]
    loading_card = build_progress_card("👁️ 正在识别图片", steps, 0)
    resp = await feishu_client.send_interactive_card(chat_id, loading_card)
    msg_id = resp.get("data", {}).get("message_id")

    # 2. 下载图片
    image_bytes = await feishu_client.download_file(image_key, message_id, type="image")
    if not image_bytes:
        error_card = build_status_card("❌ 识别失败", "图片下载失败", "red")
        if msg_id:
            await feishu_client.update_interactive_card(msg_id, error_card)
        return

    # 更新进度到步骤2
    if msg_id:
        await feishu_client.update_interactive_card(msg_id, build_progress_card("👁️ 正在识别图片", steps, 1))

    # 3. 调用多模态模型进行 OCR
    text_content = await aliyun_client.ocr_image(image_bytes)
    if not text_content:
        error_card = build_status_card("❌ 识别失败", "无法从图片中提取文字", "red")
        if msg_id:
            await feishu_client.update_interactive_card(msg_id, error_card)
        return

    # 更新进度到步骤3
    if msg_id:
        await feishu_client.update_interactive_card(msg_id, build_progress_card("👁️ 正在识别图片", steps, 2))

    # 4. 将提取出的文字存入向量库
    filename = f"image_{message_id[:8]}.txt"
    count = await rag_service.process_document(text_content.encode('utf-8'), filename)

    # 5. 回复识别结果
    success_card = build_status_card("✅ 图片识别成功", f"识别到以下内容并已存入知识库：\n\n{text_content[:200]}...", "green")
    if msg_id:
        await feishu_client.update_interactive_card(msg_id, success_card)
    else:
        await feishu_client.send_interactive_card(chat_id, success_card)

@router.post("/webhook")
async def feishu_webhook(request: Request, background_tasks: BackgroundTasks):
    # 打印收到的原始数据，方便排查
    raw_body = await request.body()
    logger.info(f"收到飞书请求: {raw_body.decode()}")
    
    try:
        data = json.loads(raw_body)
    except Exception as e:
        logger.error(f"解析 JSON 失败: {e}")
        return {"code": 1, "msg": "invalid json"}
    
    # 1. 处理 URL 校验 (必须直接返回 challenge)
    if data.get("type") == "url_verification":
        challenge = data.get("challenge")
        logger.info(f"正在进行 URL 校验，返回 challenge: {challenge}")
        return {"challenge": challenge}
    
    # 2. 如果数据被加密了 (如果你在飞书后台设置了 Encrypt Key)
    if "encrypt" in data:
        logger.error("检测到加密消息！请在飞书后台『事件订阅 -> 加密策略』中关闭消息加密，或者删除 Encrypt Key")
        return {"code": 1, "msg": "encryption not supported yet"}

    # 3. 处理正常事件
    if "header" in data:
        # --- 核心优化：去重逻辑 ---
        event_id = data["header"].get("event_id")
        if event_id in processed_event_ids:
            logger.info(f"跳过重复请求: {event_id}")
            return {"code": 0, "msg": "ok"}
        
        processed_event_ids.append(event_id)

        event_type = data["header"].get("event_type")
        
        # 处理卡片按钮交互事件
        if event_type == "card.action.trigger":
            action = data.get("action", {})
            value = action.get("value", {})
            chat_id = data.get("context", {}).get("open_chat_id")
            
            # 如果是拓展问题按钮点击
            if "direct_send_text" in value and chat_id:
                text = value["direct_send_text"]
                # 模拟用户发送消息，进入问答逻辑
                background_tasks.add_task(handle_message, chat_id, text)
                return {"code": 0, "msg": "ok"}

        if event_type == "im.message.receive_v1":
            message = data["event"]["message"]
            chat_id = message.get("chat_id")
            message_id = message.get("message_id")

            if not chat_id:
                logger.error("消息中缺少 chat_id")
                return {"code": 1, "msg": "missing chat_id"}

            if message["message_type"] == "text":
                content = json.loads(message["content"])
                text = content.get("text")
                background_tasks.add_task(handle_message, chat_id, text)
            elif message["message_type"] == "file":
                content = json.loads(message["content"])
                file_key = content.get("file_key")
                filename = content.get("file_name", "unknown_file")
                background_tasks.add_task(handle_file, chat_id, message_id, file_key, filename)
            
            # 处理图片消息
            elif message["message_type"] == "image":
                content = json.loads(message["content"])
                image_key = content.get("image_key")
                background_tasks.add_task(handle_image, chat_id, message_id, image_key)
                
    return {"code": 0, "msg": "ok"}
