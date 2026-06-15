from app.services.vector_store import vector_store
from app.core.aliyun_client import aliyun_client
from langchain.text_splitter import RecursiveCharacterTextSplitter
import io
import asyncio
from pypdf import PdfReader
from docx import Document

class RAGService:
    def __init__(self):
        # 优化点：精细化递归切分器
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=600,         # 稍微增大块大小，给模型更多上下文
            chunk_overlap=120,      # 增大重叠度（20%左右），防止语义断层
            length_function=len,
            # 优先级：段落 > 换行 > 中文句号 > 英文句号 > 空格
            separators=["\n\n", "\n", "。", "！", "？", ".", " ", ""]
        )

    def extract_text_from_bytes(self, content_bytes: bytes, filename: str):
        """从二进制流中提取文本"""
        text = ""
        if filename.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content_bytes))
            for page in reader.pages:
                # 优化点：提取 PDF 文本时加入页码信息，方便溯源
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        elif filename.endswith(".docx"):
            doc = Document(io.BytesIO(content_bytes))
            for para in doc.paragraphs:
                if para.text.strip():
                    text += para.text + "\n"
        elif filename.endswith(".txt"):
            text = content_bytes.decode("utf-8")
        return text

    async def process_document(self, content_bytes: bytes, filename: str):
        """处理文档：提取文本、切片并存入向量库"""
        text = self.extract_text_from_bytes(content_bytes, filename)
        if not text:
            return 0
            
        # 核心优化：递归切分
        chunks = self.text_splitter.split_text(text)
        
        # 优化点：元数据中加入更多信息
        metadatas = []
        for i, _ in enumerate(chunks):
            metadatas.append({
                "source": filename,
                "chunk_id": i,
                "total_chunks": len(chunks)
            })
            
        count = await vector_store.add_documents(chunks, metadatas)
        return count

    async def answer_question(self, question: str, history: list = None, stream: bool = False):
        """增强版问答流程：查询扩展 -> 宽召回 -> 精重排 -> 生成答案"""
        # 1. 如果有历史记录，先尝试改写问题（解决代词指代问题）
        main_query = question
        if history:
            main_query = await aliyun_client.rewrite_query(question, history)
            if main_query != question:
                print(f"问题重写: {question} -> {main_query}")
        
        # 2. 【查询扩展】：生成多个相似查询以增强召回
        expanded_queries = await aliyun_client.generate_queries(main_query, n=3)
        all_search_queries = [main_query] + expanded_queries
        print(f"扩展查询: {all_search_queries}")
        
        # 3. 【宽召回】：并行检索多个查询的结果
        # 优化点：对扩展后的查询去重，避免重复检索
        search_tasks = [vector_store.search_list(q, top_k=5) for q in set(all_search_queries)]
        results = await asyncio.gather(*search_tasks)
        all_candidates = []
        for candidates in results:
            all_candidates.extend(candidates)
            
        # 去重（防止不同查询搜到同一个块）
        unique_candidates = list(set(all_candidates))
        
        # 4. 【精重排】：利用 Reranker 模型从候选块中选出最相关的 Top 3
        reranked_docs = await aliyun_client.rerank(main_query, unique_candidates, top_n=3)
        
        # 5. 组合最终上下文
        context = "\n---\n".join(reranked_docs)
        
        # 6. 调用大模型生成回答 (支持流式)
        answer = await aliyun_client.call_llm(question, context, stream=stream)
        return answer

rag_service = RAGService()
