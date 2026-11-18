"""B6 契约预置：幂等建库脚本（PRD DR-6，schema_v1.sql）。

用法：
    python -m zhiying.storage.init_db --database zhiying --user postgres [--password ***] [--host localhost] [--port 5432]

只建结构与契约（schema_v1.sql），不写业务数据；可重复执行。
连接参数优先级：命令行 > 环境变量 > 默认值。
环境变量支持两套命名（前者优先，与 gewu 对齐）：
    ZHIYING_DB_HOST / ZHIYING_DB_PORT / ZHIYING_DB_USER / ZHIYING_DB_PASSWORD
    ZHIYING_PG_HOST / ZHIYING_PG_PORT / ZHIYING_PG_USER / ZHIYING_PG_PASSWORD
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema_v1.sql"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _connect_kwargs(args: argparse.Namespace) -> dict:
    import os

    from zhiying.envkeys import getenv

    return dict(
        host=args.host or os.environ.get("ZHIYING_DB_HOST") or os.environ.get("ZHIYING_PG_HOST", "localhost"),
        port=args.port or int(os.environ.get("ZHIYING_DB_PORT") or os.environ.get("ZHIYING_PG_PORT", "5432")),
        user=args.user or os.environ.get("ZHIYING_DB_USER") or os.environ.get("ZHIYING_PG_USER", "postgres"),
        password=args.password or getenv("ZHIYING_DB_PASSWORD") or getenv("ZHIYING_PG_PASSWORD") or getenv("PGPASSWORD"),
        dbname="postgres",  # 先连默认库，再建目标库
    )


def _ensure_database(conn_kwargs: dict, database: str) -> None:
    import psycopg

    # AUTOCOMMIT：CREATE DATABASE 不能在事务内
    with psycopg.connect(**conn_kwargs, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{database}"')
            print(f"✅ 已创建数据库 {database}")
        else:
            print(f"ℹ 数据库 {database} 已存在")


def apply_schema(conn_kwargs: dict, database: str) -> None:
    import psycopg

    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    kw = dict(conn_kwargs)
    kw["dbname"] = database
    with psycopg.connect(**kw) as conn:
        conn.execute(sql)
        conn.commit()
    print(f"✅ schema_v1 已应用于 {database}（幂等）")


def apply_migrations(conn_kwargs: dict, database: str) -> list[str]:
    """依次应用 migrations/*.sql（幂等，全用 IF NOT EXISTS）；返回已应用文件名。"""
    import psycopg

    applied: list[str] = []
    if not MIGRATIONS_DIR.is_dir():
        return applied
    kw = dict(conn_kwargs)
    kw["dbname"] = database
    with psycopg.connect(**kw) as conn:
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            conn.execute(sql_file.read_text(encoding="utf-8"))
            applied.append(sql_file.name)
        conn.commit()
    if applied:
        print(f"✅ migrations 已应用: {', '.join(applied)}（幂等）")
    return applied


def verify(conn_kwargs: dict, database: str) -> bool:
    import psycopg

    kw = dict(conn_kwargs)
    kw["dbname"] = database
    with psycopg.connect(**kw) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1"
        ).fetchall()
        tables = [r[0] for r in rows]
        print("表清单:", tables)
        need = {"videos", "segments", "chunks"}
        ok = need.issubset(set(tables))
        # migrations 关键列核验（003 content_hash，DR-23 去重依赖）
        col = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='videos' AND column_name='content_hash'"
        ).fetchone()
        print("videos.content_hash:", "✅" if col else "❌ 缺失（migrations 未生效）")
        ok = ok and bool(col)
        # vector 维度核验
        dim = conn.execute(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid='chunks'::regclass AND attname='embedding'"
        ).fetchone()
        print("embedding typmod:", dim[0] if dim else None)
        return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="zhiying.init_db", description="知映 B6 契约预置：幂等建库")
    ap.add_argument("--database", default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", default=None)
    ap.add_argument("--user", default=None)
    ap.add_argument("--password", default=None)
    args = ap.parse_args(argv)

    from zhiying.console import setup_console

    setup_console()
    if args.database is None:
        import os

        args.database = os.environ.get("ZHIYING_DB_NAME", "zhiying")
    try:
        kw = _connect_kwargs(args)
        _ensure_database(kw, args.database)
        apply_schema(kw, args.database)
        apply_migrations(kw, args.database)
        ok = verify(kw, args.database)
        print("✅ B6 契约预置完成" if ok else "❌ 表缺失，请检查 schema 输出")
        return 0 if ok else 1
    except Exception as e:  # noqa: BLE001
        print(f"❌ 建库失败: {e}")
        print("  └─ 检查 PG 服务、认证方式与 ZHIYING_DB_PASSWORD 环境变量")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
