import os
import random
from typing import Dict, Optional
from dotenv import load_dotenv
from common.Logger import logger

# 只在环境变量不存在时才从.env加载值
load_dotenv(override=False)


class Config:
    GITHUB_TOKENS_STR = os.getenv("GITHUB_TOKENS", "")

    # 获取GitHub tokens列表 (用于执行搜索任务的Token)
    GITHUB_TOKENS = [token.strip() for token in GITHUB_TOKENS_STR.split(',') if token.strip()]
    DATA_PATH = os.getenv('DATA_PATH', '/app/data')
    PROXY_LIST_STR = os.getenv("PROXY", "")
    
    # 解析代理列表
    PROXY_LIST = []
    if PROXY_LIST_STR:
        for proxy_str in PROXY_LIST_STR.split(','):
            proxy_str = proxy_str.strip()
            if proxy_str:
                PROXY_LIST.append(proxy_str)
    
    # === 【深度扫描专项配置】 借鉴 Selenium 深度搜索技巧 ===
    # 开启后将按时间段拆分搜索，彻底突破 GitHub API 1000条结果限制
    DEEP_SCAN_ENABLED = os.getenv("DEEP_SCAN_ENABLED", "true").lower() == "true"
    # 每次扫描的时间跨度（天），建议为 3-7 天，跨度越小扫描越深
    DEEP_SCAN_INTERVAL_DAYS = int(os.getenv("DEEP_SCAN_INTERVAL_DAYS", "7"))
    # 全局排除 Dork：在搜索请求级别直接过滤文档、测试和说明文件，提升结果含金量
    GLOBAL_EXCLUDE_DORK = "-path:docs -path:tests -path:samples -filename:README.md -filename:package-lock.json -path:node_modules"

    # === 同步配置 (保留更名为 GROK 相关) ===
    GROK_BALANCER_SYNC_ENABLED = os.getenv("GROK_BALANCER_SYNC_ENABLED", "false")
    GROK_BALANCER_URL = os.getenv("GROK_BALANCER_URL", "")
    GROK_BALANCER_AUTH = os.getenv("GROK_BALANCER_AUTH", "")

    # GPT Load Balancer Configuration
    GPT_LOAD_SYNC_ENABLED = os.getenv("GPT_LOAD_SYNC_ENABLED", "false")
    GPT_LOAD_URL = os.getenv('GPT_LOAD_URL', '')
    GPT_LOAD_AUTH = os.getenv('GPT_LOAD_AUTH', '')
    GPT_LOAD_GROUP_NAME = os.getenv('GPT_LOAD_GROUP_NAME', '')

    # 文件前缀配置
    VALID_KEY_PREFIX = os.getenv("VALID_KEY_PREFIX", "keys/keys_valid_")
    RATE_LIMITED_KEY_PREFIX = os.getenv("RATE_LIMITED_KEY_PREFIX", "keys/key_429_")
    KEYS_SEND_PREFIX = os.getenv("KEYS_SEND_PREFIX", "keys/keys_send_")

    VALID_KEY_DETAIL_PREFIX = os.getenv("VALID_KEY_DETAIL_PREFIX", "logs/keys_valid_detail_")
    RATE_LIMITED_KEY_DETAIL_PREFIX = os.getenv("RATE_LIMITED_KEY_DETAIL_PREFIX", "logs/key_429_detail_")
    KEYS_SEND_DETAIL_PREFIX = os.getenv("KEYS_SEND_DETAIL_PREFIX", "logs/keys_send_detail_")
    
    # 搜索回溯总时间 (单位：天)
    DATE_RANGE_DAYS = int(os.getenv("DATE_RANGE_DAYS", "365"))  # 搜索过去一年的泄露

    # 查询文件路径
    QUERIES_FILE = os.getenv("QUERIES_FILE", "queries.txt")

    # 已扫描SHA文件
    SCANNED_SHAS_FILE = os.getenv("SCANNED_SHAS_FILE", "scanned_shas.txt")

    # === 【关键修改】验证逻辑配置 ===
    # 由于我们要搜的是 github_pat_，验证地址改为 GitHub 官方 API
    GITHUB_API_URL = "https://api.github.com/user"
    HAJIMI_CHECK_MODEL = os.getenv("HAJIMI_CHECK_MODEL", "github-token-scan")

    # 文件路径内部黑名单 (二次过滤)
    FILE_PATH_BLACKLIST_STR = os.getenv("FILE_PATH_BLACKLIST", "readme,docs,doc/,.md,sample,tutorial,node_modules")
    FILE_PATH_BLACKLIST = [token.strip().lower() for token in FILE_PATH_BLACKLIST_STR.split(',') if token.strip()]

    @classmethod
    def parse_bool(cls, value: str) -> bool:
        if isinstance(value, bool): return value
        if isinstance(value, str):
            value = value.strip().lower()
            return value in ('true', '1', 'yes', 'on', 'enabled')
        return False

    @classmethod
    def get_random_proxy(cls) -> Optional[Dict[str, str]]:
        if not cls.PROXY_LIST: return None
        proxy_url = random.choice(cls.PROXY_LIST).strip()
        return {'http': proxy_url, 'https': proxy_url}

    @classmethod
    def check(cls) -> bool:
        logger.info("🔍 Checking required configurations (GitHub PAT DeepScan Edition)...")
        if not cls.GITHUB_TOKENS:
            logger.error("❌ GitHub tokens: Missing (必须填入 Token 才能开始搜索)")
            return False
        return True


# 启动时打印配置状态
logger.info(f"*" * 30 + " GITHUB PAT SCAN CONFIG " + "*" * 30)
logger.info(f"GITHUB_TOKENS: {len(Config.GITHUB_TOKENS)} tokens")
logger.info(f"DEEP_SCAN: {Config.DEEP_SCAN_ENABLED} (Interval: {Config.DEEP_SCAN_INTERVAL_DAYS} days)")
logger.info(f"EXCLUDE_DORK: {Config.GLOBAL_EXCLUDE_DORK}")
logger.info(f"DATE_RANGE_DAYS: {Config.DATE_RANGE_DAYS} days")
logger.info(f"*" * 30 + " CONFIG END " + "*" * 30)

config = Config()
