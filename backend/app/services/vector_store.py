# 【RAG】zvec 向量库：建库、增量同步、混合检索
#
# zvec 是阿里开源的【进程内】向量数据库：没有服务端、没有守护进程，
# 就是一个目录 + 一个 Python 包（实测 win/cp312 whl 只有 11.4 MB，只依赖 numpy）。
#
# 它同时提供两种索引，本模块两种都用上：
#   - FTS 索引：jieba 中文分词 + BM25 排序（比原来"2 字滑窗数命中"强得多）
#   - 向量索引：HNSW + COSINE 距离（解决同义词/近义表述，关键词永远搜不到）
#
# 两个必须记住的坑：
#   1. COSINE 返回的是【距离，越小越相似】；BM25 是【越大越相关】。方向相反。
#   2. 单个 Query 不能同时设 fts 和 vector，只能分两路查再自己融合。
#
# 增量同步：靠 backend/data/zvec_kb.manifest.json 记每个文件的 sha1，
# 只有变过的文件才重新切块+向量化；manifest 只在全部成功后才落盘，
# 所以中途崩了下次会自动重做，天然幂等。

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import quote

from ..core import config
from . import chunker, coreference, embeddings

try:                                   # zvec 没装也要能跑：降级到关键词检索
    import zvec
    from zvec.model.param.query import Fts
    _ZVEC_OK = True
except Exception as _exc:              # noqa: BLE001
    zvec = None
    Fts = None
    _ZVEC_OK = False
    _IMPORT_ERROR = str(_exc)
else:
    _IMPORT_ERROR = ""

_KB_SUFFIXES = (".md", ".txt")

# 写操作和查询都过这把锁。zvec 的文档只承诺 embedding function 线程安全，
# 没说 collection 句柄可以并发查；这个后端并发量很小，串行化的代价可以忽略。
_lock = threading.RLock()
_col = None
_ready = False
_dim = 0
_last_error = ""
_last_sync = {}          # {文件数, 块数, 重建块数, 耗时}
_initialized = False     # zvec.init 只允许在启动时调一次


# ======== 路径 ========

def _manifest_path() -> Path:
    """清单放在集合目录【外面】——集合目录里的杂项文件可能干扰 zvec 存储层"""
    return config.VECTOR_DIR.parent / (config.VECTOR_DIR.name + ".manifest.json")


def _dim_path() -> Path:
    return config.VECTOR_DIR.parent / (config.VECTOR_DIR.name + ".dim.json")


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ======== 集合 ========

def _schema(dim: int):
    return zvec.CollectionSchema(
        name=config.COLLECTION_NAME,
        fields=[
            zvec.FieldSchema("doc_title", zvec.DataType.STRING,
                             index_param=zvec.InvertIndexParam()),
            zvec.FieldSchema("heading", zvec.DataType.STRING),
            zvec.FieldSchema("source_path", zvec.DataType.STRING,
                             index_param=zvec.InvertIndexParam()),
            zvec.FieldSchema("chunk_no", zvec.DataType.INT32),
            # FTS 列必须在建集合时定好：schema evolution 不支持事后增删 FTS 列
            zvec.FieldSchema("content", zvec.DataType.STRING,
                             index_param=zvec.FtsIndexParam(tokenizer_name="jieba",
                                                            filters=["lowercase"])),
        ],
        vectors=[
            zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, dimension=dim,
                              index_param=zvec.HnswIndexParam(metric_type=zvec.MetricType.COSINE)),
        ],
    )


def _reset_disk(reason: str) -> None:
    """销毁索引目录。维度变了就只能重建——集合的维度是建库时写死的。"""
    print(f"[向量库] 重建索引：{reason}")
    shutil.rmtree(config.VECTOR_DIR, ignore_errors=True)
    _manifest_path().unlink(missing_ok=True)
    _dim_path().unlink(missing_ok=True)


def _open_or_create(dim: int):
    saved = _load_json(_dim_path(), {})
    if config.VECTOR_DIR.exists() and saved.get("dim") != dim:
        _reset_disk(f"维度变化 {saved.get('dim')} → {dim}")

    config.VECTOR_DIR.parent.mkdir(parents=True, exist_ok=True)
    if config.VECTOR_DIR.exists():
        col = zvec.open(path=str(config.VECTOR_DIR))
    else:
        col = zvec.create_and_open(path=str(config.VECTOR_DIR), schema=_schema(dim))
    _save_json(_dim_path(), {"dim": dim, "model": config.ARK_EMBED_MODEL})
    return col


# ======== 增量同步 ========

def _scan_files() -> dict:
    """知识库文件 → {相对路径: {"sha1","size"}}"""
    root = Path(config.KNOWLEDGE_BASE_DIR)
    if not root.exists():
        return {}
    found = {}
    for path in sorted(root.glob("**/*")):
        if not path.is_file() or path.suffix.lower() not in _KB_SUFFIXES:
            continue
        if path.name.upper() == "README.MD":      # 目录说明不是知识
            continue
        data = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        found[rel] = {"sha1": hashlib.sha1(data).hexdigest(), "size": len(data)}
    return found


