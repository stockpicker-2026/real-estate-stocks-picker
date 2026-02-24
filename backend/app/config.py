import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/realestate.db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
REFRESH_HOUR = int(os.getenv("REFRESH_HOUR", "9"))
REFRESH_MINUTE = int(os.getenv("REFRESH_MINUTE", "0"))

# 腾讯混元 API 配置
HUNYUAN_SECRET_ID = os.getenv("HUNYUAN_SECRET_ID", "")
HUNYUAN_SECRET_KEY = os.getenv("HUNYUAN_SECRET_KEY", "")
HUNYUAN_MODEL = os.getenv("HUNYUAN_MODEL", "hunyuan-2.0-thinking-20251109")

# JWT 配置
JWT_SECRET = os.getenv("JWT_SECRET", "real-estate-stock-agent-secret-key-2025")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72

# 默认管理员（首次启动自动创建）
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
