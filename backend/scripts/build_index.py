# 构建/更新向量索引（一次性；之后启动服务时只做增量同步）
#
# 用法（在 backend/ 目录下）：
#   .venv\Scripts\python.exe scripts\build_index.py
#
# ⚠️ 建库前必须先停掉正在运行的后端服务：zvec 是进程内数据库，
#    同一个索引目录只能被一个进程打开，否则会报 "索引被占用 / Can't lock read-write collection"。
#
# 为什么要单独跑：
#   直接启动服务也行（启动时会自动建库），但那样服务会一直卡在启动阶段、
#   看不到进度；这个脚本会打印每批进度。
#
# 耗时完全取决于向量化供应商（见 config.EMBED_*）：
#   火山 Ark  doubao-embedding-vision  批量上限 10、限速约 10 次/分钟 → 约 50 分钟
#   SiliconFlow BAAI/bge-m3            批量 100、未遇限频            → 约 1 分钟
#
# 常用环境变量：
#   EMBED_BATCH          一次请求塞多少段（Ark 必须设回 10）
#   EMBED_DELAY_SECONDS  批间隔，默认 0.35；Ark 建库时建议 6
#   EMBED_RETRIES        429 重试次数
#   RAG_VECTOR_ENABLED=1 确保真的建库（.env 里被设成 0 时会跳过）

import sys
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core import config  # noqa: E402
from app.services import embeddings, vector_store  # noqa: E402

INDEX_DIR = Path(config.VECTOR_DIR)
_done = False


def index_size_mb() -> float:
    if not INDEX_DIR.exists():
        return 0.0
    return sum(p.stat().st_size for p in INDEX_DIR.rglob("*") if p.is_file()) / 1024 / 1024


def monitor() -> None:
    t0 = time.time()
    while not _done:
        print(f"[进度] 已用 {int(time.time() - t0)}s，索引目录 {index_size_mb():.1f} MB", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    if not config.RAG_VECTOR_ENABLED:
        print("RAG_VECTOR_ENABLED=0，向量索引已关闭，无需建库。")
        print("如需建库：把 backend/.env 里的 RAG_VECTOR_ENABLED 改成 1，或先删掉那一行。")
        sys.exit(0)
    if not embeddings.available():
        print("未配置 EMBED_API_KEY / ARK_API_KEY，无法向量化。请先在 backend/.env 里填好。")
        sys.exit(1)

    # 坑：索引目录被删掉、但 manifest（记录"哪些文件已索引"）还在时，
    # 增量同步会认为"全都建过了"，结果建出一个空索引（实测踩过）。
    # 所以索引目录不存在就把 manifest 一并清掉，强制按资料目录重建。
    manifest = INDEX_DIR.parent / (INDEX_DIR.name + ".manifest.json")
    if not INDEX_DIR.exists() and manifest.exists():
        print(f"[修正] 索引目录不存在但清单还在，已删除清单 {manifest.name}，将全量重建")
        manifest.unlink()

    print(f"资料目录：{config.KNOWLEDGE_BASE_DIR}")
    print(f"索引目录：{INDEX_DIR}")
    print(f"向量服务：{config.EMBED_MODEL} @ {config.EMBED_BASE_URL}")
    print(f"批间隔 {config.EMBED_DELAY_SECONDS}s / 批大小 {config.EMBED_BATCH} / "
          f"重试 {config.EMBED_RETRIES} 次")

    threading.Thread(target=monitor, daemon=True).start()
    t0 = time.time()
    try:
        vector_store.ensure_ready()
    finally:
        _done = True
    print(f"[完成] 总耗时 {int(time.time() - t0)}s，索引目录 {index_size_mb():.1f} MB")
