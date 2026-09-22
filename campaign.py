"""五关进度与本地管理员配置；不参与箭头运动和碰撞规则。"""
import hmac
import json
from dataclasses import dataclass
from pathlib import Path

from levels import LevelConfig
from game_logic import positive_integer


LEVEL_COUNT = 5
CONFIG_DIR = Path(__file__).resolve().parent / "config" # 当前文件下的绝对路径所在目录+目录下的config文件夹
DEFAULT_ADMIN_PATH = CONFIG_DIR / "admin.json"
DEFAULT_CAMPAIGN_PATH = CONFIG_DIR / "campaign.json"

# 首次运行从同目录模板创建本地配置,已有文件绝不覆盖
def ensure_local_config(path):
    path = Path(path)
    if path.exists():
        return
    template = path.with_name(path.stem + ".example.json")
    content = template.read_bytes()
    try: # x表示只允许新建，文件已经存在就报错；b表示按二进制写入
        with path.open("xb") as target:
            target.write(content)
    except FileExistsError:
        pass  # 同时启动的另一实例已经创建配置。

# JSON 中的一关转换成 Python 对象
@dataclass(frozen=True)
class CampaignLevel:
    name: str
    config: LevelConfig
    lives: int      # lives: int 这样的类型标注本身不会检查输入是否合法，真正的检查由后面的函数完成


def validate_lives(value):
    positive_integer(value, "生命值")
    if value > 20:
        raise ValueError("生命值最多为 20，以便完整显示爱心")
    return value

# 读取和检查全部五关
def read_campaign(path):
    try:
        ensure_local_config(path)
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("无法读取 config/campaign.json，请检查文件和 JSON 格式") from exc
    if not isinstance(data, dict) or set(data) != {"levels"}: # 检查最外层是否只有 levels 字段
        raise ValueError("配置仅包含 levels；请检查字段名")
    entries = data.get("levels")
    if not isinstance(entries, list) or len(entries) != LEVEL_COUNT:
        raise ValueError("levels 必须恰好包含五个关卡对象")
    levels = []
    allowed = {"name", "lives", "rows", "cols", "arrow_count", "min_length", "max_length", "turn_probability"}
    # 逐关检查字段、名称、棋盘参数和生命值
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
                                    if key not in {"name", "lives"}})  # **将剩余字典展开为函数的关键字参数
            levels.append(CampaignLevel(name, config, validate_lives(entry["lives"])))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"第 {index + 1} 关配置错误：{exc}") from exc
    return tuple(levels)

# 读取管理员文件
def read_admin_password(path):
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

# 保存本次游戏运行的整体进度
class Campaign:
    def __init__(self, admin_path=None, config_path=None):
        self.admin_path = Path(admin_path) if admin_path is not None else DEFAULT_ADMIN_PATH
        self.config_path = Path(config_path) if config_path is not None else DEFAULT_CAMPAIGN_PATH
        self.levels = ()                      # 当前有效的五关配置
        self.config_error = ""                # 最近一次读取配置的错误信息
        self.highest_unlocked = 0             # 普通模式开放到哪一关
        self.completed = set()                # 实际通关的关卡编号集合
        self.admin_unlocked = False           # 本次运行是否已经管理员解锁
        self.reload_config()
        read_admin_password(self.admin_path)  # 首次运行同时准备空密码配置；配置错误仍有管理员入口显示

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

    # 判断能否进入
    def can_enter(self, index):
        return 0 <= index < len(self.levels) and (
            self.admin_unlocked or index <= self.highest_unlocked)

    # 记录真实通关
    def record_win(self, index):
        if not 0 <= index < len(self.levels):
            raise ValueError("关卡索引超出范围")
        self.completed.add(index)
        self.highest_unlocked = max(self.highest_unlocked, min(index + 1, len(self.levels) - 1))

    @property
    def all_completed(self):
        return len(self.completed) == LEVEL_COUNT

    # 管理员验证
    def authenticate(self, entered):
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
