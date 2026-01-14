import os
import random
from typing import Dict, Optional

from dotenv import load_dotenv

from common.Logger import logger

# 只在环境变量不存在时才从.env加载值
load_dotenv(override=False)


class Config:
    GITHUB_TOKENS_STR = os.getenv("GITHUB_TOKENS", "")

    # 获取GitHub tokens列表
    GITHUB_TOKENS = [token.strip() for token in GITHUB_TOKENS_STR.split(',') if token.strip()]
    DATA_PATH = os.getenv('DATA_PATH', '/app/data')
    PROXY_LIST_STR = os.getenv("PROXY", "")
    
    # 解析代理列表，支持格式：http://user:pass@host:port,http://host:port,socks5://user:pass@host:port
    PROXY_LIST = []
    if PROXY_LIST_STR:
        for proxy_str in PROXY_LIST_STR.split(','):
            proxy_str = proxy_str.strip()
            if proxy_str:
                PROXY_LIST.append(proxy_str)
    
    # Grok / xAI Balancer 配置 (原 Gemini Balancer)
    # 如果你还需要同步到外部负载均衡器，这里保留逻辑但更名为 GROK 相关
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
    
    # 日期范围过滤器配置 (单位：天)
    DATE_RANGE_DAYS = int(os.getenv("DATE_RANGE_DAYS", "730"))  # 默认730天 (约2年)

    # 查询文件路径配置
    QUERIES_FILE = os.getenv("QUERIES_FILE", "queries.txt")

    # 已扫描SHA文件配置
    SCANNED_SHAS_FILE = os.getenv("SCANNED_SHAS_FILE", "scanned_shas.txt")

    # 【核心修改】Grok模型配置
    # 默认使用 grok-2-latest，这是目前 xAI 最稳定的验证模型
    HAJIMI_CHECK_MODEL = os.getenv("HAJIMI_CHECK_MODEL", "grok-2-latest")

    # 文件路径黑名单配置
    FILE_PATH_BLACKLIST_STR = os.getenv("FILE_PATH_BLACKLIST", "readme,docs,doc/,.md,sample,tutorial")
    FILE_PATH_BLACKLIST = [token.strip().lower() for token in FILE_PATH_BLACKLIST_STR.split(',') if token.strip()]

    @classmethod
    def parse_bool(cls, value: str) -> bool:
        if isinstance(value, bool):
            return value
        
        if isinstance(value, str):
            value = value.strip().lower()
            return value in ('true', '1', 'yes', 'on', 'enabled')
        
        if isinstance(value, int):
            return bool(value)
        
        return False

    @classmethod
    def get_random_proxy(cls) -> Optional[Dict[str, str]]:
        if not cls.PROXY_LIST:
            return None
        
        proxy_url = random.choice(cls.PROXY_LIST).strip()
        
        # 返回requests格式的proxies字典
        return {
            'http': proxy_url,
            'https': proxy_url
        }

    @classmethod
    def check(cls) -> bool:
        logger.info("🔍 Checking required configurations (Grok Edition)...")
        
        errors = []
        
        # 检查GitHub tokens
        if not cls.GITHUB_TOKENS:
            errors.append("GitHub tokens not found. Please set GITHUB_TOKENS environment variable.")
            logger.error("❌ GitHub tokens: Missing")
        else:
            logger.info(f"✅ GitHub tokens: {len(cls.GITHUB_TOKENS)} configured")
        
        # 检查 Grok Balancer 配置
        if cls.parse_bool(cls.GROK_BALANCER_SYNC_ENABLED):
            logger.info(f"✅ Grok Balancer enabled, URL: {cls.GROK_BALANCER_URL}")
            if not cls.GROK_BALANCER_AUTH or not cls.GROK_BALANCER_URL:
                logger.warning("⚠️ Grok Balancer Auth or URL Missing (Balancer功能将被禁用)")
            else:
                logger.info(f"✅ Grok Balancer Auth: ****")
        else:
            logger.info("ℹ️ Grok Balancer: Not configured")

        # 检查GPT Load Balancer配置
        if cls.parse_bool(cls.GPT_LOAD_SYNC_ENABLED):
            logger.info(f"✅ GPT Load Balancer enabled, URL: {cls.GPT_LOAD_URL}")
            if not cls.GPT_LOAD_AUTH or not cls.GPT_LOAD_URL or not cls.GPT_LOAD_GROUP_NAME:
                logger.warning("⚠️ GPT Load Balancer Auth, URL or Group Name Missing (Load Balancer功能将被禁用)")
            else:
                logger.info(f"✅ GPT Load Balancer Auth: ****")
                logger.info(f"✅ GPT Load Balancer Group Name: {cls.GPT_LOAD_GROUP_NAME}")
        else:
            logger.info("ℹ️ GPT Load Balancer: Not configured")

        if errors:
            logger.error("❌ Configuration check failed:")
            return False
        
        logger.info("✅ All required configurations are valid")
        return True


# 启动时打印配置状态
logger.info(f"*" * 30 + " GROK CONFIG START " + "*" * 30)
logger.info(f"GITHUB_TOKENS: {len(Config.GITHUB_TOKENS)} tokens")
logger.info(f"PROXY_LIST: {len(Config.PROXY_LIST)} proxies configured")
logger.info(f"HAJIMI_CHECK_MODEL: {Config.HAJIMI_CHECK_MODEL}")
logger.info(f"GROK_BALANCER_SYNC_ENABLED: {Config.parse_bool(Config.GROK_BALANCER_SYNC_ENABLED)}")
logger.info(f"DATE_RANGE_DAYS: {Config.DATE_RANGE_DAYS} days")
logger.info(f"QUERIES_FILE: {Config.QUERIES_FILE}")
logger.info(f"*" * 30 + " CONFIG END " + "*" * 30)

# 创建全局配置实例
config = Config()
