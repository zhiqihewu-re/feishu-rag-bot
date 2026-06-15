import httpx
import os
import json
import logging

class FeishuClient:
    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID")
        self.app_secret = os.getenv("FEISHU_APP_SECRET")
        self.tenant_access_token = None

    async def _get_tenant_access_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                self.tenant_access_token = response.json().get("tenant_access_token")
            else:
                logging.error(f"Failed to get tenant_access_token: {response.text}")

    async def send_text_message(self, receive_id, content, receive_id_type="chat_id"):
        if not self.tenant_access_token:
            await self._get_tenant_access_token()

        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": content})
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logging.error(f"Failed to send message: {response.text}")
            return response.json()

    async def download_file(self, file_key, message_id, type="file"):
        """从飞书下载文件或图片"""
        if not self.tenant_access_token:
            await self._get_tenant_access_token()

        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}?type={type}"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                return response.content
            else:
                logging.error(f"Failed to download file: {response.text}")
                return None

    async def send_interactive_card(self, receive_id, card_content, receive_id_type="chat_id"):
        """发送飞书消息卡片"""
        if not self.tenant_access_token:
            await self._get_tenant_access_token()

        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card_content)
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logging.error(f"Failed to send card: {response.text}")
            return response.json()

    async def update_interactive_card(self, message_id, card_content):
        """更新已发送的飞书消息卡片"""
        if not self.tenant_access_token:
            await self._get_tenant_access_token()

        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        payload = {
            "msg_type": "interactive",
            "content": json.dumps(card_content)
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.patch(url, headers=headers, json=payload)
            if response.status_code != 200:
                logging.error(f"Failed to update card: {response.text}")
            return response.json()

feishu_client = FeishuClient()