def _doc_id(rel_path: str, chunk_no: int) -> str:
    return f"{rel_path}#{chunk_no:04d}"


def _filter_source(rel_path: str) -> str:
    """过滤表达式里的单引号要写两遍，否则路径里有引号就把语法弄坏了"""
    return "source_path = '" + rel_path.replace("'", "''") + "'"


def _delete_source(col, rel_path: str) -> None:
    try:
        col.delete_by_filter(filter=_filter_source(rel_path))
    except Exception:            # noqa: BLE001 —— 文件本来就没入过库时会报错，无所谓
        pass


def _build_docs(rel_path: str, chunks: list, vectors: list) -> list:
    stem = Path(rel_path).stem
    title = coreference.normalize_title(stem)     # 与指代消解共用同一套命名规则
    docs = []
    for chunk, vector in zip(chunks, vectors):
        docs.append(zvec.Doc(
            id=_doc_id(rel_path, chunk["chunk_no"]),
            vectors={"embedding": vector},
            fields={
                "doc_title": title,
                "heading": chunk["heading"],
                "source_path": rel_path,
                "chunk_no": chunk["chunk_no"],
                "content": chunk["content"],
            },
        ))
    return docs


def _open_with_retry(dim: int, attempts: int = 3, delay: float = 0.8):
    """打开/创建集合，遇到"别人还占着锁"就等一会儿重试。

    为什么需要：`uvicorn --reload` 改代码会自动重启子进程，旧进程可能
    还没来得及释放 LOCK，新进程就起来了。实测会报
    "Can't lock read-write collection"。不重试的话，一次普通的代码修改
    就会让检索掉回关键词模式，很误导人。
    """
    last = None
    for attempt in range(attempts):
        try:
            return _open_or_create(dim)
        except Exception as exc:        # noqa: BLE001
            last = exc
            if "lock" not in str(exc).lower() or attempt == attempts - 1:
                raise
            print(f"[向量库] 索引被占用，{delay}s 后重试（{attempt + 1}/{attempts}）")
            time.sleep(delay)
    raise last


def _sync(col) -> dict:
    """把知识库同步进索引，只处理变过的文件"""
    files = _scan_files()
    manifest = _load_json(_manifest_path(), {})

    removed = [rel for rel in manifest if rel not in files]
    changed = [rel for rel in files if manifest.get(rel, {}).get("sha1") != files[rel]["sha1"]]

    for rel in removed:
        _delete_source(col, rel)

    pending = []            # [(rel, chunks)]
    for rel in changed:
        _delete_source(col, rel)
        chunks = chunker.split_file(Path(config.KNOWLEDGE_BASE_DIR) / rel)
        if chunks:
            pending.append((rel, chunks))

    inserted = 0
    if pending:
        flat = [c["content"] for _, chunks in pending for c in chunks]
        vectors = embeddings.embed_documents(flat)      # 网络调用，批量做
        offset = 0
        for rel, chunks in pending:
            piece = vectors[offset: offset + len(chunks)]
            offset += len(chunks)
            col.insert(_build_docs(rel, chunks, piece))
            inserted += len(chunks)
        col.optimize()                                  # 新插入的向量要走索引才搜得快

    # P1：全部成功后才更新清单
    new_manifest = {rel: files[rel] for rel in files}
    _save_json(_manifest_path(), new_manifest)
    return {"files": len(files), "removed": len(removed),
            "rebuilt": len(changed), "chunks": inserted}


# ======== 对外：初始化 ========

def ensure_ready(force: bool = False) -> bool:
    """启动时调用一次：初始化 zvec、按需建库、增量同步。失败不抛异常，只降级。"""
    global _col, _ready, _dim, _last_error, _last_sync, _initialized

    with _lock:
        if _ready and not force:
            return True
        _ready = False
        _last_error = ""

        if not config.RAG_VECTOR_ENABLED:
            _last_error = "RAG_VECTOR_ENABLED=0"
            print("[向量库] 已按配置关闭 → 检索退回关键词模式")
            return False
        if not _ZVEC_OK:
            _last_error = f"zvec 未安装：{_IMPORT_ERROR}"
            print("[向量库] " + _last_error + " → 检索退回关键词模式")
            return False
        if not embeddings.available():
            _last_error = "未配置 ARK_API_KEY"
            print("[向量库] " + _last_error + " → 检索退回关键词模式")
            return False

        try:
            if not _initialized:
                try:
                    zvec.init(log_level=zvec.LogLevel.WARN)
                except Exception:       # noqa: BLE001 —— init 可选，失败不影响使用
                    pass
                _initialized = True

            dim = embeddings.dimension()           # 实测维度，不靠猜

            # 同一个进程里对同一路径再 open 一次会撞 LOCK（实测报
            # "Can't lock read-write collection"），所以句柄复用：
            #   - 已经有句柄且维度没变 → 直接复用，只重新同步文件
            #   - 维度变了 → 不能原地换向量维度，必须重启服务重建
            if _col is not None:
                if dim != _dim:
                    _last_error = (f"向量维度从 {_dim} 变成 {dim}，"
                                   "需要重启服务以重建索引")
                    print("[向量库] " + _last_error + " → 暂时退回关键词模式")
                    return False
                col = _col
            else:
                col = _open_with_retry(dim)

            _dim = dim
            _col = col
            _last_sync = _sync(_col)
            _ready = True
            print("[向量库] 就绪 dim={} 文件={} 本次变更={} 新增块={}"
                  .format(_dim, _last_sync["files"], _last_sync["rebuilt"], _last_sync["chunks"]))
            return True
        except Exception as exc:        # noqa: BLE001 —— 任何失败都只降级
            _last_error = f"{type(exc).__name__}: {exc}"
            _col = None
            print("[向量库] 初始化失败：" + _last_error + " → 检索退回关键词模式")
            return False


