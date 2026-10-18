"""全局配置。全部可用环境变量覆盖(默认值只依赖 $HOME,不含任何个人路径)。

本服务把 PDF 转成 Markdown:转换由引擎子进程完成(默认 **MinerU**,可选
PaddleX),本进程只做 UI、任务排队与产物打包。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
HOME = Path.home()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


# --- 服务 ---
HOST = _env("OT_HOST", "0.0.0.0")
PORT = _env_int("OT_PORT", 8300)

# --- 数据 ---
DATA_DIR = Path(_env("OT_DATA_DIR", str(BASE_DIR / "data"))).resolve()
JOB_DIR = DATA_DIR / "jobs"
for _d in (DATA_DIR, JOB_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- 转换引擎:PaddleX(PDF → Markdown) ------------------------------------
# 用 paddle 环境的解释器跑(app 自己的 venv 不装 paddle/torch,保持轻量)。
PADDLE_PYTHON = _env("OT_PADDLE_PYTHON", str(HOME / "anaconda3/envs/paddle/bin/python"))
# PP-StructureV3 = 版面分析管线(标题/段落/表格/图片/公式),输出的 md 才有结构。
# 想更快可换 PaddleOCR-VL,或轻量纯文字 "OCR"(不推荐,会丢版面)。
PADDLE_PIPELINE = _env("OT_PADDLE_PIPELINE", "PP-StructureV3")
# --- MinerU(默认引擎:文字层 + 公式/表格识别) ---
MINERU_PYTHON = _env("OT_MINERU_PYTHON", str(HOME / "venvs/mineru/bin/python"))
MINERU_BIN = _env("OT_MINERU_BIN", str(HOME / "venvs/mineru/bin/mineru"))
MINERU_MODEL_SOURCE = _env("OT_MINERU_MODEL_SOURCE", "modelscope")
MINERU_VRAM_MB = _env_int("OT_MINERU_VRAM_MB", 16000)

# 默认引擎;前端可按任务覆盖
ENGINE_DEFAULT = _env("OT_ENGINE", "MinerU")

# 允许前端按任务选管线:
#   PP-StructureV3 = 标准(快,版面+表格+公式)
#   PaddleOCR-VL   = 精细(慢一倍,文字/表格更干净)
PIPELINES = {
    "MinerU": "最佳（文字层 + 公式/表格识别，推荐）",
    "PP-StructureV3": "标准（PaddleX 版面 + OCR，快、依赖少）",
    "PaddleOCR-VL": "精细（PaddleX VLM，慢一倍）",
}
# auto = 自动挑显存够的卡;也可是 cpu / gpu:4
PADDLE_DEVICE = _env("OT_PADDLE_DEVICE", "auto")
# 单任务显存上限(共享 GPU 上防把别人的卡吃满);0 = 不限
PADDLE_GPU_MEM_MB = _env_int("OT_PADDLE_GPU_MEM_MB", 16384)
PADDLEX_HOME = _env("OT_PADDLEX_HOME", str(HOME / "model_zoo/paddlex"))

# 单任务超时(秒):大文档留足;超时由 app 杀掉子进程
JOB_TIMEOUT_SEC = _env_int("OT_JOB_TIMEOUT_SEC", 4 * 3600)
