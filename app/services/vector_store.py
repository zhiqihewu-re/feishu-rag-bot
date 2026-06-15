import chromadb
from chromadb.config import Settings
import os
import asyncio
from app.core.aliyun_client import aliyun_client

class VectorStoreService:
    def __init__(self):
        # 确保数据持久化目录存在
        self.persist_directory = os.path.join(os.getcwd(), "data", "chroma")
        if not os.path.exists(self.persist_directory):
            os.makedirs(self.persist_directory)
            
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        self.collection = self.client.get_or_create_collection(name="kb_documents")

    async def add_documents(self, texts: list, metadatas: list = None):
        """将文本列表添加到向量库"""
        ids = [f"doc_{i}_{os.urandom(4).hex()}" for i in range(len(texts))]
        
        # 优化点：并发获取 Embedding，显著提升入库速度
        embedding_tasks = [aliyun_client.get_embedding(text) for text in texts]
        embeddings = await asyncio.gather(*embedding_tasks)
            
        # 过滤掉 embedding 失败的情况
        valid_indices = [i for i, emb in enumerate(embeddings) if emb is not None]
        
        if valid_indices:
            # ChromaDB 的 add 操作涉及磁盘 IO，建议放在线程池
            def _add():
                self.collection.add(
                    embeddings=[embeddings[i] for i in valid_indices],
                    documents=[texts[i] for i in valid_indices],
                    metadatas=[metadatas[i] for i in valid_indices] if metadatas else None,
                    ids=[ids[i] for i in valid_indices]
                )
            await asyncio.to_thread(_add)
        return len(valid_indices)

    async def search(self, query: str, top_k: int = 5):
        """根据查询搜索最相关的文本块，并返回带来源的上下文"""
        query_embedding = await aliyun_client.get_embedding(query)
        if not query_embedding:
            return ""
            
        def _query():
            return self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
        results = await asyncio.to_thread(_query)
        
        # 组合结果，包含内容和来源
        formatted_results = []
        documents = results['documents'][0]
        metadatas = results['metadatas'][0]
        
        for doc, meta in zip(documents, metadatas):
            source = meta.get("source", "未知来源")
            formatted_results.append(f"内容: {doc}\n(来源: {source})")
            
        return "\n---\n".join(formatted_results)

    async def search_list(self, query: str, top_k: int = 10):
        """返回搜索到的原始文档列表，用于重排"""
        query_embedding = await aliyun_client.get_embedding(query)
        if not query_embedding:
            return []
            
        def _query():
            return self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
        results = await asyncio.to_thread(_query)
        
        # 组合内容和来源元数据
        documents = results['documents'][0]
        metadatas = results['metadatas'][0]
        
        formatted_list = []
        for doc, meta in zip(documents, metadatas):
            source = meta.get("source", "未知来源")
            formatted_list.append(f"内容: {doc}\n(来源: {source})")
            
        return formatted_list

    async def get_all_filenames(self):
        """获取向量库中所有已上传的文件名"""
        results = await asyncio.to_thread(self.collection.get, include=['metadatas'])
        if not results['metadatas']:
            return []
        # 使用 set 去重
        filenames = {meta.get("source") for meta in results['metadatas'] if meta}
        return list(filenames)

    async def clear_all(self):
        """清空向量库所有数据"""
        def _clear():
            self.client.delete_collection(name="kb_documents")
            self.collection = self.client.get_or_create_collection(name="kb_documents")
        await asyncio.to_thread(_clear)

    async def delete_document_by_name(self, filename: str):
        """根据文件名删除指定文档的所有向量"""
        await asyncio.to_thread(self.collection.delete, where={"source": filename})
        return True

vector_store = VectorStoreService()
