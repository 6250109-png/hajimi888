import json
import os
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Set

from common.Logger import logger
from common.config import Config


@dataclass
class Checkpoint:
    last_scan_time: Optional[str] = None
    scanned_shas: Set[str] = field(default_factory=set)
    processed_queries: Set[str] = field(default_factory=set)
    wait_send_balancer: Set[str] = field(default_factory=set)
    wait_send_gpt_load: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，但不包含scanned_shas（单独存储）"""
        return {
            "last_scan_time": self.last_scan_time,
            "processed_queries": list(self.processed_queries),
            "wait_send_balancer": list(self.wait_send_balancer),
            "wait_send_gpt_load": list(self.wait_send_gpt_load)
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Checkpoint':
        """从字典创建Checkpoint对象，scanned_shas需要单独加载"""
        return cls(
            last_scan_time=data.get("last_scan_time"),
            scanned_shas=set(),  # 将通过FileManager单独加载
            processed_queries=set(data.get("processed_queries", [])),
            wait_send_balancer=set(data.get("wait_send_balancer", [])),
            wait_send_gpt_load=set(data.get("wait_send_gpt_load", []))
        )

    def add_scanned_sha(self, sha: str) -> None:
        if sha:
            self.scanned_shas.add(sha)

    def add_processed_query(self, query: str) -> None:
        if query:
            self.processed_queries.add(query)

    def update_scan_time(self) -> None:
        self.last_scan_time = datetime.utcnow().isoformat()


class FileManager:
    """文件管理器：负责 GitHub PAT 扫描相关的所有文件操作"""

    def __init__(self, data_dir: str):
        """
        初始化FileManager并完成所有必要的设置
        """
        logger.info("🔧 Initializing FileManager (GitHub PAT Edition)")

        # 1. 基础路径设置
        self.data_dir = data_dir
        self.checkpoint_file = os.path.join(data_dir, "checkpoint.json")
        self.scanned_shas_file = os.path.join(data_dir, Config.SCANNED_SHAS_FILE)

        # 2. 动态文件名
        self._detail_log_filename: Optional[str] = None
        self._keys_valid_filename: Optional[str] = None
        self._rate_limited_filename: Optional[str] = None
        self._rate_limited_detail_filename: Optional[str] = None
        self._keys_send_filename: Optional[str] = None
        self._keys_send_detail_filename: Optional[str] = None

        # 3. 创建数据目录
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
            logger.info(f"Created data directory: {self.data_dir}")

        # 4. 加载搜索查询
        try:
            self._search_queries = self.load_search_queries(Config.QUERIES_FILE)
            logger.info(f"✅ Loaded {len(self._search_queries)} search queries")
        except Exception as e:
            logger.error(f"❌ Failed to load search queries: {e}")
            self._search_queries = []

        # 5. 初始化文件名
        start_time = datetime.now()

        self._keys_valid_filename = os.path.join(self.data_dir, f"{Config.VALID_KEY_PREFIX}{start_time.strftime('%Y%m%d')}.txt")
        self._rate_limited_filename = os.path.join(self.data_dir, f"{Config.RATE_LIMITED_KEY_PREFIX}{start_time.strftime('%Y%m%d')}.txt")
        self._keys_send_filename = os.path.join(self.data_dir, f"{Config.KEYS_SEND_PREFIX}{start_time.strftime('%Y%m%d')}.txt")
        
        self._detail_log_filename = os.path.join(self.data_dir, f"{ Config.VALID_KEY_DETAIL_PREFIX.rstrip('_')}{start_time.strftime('%Y%m%d')}.log")
        self._rate_limited_detail_filename = os.path.join(self.data_dir, f"{Config.RATE_LIMITED_KEY_DETAIL_PREFIX}{start_time.strftime('%Y%m%d')}.log")
        self._keys_send_detail_filename = os.path.join(self.data_dir, f"{Config.KEYS_SEND_DETAIL_PREFIX}{start_time.strftime('%Y%m%d')}.log")

        # 创建目录和空文件
        for filename in [self._detail_log_filename, self._keys_valid_filename, self._rate_limited_filename, self._rate_limited_detail_filename, self._keys_send_filename, self._keys_send_detail_filename]:
            parent_dir = os.path.dirname(filename)
            if parent_dir: os.makedirs(parent_dir, exist_ok=True)
            if not os.path.exists(filename):
                with open(filename, 'a', encoding='utf-8') as f: f.write("")

        logger.info("✅ FileManager initialization complete")

    def check(self) -> bool:
        """检查文件状态"""
        if not hasattr(self, '_search_queries') or not self._search_queries:
            logger.error("❌ Search queries: Not loaded or empty")
            return False
        return True

    def load_checkpoint(self) -> Checkpoint:
        checkpoint = Checkpoint()
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    checkpoint = Checkpoint.from_dict(data)
            except Exception as e:
                logger.warning(f"Cannot read checkpoint: {e}")
        else:
            self.save_checkpoint(checkpoint)
        checkpoint.scanned_shas = self.load_scanned_shas()
        return checkpoint

    def load_scanned_shas(self) -> Set[str]:
        scanned_shas = set()
        if os.path.isfile(self.scanned_shas_file):
            try:
                with open(self.scanned_shas_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'): scanned_shas.add(line)
            except Exception as e: logger.error(f"Read SHA error: {e}")
        return scanned_shas

    def load_search_queries(self, queries_file_path: str) -> List[str]:
        queries = []
        full_path = os.path.join(self.data_dir, queries_file_path)
        if not os.path.exists(full_path):
            self._create_default_queries_file(full_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'): queries.append(line)
        except Exception as e: logger.error(f"Read queries error: {e}")
        return queries

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        self.save_scanned_shas(checkpoint.scanned_shas)
        try:
            with open(self.checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(checkpoint.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e: logger.error(f"Save checkpoint error: {e}")

    def save_scanned_shas(self, scanned_shas: Set[str]) -> None:
        try:
            with open(self.scanned_shas_file, "w", encoding="utf-8") as f:
                f.write(f"# GitHub PAT Scanned SHAs\n# Last Update: {datetime.now()}\n\n")
                for sha in sorted(scanned_shas): f.write(f"{sha}\n")
        except Exception as e: logger.error(f"Save SHA error: {e}")

    def save_valid_keys(self, repo_name: str, file_path: str, file_url: str, valid_keys: List[str]) -> None:
        if not valid_keys or not self._detail_log_filename: return
        with open(self._detail_log_filename, "a", encoding="utf-8") as f:
            f.write(f"TIME: {datetime.now()}\nURL: {file_url}\n")
            for key in valid_keys: f.write(f"TOKEN: {key}\n")
            f.write("-" * 80 + "\n")
        if self._keys_valid_filename:
            with open(self._keys_valid_filename, "a", encoding="utf-8") as f:
                for key in valid_keys: f.write(f"{key}\n")

    def save_rate_limited_keys(self, repo_name: str, file_path: str, file_url: str, rate_limited_keys: List[str]) -> None:
        if not rate_limited_keys: return
        if self._rate_limited_filename:
            with open(self._rate_limited_filename, "a", encoding="utf-8") as f:
                for key in rate_limited_keys: f.write(f"{key}\n")

    def save_keys_send_result(self, keys: List[str], send_result: dict) -> None:
        if not keys: return
        if self._keys_send_filename:
            with open(self._keys_send_filename, "a", encoding="utf-8") as f:
                for key in keys: f.write(f"{key} | {send_result.get(key, 'unknown')}\n")

    def append_scanned_sha(self, sha: str) -> None:
        if not sha: return
        try:
            with open(self.scanned_shas_file, "a", encoding="utf-8") as f: f.write(f"{sha}\n")
        except Exception: pass

    def get_search_queries(self) -> List[str]:
        return getattr(self, '_search_queries', [])

    # ================================
    # 核心修改：针对 github_pat_ 的默认搜索词
    # ================================
    def _create_default_queries_file(self, queries_file: str) -> None:
        """创建 GitHub Token 专项查询文件"""
        try:
            os.makedirs(os.path.dirname(queries_file), exist_ok=True)
            with open(queries_file, "w", encoding="utf-8") as f:
                f.write("# GitHub Fine-grained PAT 专项扫描配置文件\n")
                f.write("# 技巧：使用引号包裹前缀实现精准匹配\n\n")
                f.write("\"github_pat_\" in:file\n")
                f.write("\"github_pat_\" extension:env\n")
                f.write("\"github_pat_\" filename:config.py\n")
                f.write("\"github_pat_\" language:shell\n")
                f.write("\"github_pat_\" language:python\n")
                f.write("\"github_pat_\" path:.github/workflows\n")
            logger.info(f"✅ Created GitHub PAT default queries file: {queries_file}")
        except Exception as e:
            logger.error(f"Failed to create queries file: {e}")

file_manager = FileManager(Config.DATA_PATH)
checkpoint = file_manager.load_checkpoint()
