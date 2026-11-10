"""迁移执行器（V0.2）：按文件名顺序执行 storage/migrations/*.sql，幂等。

用法：
    python -m zhiying.storage.migrate
"""

from __future__ import annotations

import argparse
from pathlib import Path

from zhiying.kb import db_conn_kwargs

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run(database: str | None = None) -> int:
    import psycopg

    kw = db_conn_kwargs()
    if database:
        kw["dbname"] = database
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("无迁移文件")
        return 0
    with psycopg.connect(**kw) as conn:
        with conn.cursor() as cur:
            for f in files:
                sql = f.read_text(encoding="utf-8")
                cur.execute(sql)
                print(f"✅ {f.name}")
        conn.commit()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="zhiying.migrate", description="执行数据库迁移")
    ap.add_argument("--database", default=None)
    args = ap.parse_args(argv)
    from zhiying.console import setup_console

    setup_console()
    try:
        return run(args.database)
    except Exception as e:  # noqa: BLE001
        print(f"❌ 迁移失败: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
