import dashscope
from dashscope import Generation
from http import HTTPStatus
import os
import logging
import asyncio

class AliyunClient:
    def __init__(self):
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        dashscope.api_key = self.api_key

    async def get_embedding(self, text: str):
        """将文本转化为向量"""
        def _call():
            return dashscope.TextEmbedding.call(
                model=dashscope.TextEmbedding.Models.text_embedding_v2,
                input=text
            )
        resp = await asyncio.to_thread(_call)
        if resp.status_code == HTTPStatus.OK:
            return resp.output['embeddings'][0]['embedding']
        else:
            logging.error(f"Embedding failed: {resp.code} - {resp.message}")
            return None

    async def call_llm(self, prompt: str, context: str = "", stream: bool = False):
        """调用大语言模型，增强 Prompt 严谨性，支持流式"""
        system_prompt = """你是一个专业且严谨的知识库助手。请根据提供的参考上下文回答用户的问题。
要求：
1. 必须根据参考上下文的内容进行回答，不要编造。
2. 答案中如果引用了上下文内容，请在句末注明来源文档名称，例如：(来源: 员工手册.pdf)。
3. 如果上下文中没有提到相关信息，请直接回答：“抱歉，在知识库中没有找到相关信息。”
4. 回答要条理清晰，使用 Markdown 格式。"""

        full_prompt = f"参考上下文：\n{context}\n\n问题：{prompt}"
        
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': full_prompt}
        ]
        
        if stream:
            # 使用 asyncio.to_thread 将同步生成器包装起来，防止阻塞事件循环
            def _get_responses():
                return Generation.call(
                    model="qwen-plus",
                    messages=messages,
                    result_format='message',
                    stream=True,
                    incremental_output=True
                )
            return await asyncio.to_thread(_get_responses)
        
        def _call():
            return Generation.call(
                model="qwen-plus",
                messages=messages,
                result_format='message',
            )
        
        response = await asyncio.to_thread(_call)
        
        if response.status_code == HTTPStatus.OK:
            return response.output.choices[0].message.content
        else:
            logging.error(f"LLM call failed: {response.code} - {response.message}")
            return "抱歉，大模型调用失败，请稍后再试。"

    async def call_llm_pure(self, prompt: str, history: list = None):
        """纯大模型问答，不依赖知识库"""
        messages = [{'role': 'system', 'content': "你是一个乐于助人的 AI 助手。"}]
        if history:
            messages.extend(history)
        messages.append({'role': 'user', 'content': prompt})
        
        def _call():
            return Generation.call(
                model="qwen-plus",
                messages=messages,
                result_format='message',
            )
        
        response = await asyncio.to_thread(_call)
        
        if response.status_code == HTTPStatus.OK:
            return response.output.choices[0].message.content
        else:
            logging.error(f"Pure LLM call failed: {response.code} - {response.message}")
            return "抱歉，大模型调用失败，请稍后再试。"

    async def rewrite_query(self, question: str, history: list):
        """根据对话历史改写用户问题，使其更适合向量搜索"""
        if not history:
            return question

        history_str = "\n".join([f"{m['role']}: {m['content']}" for m in history])
        prompt = f"""以下是用户与助手的历史对话：
{history_str}

用户当前提问："{question}"

请结合上下文，将当前提问改写为一个独立、完整的搜索词（不需要回答）。
如果问题本身已经很完整，则直接返回原话。

改写后的问题："""

        messages = [{'role': 'user', 'content': prompt}]
        
        def _call():
            return Generation.call(
                model="qwen-plus",
                messages=messages,
                result_format='message',
            )
        
        response = await asyncio.to_thread(_call)
        
        if response.status_code == HTTPStatus.OK:
            return response.output.choices[0].message.content.strip()
        return question

    async def generate_queries(self, question: str, n: int = 3):
        """生成 n 个意思相近的搜索查询，用于增强召回"""
        prompt = f"""你是一个搜索优化助手。请针对以下用户提问，生成 {n} 个语义相近但措辞不同的搜索查询，
以便从知识库中检索到更全面的信息。

用户提问："{question}"

要求：
1. 每行返回一个查询。
2. 不要包含序号、解释或多余的标点。
3. 确保查询涵盖不同的关键词和表达方式。

生成的查询："""

        messages = [{'role': 'user', 'content': prompt}]
        
        def _call():
            return Generation.call(
                model="qwen-plus",
                messages=messages,
                result_format='message',
            )
        
        response = await asyncio.to_thread(_call)
        
        if response.status_code == HTTPStatus.OK:
            queries = response.output.choices[0].message.content.strip().split("\n")
            # 过滤掉空行，并限制数量
            return [q.strip() for q in queries if q.strip()][:n]
        return []

    async def generate_followup_questions(self, question: str, answer: str):
        """根据当前问题和回答，生成 3 个推荐的后续提问"""
        prompt = f"""你是一个智能对话助手。请根据用户的提问和你的回答，推荐 3 个用户可能会感兴趣的后续问题。

用户提问："{question}"
你的回答："{answer}"

要求：
1. 生成 3 个简短、有针对性的后续问题。
2. 每行返回一个问题。
3. 不要包含序号、解释或多余的标点。

推荐的后续问题："""

        messages = [{'role': 'user', 'content': prompt}]
        
        def _call():
            return Generation.call(
                model="qwen-plus",
                messages=messages,
                result_format='message',
            )
        
        response = await asyncio.to_thread(_call)
        
        if response.status_code == HTTPStatus.OK:
            questions = response.output.choices[0].message.content.strip().split("\n")
            return [q.strip() for q in questions if q.strip()][:3]
        return []

    async def ocr_image(self, image_bytes: bytes):
        """使用通义千问-VL多模态模型识别图片内容"""
        import tempfile
        import os
        
        # Qwen-VL 接收文件路径或 URL
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name
        
        try:
            from dashscope import MultiModalConversation
            messages = [
                {
                    'role': 'user',
                    'content': [
                        {'image': f'file://{tmp_path}'},
                        {'text': '请提取并详细描述图片中的所有文字信息，如果是表格请转化为 Markdown 表格。直接输出识别到的内容：'}
                    ]
                }
            ]
            
            def _call():
                return MultiModalConversation.call(
                    model='qwen-vl-plus',
                    messages=messages
                )
            
            response = await asyncio.to_thread(_call)
            
            if response.status_code == HTTPStatus.OK:
                return response.output.choices[0].message.content[0]['text']
            else:
                logging.error(f"OCR failed: {response.code} - {response.message}")
                return ""
        except Exception as e:
            logging.error(f"OCR error: {e}")
            return ""
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    async def rerank(self, query: str, documents: list, top_n: int = 3):
        """调用阿里云 Reranker 模型进行二次精排"""
        if not documents:
            return []
            
        try:
            from dashscope import TextReRank
            
            def _call():
                return TextReRank.call(
                    model="gte-rerank",
                    query=query,
                    documents=documents,
                    top_n=top_n
                )
            
            resp = await asyncio.to_thread(_call)
            
            if resp.status_code == HTTPStatus.OK:
                results = resp.output.results
                # 根据重排后的索引返回文档
                sorted_docs = [documents[item.index] for item in results]
                return sorted_docs
            else:
                logging.error(f"Rerank failed: {resp.code} - {resp.message}")
                return documents[:top_n]
        except Exception as e:
            logging.error(f"Rerank error: {e}")
            return documents[:top_n]

aliyun_client = AliyunClient()
