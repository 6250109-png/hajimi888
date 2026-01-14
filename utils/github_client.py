import base64
import random
import time
from typing import Dict, List, Optional, Any
import requests
from common.Logger import logger
from common.config import Config

class GitHubClient:
    GITHUB_API_URL = "https://api.github.com/search/code"

    def __init__(self, tokens: List[str]):
        # 严谨处理：过滤空值并去重，确保 Token 池纯净
        self.tokens = list(set([tk.strip() for tk in tokens if tk.strip()]))
        self._token_ptr = 0
        if not self.tokens:
            logger.error("❌ No valid GitHub tokens found in Config!")

    def _next_token(self) -> Optional[str]:
        if not self.tokens: return None
        token = self.tokens[self._token_ptr % len(self.tokens)]
        self._token_ptr += 1
        return token

    def search_for_keys(self, query: str, max_retries: int = 5) -> Dict[str, Any]:
        """
        执行 GitHub 搜索任务。
        配合主程序的 DeepScan 逻辑，此处处理单次时间分片的 1-10 页结果。
        """
        all_items = []
        total_count = 0
        expected_total = None
        pages_processed = 0

        # GitHub 搜索 API 最多允许访问前 1000 条结果（即 100 条/页 * 10 页）
        for page in range(1, 11):
            page_result = None
            page_success = False

            for attempt in range(1, max_retries + 1):
                current_token = self._next_token()
                headers = {
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HajimiScanner/2.0"
                }

                if current_token:
                    headers["Authorization"] = f"token {current_token}"

                params = {"q": query, "per_page": 100, "page": page}

                try:
                    proxies = Config.get_random_proxy()
                    # 执行请求
                    response = requests.get(
                        self.GITHUB_API_URL, 
                        headers=headers, 
                        params=params, 
                        timeout=30, 
                        proxies=proxies
                    )
                    
                    # 频率限制监测
                    remaining = response.headers.get('X-RateLimit-Remaining')
                    if remaining and int(remaining) < 5:
                        logger.warning(f"⚠️ Token 剩余配额极低: {remaining} | Token: {current_token[:10]}...")

                    # 处理 403 情况（GitHub 经常对包含 "github_pat_" 的查询进行二级封禁）
                    if response.status_code == 403:
                        wait_time = int(response.headers.get('Retry-After', 60))
                        logger.warning(f"🚫 触发 GitHub 二级限流，等待 {wait_time} 秒...")
                        time.sleep(wait_time)
                        continue

                    response.raise_for_status()
                    page_result = response.json()
                    page_success = True
                    break

                except Exception as e:
                    wait = min(2 ** attempt, 30)
                    if attempt == max_retries:
                        logger.error(f"❌ 搜索失败 (Page {page}): {str(e)}")
                    time.sleep(wait)

            if not page_success or not page_result: break

            pages_processed += 1
            if page == 1:
                total_count = page_result.get("total_count", 0)
                expected_total = min(total_count, 1000)

            items = page_result.get("items", [])
            if not items: break
            
            all_items.extend(items)
            
            # 满足预期数量即停止，节省配额
            if len(all_items) >= (expected_total or 1000): break

            # 页面间随机延迟，模拟人类行为
            time.sleep(random.uniform(1.0, 2.5))

        logger.info(f"🔍 搜索完成: 【{query[:40]}...】 | 命中: {len(all_items)} | 总计: {total_count}")
        return {"total_count": total_count, "items": all_items}

    def get_file_content(self, item: Dict[str, Any]) -> Optional[str]:
        """获取并解码文件内容，优先使用 Base64 接口以提高速度"""
        repo_name = item["repository"]["full_name"]
        path = item["path"]
        url = f"https://api.github.com/repos/{repo_name}/contents/{path}"
        
        headers = {"Accept": "application/vnd.github.v3+json"}
        token = self._next_token()
        if token: headers["Authorization"] = f"token {token}"

        try:
            res = requests.get(url, headers=headers, proxies=Config.get_random_proxy(), timeout=20)
            res.raise_for_status()
            data = res.json()
            
            # 优先 Base64 解码，避免二次请求 download_url
            if data.get("encoding") == "base64" and data.get("content"):
                return base64.b64decode(data["content"]).decode('utf-8', errors='ignore')
            
            # 备选下载方案
            download_url = data.get("download_url")
            if download_url:
                content_res = requests.get(download_url, headers=headers, timeout=20)
                return content_res.text
                
        except Exception as e:
            logger.debug(f"⚠️ 提取文件失败 {path}: {str(e)}")
        return None

    @staticmethod
    def create_instance(tokens: List[str]) -> 'GitHubClient':
        return GitHubClient(tokens)
