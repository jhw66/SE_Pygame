"""五关进度与本地管理员配置；不参与箭头运动和碰撞规则。"""
import hmac
import json
from dataclasses import dataclass
from pathlib import Path

from levels import LevelConfig
from game_logic import positive_integer


LEVEL_COUNT = 5
CONFIG_DIR = Path(__file__).resolve().parent / "config"
DEFAULT_ADMIN_PATH = CONFIG_DIR / "admin.json"
DEFAULT_CAMPAIGN_PATH = CONFIG_DIR / "campaign.json"


def ensure_local_config(path):
    """首次运行从同目录模板创建本地配置；已有文件绝不覆盖。"""
    path = Path(path)
    if path.exists():
        return
    template = path.with_name(path.stem + ".example.json")
    content = template.read_bytes()
    try:
        with path.open("xb") as target:
            target.write(content)
    except FileExistsError:
        pass  # 同时启动的另一实例已经创建配置。


@dataclass(frozen=True)
class CampaignLevel:
    name: str
    config: LevelConfig
    lives: int


def validate_lives(value):
    positive_integer(value, "生命值")
    if value > 20:
        raise ValueError("生命值最多为 20，以便完整显示爱心")
    return value


def read_campaign(path):
    """完整校验后才替换配置，错误不泄露 JSON 内容。"""
    try:
        ensure_local_config(path)
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("无法读取 config/campaign.json，请检查文件和 JSON 格式") from exc
    if not isinstance(data, dict) or set(data) != {"levels"}:
        raise ValueError("配置仅包含 levels；请检查字段名")
    entries = data.get("levels")
    if not isinstance(entries, list) or len(entries) != LEVEL_COUNT:
        raise ValueError("levels 必须恰好包含五个关卡对象")
    levels = []
    allowed = {"name", "lives", "rows", "cols", "arrow_count", "min_length", "max_length", "turn_probability"}
    for index, entry in enumerate(entries):
        try:
            if not isinstance(entry, dict) or set(entry) - allowed:
                raise ValueError("关卡对象包含未知字段")
            if not {"rows", "cols", "arrow_count", "lives"} <= entry.keys():
                raise ValueError("缺少 rows、cols、arrow_count 或 lives")
            name = entry.get("name", f"第 {index + 1} 关")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("name 必须是非空字符串")
            config = LevelConfig(**{key: value for key, value in entry.items()
                                    if key not in {"name", "lives"}})
            levels.append(CampaignLevel(name, config, validate_lives(entry["lives"])))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"第 {index + 1} 关配置错误：{exc}") from exc
    return tuple(levels)


def read_admin_password(path):
    """读取本地 JSON；错误消息不包含文件内容或密码。"""
    try:
        ensure_local_config(path)
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, "未找到 config/admin.json 或模板，请先配置管理员密码"
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "管理员 JSON 无法读取或格式错误"
    if not isinstance(data, dict) or not isinstance(data.get("password"), str):
        return None, "管理员 JSON 需要字符串类型的 password 字段"
    password = data["password"]
    if not password.strip():
        return None, "管理员密码尚未设置"
    try:
        password.encode("utf-8")
    except UnicodeError:
        return None, "管理员密码包含无效字符"
    return password, ""


class Campaign:
    """解锁权限与真实通关分开，只保存在本次运行的内存中。"""
    def __init__(self, admin_path=None, config_path=None):
        self.admin_path = Path(admin_path) if admin_path is not None else DEFAULT_ADMIN_PATH
        self.config_path = Path(config_path) if config_path is not None else DEFAULT_CAMPAIGN_PATH
        self.levels = ()
        self.config_error = ""
        self.highest_unlocked = 0
        self.completed = set()
        self.admin_unlocked = False
        self.reload_config()
        # 首次运行同时准备空密码配置；配置错误仍由管理员入口显示。
        read_admin_password(self.admin_path)

    def reload_config(self):
        try:
            levels = read_campaign(self.config_path)
        except ValueError as exc:
            self.config_error = str(exc)
            return False, self.config_error
        changed = levels != self.levels
        self.levels = levels
        self.config_error = ""
        if changed:
            self.highest_unlocked = 0
            self.completed.clear()
        return changed, "配置已更新，通关进度已重置" if changed else "配置已读取，内容未改变"

    def can_enter(self, index):
        return 0 <= index < len(self.levels) and (
            self.admin_unlocked or index <= self.highest_unlocked)

    def record_win(self, index):
        if not 0 <= index < len(self.levels):
            raise ValueError("关卡索引超出范围")
        self.completed.add(index)
        self.highest_unlocked = max(self.highest_unlocked, min(index + 1, len(self.levels) - 1))

    @property
    def all_completed(self):
        return len(self.completed) == LEVEL_COUNT

    def authenticate(self, entered):
        # 提交时重新读取，修改本地 JSON 后无需重新启动游戏。
        password, error = read_admin_password(self.admin_path)
        if error:
            return False, error
        try:
            matched = hmac.compare_digest(entered.encode("utf-8"), password.encode("utf-8"))
        except UnicodeError:
            matched = False
        if not matched:
            return False, "密码错误，请重新输入"
        self.admin_unlocked = True
        return True, "管理员已解锁全部五关（仅本次运行有效）"
