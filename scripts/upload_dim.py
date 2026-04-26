"""일회성 dim 테이블 업로드 — 노트북에서 생성한 parquet 파일을 Supabase에 적재.

실행 방법:
  python scripts/upload_dim.py --mapping data/dim/stdg_admm_mapping_202503.parquet
"""
import argparse
from pathlib import Path

import pandas as pd

from database.supabase_client import get_client


def upload_mapping(parquet_path: Path) -> None:
    """stdg_admm_mapping parquet → Supabase stdg_admm_mapping 테이블."""
    # TODO: implement
    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, required=True)
    args = parser.parse_args()
    upload_mapping(args.mapping)
