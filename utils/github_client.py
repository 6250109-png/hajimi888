import base64, random, time, requests
from typing import Dict, List, Optional, Any
from common.Logger import logger
from common.config import Config

class GitHubClient:
    GITHUB_API_URL = "https://api.github.com/search/code"
    _GLOBAL_COOLDOWN_UNTIL = 0
    _CONSECUTIVE_403_COUNT = 0

    def __init__(self, tokens: List[str]):
        self.tokens = list(set([tk.strip() for tk in tokens if tk.strip()]))
        self._token_ptr = 0

    def _next_token(self) -> Optional[str]:
        if not self.tokens: return None
        token = self.tokens[self._token_ptr % len(self.tokens)]
        self._token_ptr += 1
        return token

    def _wait_if_cooldown(self):
        now = time.time()
        if now < GitHubClient._GLOBAL_COOLDOWN_UNTIL:
            wait_needed = GitHubClient._GLOBAL_COOLDOWN_UNTIL - now
            logger.warning(f"💤 二级限流保护中，罚站剩余: {wait_needed:.1f}s")
            time.sleep(wait_needed)

    def search_for_keys(self, query: str, max_retries: int = 5) -> Dict[str, Any]:
        all_items = []
        for page in range(1, 11):
            self._wait_if_cooldown()
            
            page_success = False
            for attempt in range(1, max_retries + 1):
                current_token = self._next_token()
                # 【新功能】动态混淆请求头
                headers = {
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(128,131)}.0.0.0 Safari/537.36",
                    "Referer": random.choice(["https://github.com/search/advanced", "https://github.com/"])
                }
                if current_token: headers["Authorization"] = f"token {current_token}"

                try:
                    res = requests.get(self.GITHUB_API_URL, params={"q": query, "per_page": 100, "page": page}, 
                                       headers=headers, proxies=Config.get_random_proxy(), timeout=30)
                    
                    if res.status_code in (403, 429):
                        GitHubClient._CONSECUTIVE_403_COUNT += 1
                        # 如果只有一个 Token，惩罚力度翻倍
                        penalty = 120 if len(self.tokens) <= 1 else 60
                        cooldown = penalty * GitHubClient._CONSECUTIVE_403_COUNT
                        GitHubClient._GLOBAL_COOLDOWN_UNTIL = time.time() + cooldown
                        logger.error(f"🚫 撞墙(403)了，全局静默 {cooldown}s")
                        self._wait_if_cooldown()
                        continue

                    res.raise_for_status()
                    GitHubClient._CONSECUTIVE_403_COUNT = 0 # 重置计数
                    page_result = res.json()
                    all_items.extend(page_result.get("items", []))
                    page_success = True
                    break
                except Exception as e:
                    time.sleep(attempt * 5)

            if not page_success or page >= 10: break
            # 翻页慢一点，像个人在看
            time.sleep(random.uniform(8.0, 15.0))

        return {"items": all_items}

    def get_file_content(self, item: Dict[str, Any]) -> Optional[str]:
        self._wait_if_cooldown()
        url = f"https://api.github.com/repos/{item['repository']['full_name']}/contents/{item['path']}"
        headers = {"Accept": "application/vnd.github.v3+json"}
        tk = self._next_token()
        if tk: headers["Authorization"] = f"token {tk}"
        try:
            res = requests.get(url, headers=headers, proxies=Config.get_random_proxy(), timeout=20)
            if res.status_code == 200:
                data = res.json()
                if data.get("encoding") == "base64":
                    return base64.b64decode(data["content"]).decode('utf-8', errors='ignore')
        except: pass
        return None

    @staticmethod
    def create_instance(tokens: List[str]) -> 'GitHubClient':
        return GitHubClient(tokens)
