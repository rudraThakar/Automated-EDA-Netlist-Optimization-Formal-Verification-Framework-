from __future__ import annotations

import json
import os
import time
from typing import Any


def now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_path(path: str) -> str:
    return os.path.normpath(path.strip())
