import base64
import random
import time
from typing import Dict, List, Optional, Any
import requests
from common.Logger import logger
from common.config import Config

class GitHubClient:
    GITHUB_API_URL = "https://api.github.com/search/code"
    
    # 核心：类级别的静态变量，实现多实例间的状态共享
    _GLOBAL_COOLDOWN_UNTIL = 0  
    _CONSECUTIVE_403_COUNT = 0

    def __init__(self, tokens: List[str]):
        self.tokens = list(set([tk.strip() for tk in tokens if tk.strip()]))
        self._token_ptr = 0
        if not self.tokens:
            logger.error("❌ No valid GitHub tokens found!")

    def _next_token(self) -> Optional[str]:
        if not self.tokens: return None
        token = self.tokens[self._token_ptr % len(self.tokens)]
        self._token_ptr += 1
        return token

    def _wait_if_cooldown(self):
        """检查并执行全局冷却等待"""
        now = time.time()
        if now < GitHubClient._GLOBAL_COOLDOWN_UNTIL:
            wait_time = GitHubClient._GLOBAL_COOLDOWN_UNTIL - now
            logger.warning(f"🛌 全局限流冷却中... 需等待 {wait_time:.1f}s (当前Token池: {len(self.tokens)}个)")
            time.sleep(wait_time)

    def search_for_keys(self, query: str, max_retries: int = 5) -> Dict[str, Any]:
        all_items = []
        total_count = 0
        expected_total = None
        
        for page in range(1, 11):
            self._wait_if_cooldown() # 每次请求页码前检查冷却
            
            page_success = False
            for attempt in range(1, max_retries + 1):
                current_token = self._next_token()
                headers = {
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) HajimiPAT/{random.randint(1,99)}"
                }
                if current_token: headers["Authorization"] = f"token {current_token}"

                params = {"q": query, "per_page": 100, "page": page}

                try:
                    response = requests.get(
                        self.GITHUB_API_URL, 
                        headers=headers, 
                        params=params, 
                        timeout=30, 
                        proxies=Config.get_random_proxy()
                    )

                    # 核心处理：二级限流 (403 或 429)
                    if response.status_code in (403, 429):
                        GitHubClient._CONSECUTIVE_403_COUNT += 1
                        # 阶梯式冷却：封禁次数越多，罚站时间越长 (60s, 120s, 240s...)
                        retry_after = int(response.headers.get('Retry-After', 60))
                        cooldown_period = max(retry_after, 60 * GitHubClient._CONSECUTIVE_403_COUNT)
                        
                        GitHubClient._GLOBAL_COOLDOWN_UNTIL = time.time() + cooldown_period
                        
                        logger.error(f"🚫 触发GitHub二级限流! 状态码: {response.status_code}")
                        logger.warning(f"💤 全局挂起 {cooldown_period}s，避开检测。Token: {current_token[:10]}...")
                        
                        self._wait_if_cooldown()
                        continue # 冷却后重试

                    response.raise_for_status()
                    
                    # 请求成功，重置连续错误计数
                    GitHubClient._CONSECUTIVE_403_COUNT = max(0, GitHubClient._CONSECUTIVE_403_COUNT - 1)
                    
                    page_result = response.json()
                    page_success = True
                    
                    if page == 1:
                        total_count = page_result.get("total_count", 0)
                        expected_total = min(total_count, 1000)
                    
                    items = page_result.get("items", [])
                    all_items.extend(items)
                    break # 成功跳出重试循环

                except Exception as e:
                    logger.debug(f"⚠️ 第 {attempt} 次重试失败: {str(e)}")
                    time.sleep(min(5 * attempt, 30))

            if not page_success or not items: break
            if len(all_items) >= (expected_total or 1000): break

            # 翻页间的模拟人类行为：拉长延迟至 5-12 秒
            time.sleep(random.uniform(5.0, 12.0))

        logger.info(f"🔍 搜索完成: 【{query[:30]}...】 | 命中: {len(all_items)} | 总计: {total_count}")
        return {"total_count": total_count, "items": all_items}

    def get_file_content(self, item: Dict[str, Any]) -> Optional[str]:
        """获取文件内容时同样执行频率保护"""
        self._wait_if_cooldown()
        
        repo_name = item["repository"]["full_name"]
        url = f"https://api.github.com/repos/{repo_name}/contents/{item['path']}"
        headers = {"Accept": "application/vnd.github.v3+json"}
        token = self._next_token()
        if token: headers["Authorization"] = f"token {token}"

        try:
            res = requests.get(url, headers=headers, proxies=Config.get_random_proxy(), timeout=20)
            if res.status_code == 403:
                GitHubClient._GLOBAL_COOLDOWN_UNTIL = time.time() + 60
                return None
            
            res.raise_for_status()
            data = res.json()
            if data.get("encoding") == "base64" and data.get("content"):
                return base64.b64decode(data["content"]).decode('utf-8', errors='ignore')
            
            download_url = data.get("download_url")
            if download_url:
                return requests.get(download_url, timeout=20).text
        except: pass
        return None

    @staticmethod
    def create_instance(tokens: List[str]) -> 'GitHubClient':
        return GitHubClient(tokens)
