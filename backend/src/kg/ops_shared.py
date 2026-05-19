"""共用唯讀 ops infra — uid 解析 / DB 定位 / 唯讀連線 / 表格輸出 / 欄位探測。

三套 ops 工具(`backend/ops_cli.py`、`backend/ops_analyze.py`、
`ops/data_inspect.py`)共用,杜絕各自複製貼上的 db 定位與輸出邏輯。

純 stdlib,無 app / FastAPI 相依 —— 容器內與 repo root 皆可 import。
本 module 內所有操作一律唯讀:不 ALTER、不 INSERT、不寫入。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

# 每種 notebook-scoped 資料檔的 (template, legacy_name)。template 的 {nb}
# 代換為 notebook id;legacy_name 為 notebook 化之前的舊檔名(None 表無 legacy)。
# 此處是 ops 工具與 app(service_factories._resolve_notebook_paths)共用的
# 檔名單一真相 —— 杜絕 ops 讀錯檔名(如已失效的 graph.json)。
NOTEBOOK_FILE_SPECS: dict[str, tuple[str, str | None]] = {
    "graph": ("graph_{nb}.json", "graph.json"),
    "candidates": ("candidates_{nb}.json", "candidates.json"),
    "blocked": ("blocked_{nb}.json", "blocked.json"),
    "pending_judge": ("pending_judge_{nb}.json", None),
    "embeddings": ("embeddings_{nb}.npy", "embeddings.npy"),
    "card_ids": ("card_ids_{nb}.json", "card_ids.json"),
}


def data_dir() -> Path:
    """KG 資料根目錄。尊重 KG_DATA_DIR,預設 backend/data。每次呼叫重讀 env。"""
    default = Path(__file__).resolve().parent.parent.parent / "data"
    return Path(os.getenv("KG_DATA_DIR", str(default)))


def resolve_uid(partial: str, data_dir: str | Path) -> str:
    """部分 ID 模糊匹配 —— 支援前綴或子字串。

    精確匹配優先;唯一模糊匹配則回傳之;多重匹配印出候選後 exit(1);
    無匹配則原樣回傳(讓後續步驟自行報錯)。
    """
    users_dir = Path(data_dir) / "users"
    if not users_dir.exists():
        return partial
    if (users_dir / partial).exists():
        return partial
    matches = [d.name for d in users_dir.iterdir() if d.is_dir() and partial in d.name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"多個用戶匹配 {partial!r}：", file=sys.stderr)
        for m in matches:
            print(f"  {m}", file=sys.stderr)
        sys.exit(1)
    return partial


def connect_ro(db_path: str | Path) -> sqlite3.Connection:
    """開啟嚴格唯讀的 SQLite 連線。檔案不存在則 raise FileNotFoundError。

    以 `file:...?mode=ro` URI 開啟 —— 任何寫入(INSERT/UPDATE/ALTER)會被
    SQLite 以 readonly error 拒絕,確保 ops 工具不可能改動 production 資料。
    """
    p = Path(db_path)
    if not p.exists():
        raise FileNotFoundError(f"DB not found: {p}")
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """回傳表的欄位名集合。用於探測 legacy DB 是否缺 provider/model 等欄。"""
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def notebook_files(user_dir: str | Path, nb: str = "default") -> dict[str, Path]:
    """回傳 {kind: Path} —— 某 notebook 的所有 data 檔的正規 per-notebook 路徑。

    `default` notebook 的 graph 檔即 `graph_default.json`(非 legacy `graph.json`)。
    """
    ud = Path(user_dir)
    return {kind: ud / tmpl.format(nb=nb) for kind, (tmpl, _) in NOTEBOOK_FILE_SPECS.items()}


def print_table(headers: list[str], rows: list[list]) -> None:
    """格式化輸出對齊表格。空 rows 印 "(no data)"。"""
    if not rows:
        print("(no data)")
        return
    str_rows = [[str(v) for v in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in str_rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in str_rows:
        print(fmt.format(*row))


def emit_json(obj) -> None:
    """以可解析的 JSON 印出物件(供 --json 模式),Path 等以 str 序列化。"""
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
