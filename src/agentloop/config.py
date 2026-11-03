"""读取「配置.txt」：KEY=VALUE 纯文本，# 开头为注释，兼容 UTF-8 BOM 与 CRLF。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError

DEFAULT_DICTIONARY = "资料/干眼共病模型_数据字典_V1.0.xlsx"


@dataclass
class Config:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    max_rounds: int = 5
    token_budget: int = 2_000_000
    data_dictionary: Path = Path(DEFAULT_DICTIONARY)
    ncbi_api_key: str = ""
    project_dir: Path = field(default_factory=Path.cwd)

    def snapshot(self) -> dict:
        """写入运行目录的配置快照。绝不包含任何密钥。"""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "max_rounds": self.max_rounds,
            "token_budget": self.token_budget,
            "data_dictionary": str(self.data_dictionary),
        }


def parse_config_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def _int(values: dict[str, str], key: str, default: int) -> int:
    raw = values.get(key, "")
    if raw == "":
        return default
    try:
        number = int(raw.replace(",", "").replace("_", ""))
    except ValueError:
        raise ConfigError(f"配置.txt 中 {key} 应该是一个整数，现在是「{raw}」。请修改后保存。") from None
    if number <= 0:
        raise ConfigError(f"配置.txt 中 {key} 必须大于 0。请修改后保存。")
    return number


def load_config(path: Path, require_api_key: bool = True) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"找不到配置文件：{path}。请双击启动文件，它会自动创建。")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="gbk", errors="replace")
    values = parse_config_text(text)
    project_dir = path.resolve().parent
    api_key = values.get("API_KEY", "")
    if require_api_key and not api_key:
        raise ConfigError("配置.txt 里还没有填写 API Key。请把 API Key 粘贴到 API_KEY= 后面，保存后重新启动。")
    dictionary = Path(values.get("DATA_DICTIONARY") or DEFAULT_DICTIONARY)
    if not dictionary.is_absolute():
        dictionary = project_dir / dictionary
    return Config(
        api_key=api_key,
        base_url=values.get("BASE_URL") or Config.base_url,
        model=values.get("MODEL") or Config.model,
        max_rounds=_int(values, "MAX_ROUNDS", Config.max_rounds),
        token_budget=_int(values, "TOKEN_BUDGET", Config.token_budget),
        data_dictionary=dictionary,
        ncbi_api_key=values.get("NCBI_API_KEY", ""),
        project_dir=project_dir,
    )