def available() -> bool:
    return _ready and _col is not None


def stats() -> dict:
    return {
        "ready": _ready,
        "dim": _dim,
        "collection": config.COLLECTION_NAME,
        "dir": str(config.VECTOR_DIR),
        "last_sync": _last_sync,
        "error": _last_error,
    }


# ======== 对外：检索 ========

def _fields(doc) -> dict:
    return doc.fields or {}


def _url(rel_path: str) -> str:
    return config.KB_URL_PREFIX + quote(rel_path, safe="/")


def search(question: str, topk: int = None) -> list:
    """混合检索：向量距离当闸门，FTS 参与排序。

    为什么用"向量距离"当闸门而不是关键词命中：实测「博物馆开放时间」这句话
    会命中《越王勾践剑》—— 因为文档里出现了"博物馆"三个字。
    关键词永远治不了这种假阳性，但向量距离能：问的是开放时间，
    和"青铜剑的年代"语义很远，距离会很大，直接就被挡掉。

    返回 [{"title","content","heading","path","url","score","distance"}]
    """
    if not available():
        return []

    topk = topk or config.TOP_K
    vector = embeddings.embed_query(question)          # 网络调用放在锁外

    with _lock:
        col = _col
        if col is None:
            return []

        # 1) 向量路：拿到每个候选的【距离】
        dense = col.query(queries=zvec.Query(field_name="embedding", vector=vector),
                          topk=max(config.DENSE_CANDIDATES, topk),
                          include_vector=False)
        candidates = {}
        for doc in dense:
            candidates[doc.id] = {"distance": float(doc.score), "fields": _fields(doc)}

        # 2) 关键词路：只用来改进排序，不单独放行
        fts_ids = []
        try:
            fts = col.query(queries=zvec.Query(field_name="content",
                                               fts=Fts(match_string=question)),
                            topk=config.FTS_CANDIDATES, include_vector=False)
            fts_ids = [doc.id for doc in fts]
        except Exception as exc:        # noqa: BLE001 —— FTS 挂了不影响向量路
            print("[向量库] FTS 查询失败（忽略）：", exc)

        # 3) 闸门：距离超标的一律出局；但观众点名提到的文物无条件放行
        mentioned = set(coreference.find_entities(question)) if config.DENSE_ENTITY_BOOST else set()

        def _passes(doc_id: str) -> bool:
            info = candidates[doc_id]
            if info["distance"] <= config.DENSE_MAX_DISTANCE:
                return True
            return bool(mentioned) and (info["fields"].get("doc_title") or "") in mentioned

        passing = [doc_id for doc_id in candidates if _passes(doc_id)]
        if not passing:
            return []

        # 4) RRF 融合（两路名次取倒数和，谁的排名靠前谁加分）
        passing.sort(key=lambda doc_id: candidates[doc_id]["distance"])
        fused = {}
        for rank, doc_id in enumerate(passing):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (config.RRF_RANK_CONSTANT + rank + 1)
        for rank, doc_id in enumerate(fts_ids):
            if doc_id in fused:
                fused[doc_id] += 1.0 / (config.RRF_RANK_CONSTANT + rank + 1)

        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)

        # 5) 同一篇文档只保留得分最高的那段，避免一篇资料占满 3 个名额
        results, seen = [], set()
        for doc_id, score in ranked:
            fields = candidates[doc_id]["fields"]
            title = fields.get("doc_title") or ""
            if not title or title in seen:
                continue
            seen.add(title)
            results.append({
                "title": title,
                "heading": fields.get("heading") or "",
                "content": fields.get("content") or "",
                "path": fields.get("source_path") or "",
                "url": _url(fields.get("source_path") or ""),
                "score": round(score, 6),
                "distance": round(candidates[doc_id]["distance"], 4),
            })
            if len(results) >= topk:
                break
        return results
