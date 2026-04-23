"""
从 Seq/*.yaml 生成 PVT 测试项 Excel（测试名称、测试时间、测试内容、测试命令）。
engineer.test 步骤的说明参照 test/工程模式测试用例_数据表_AT命令 (1).csv。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
SEQ_DIR = ROOT / "Seq"
CSV_PATH = ROOT / "test" / "工程模式测试用例_数据表_AT命令 (1).csv"
OUT_DIR = ROOT / "test" / "pvt"

SEQ_FILES = [
    "vita-fcts100.yaml",
    "vita-fctx5.yaml",
    "vita-servo-id1.yaml",
    "vita-servo-id2.yaml",
    "vita01-burnin-1.yaml",
    "Vita01-cal-1.yaml",
    "vita01-head.yaml",
    "vita01-head1.yaml",
    "vita01-headmodel.yaml",
    "vita01-machine-0.yaml",
    "vita01-machine-1.yaml",
    "Vita01-motor-1.yaml",
    "Vita01-motorcal-1.yaml",
    "vita01-uwb-1.yaml",
]


def _norm_cmd_key(token: str) -> str:
    return token.strip().lower()


def _spec_key(spec: str) -> str | None:
    s = spec.strip().strip('"').strip("“”")
    if not s or s.startswith("#"):
        return None
    if "=" in s:
        return _norm_cmd_key(s.split("=", 1)[0])
    return None


def load_engineer_reference(path: Path) -> dict[str, tuple[str, str]]:
    """指令前缀 -> (名称, 说明)"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    col_spec = df.columns[0]
    col_name = df.columns[1]
    col_desc = df.columns[2]
    out: dict[str, tuple[str, str]] = {}
    for _, row in df.iterrows():
        spec = row.get(col_spec)
        if pd.isna(spec):
            continue
        key = _spec_key(str(spec))
        if not key:
            continue
        name = "" if pd.isna(row.get(col_name)) else str(row.get(col_name)).strip()
        desc = "" if pd.isna(row.get(col_desc)) else str(row.get(col_desc)).strip()
        if key not in out:
            out[key] = (name, desc)
    return out


def actual_cmd_key(command: str) -> str | None:
    c = command.strip()
    if not c:
        return None
    if "=" in c:
        return _norm_cmd_key(c.split("=", 1)[0])
    if "%" in c:
        return _norm_cmd_key(c.split("%", 1)[0])
    return _norm_cmd_key(c)


def format_timeout(step: dict) -> str:
    t = step.get("timeout")
    if t is None:
        return ""
    try:
        n = int(t)
    except (TypeError, ValueError):
        return str(t)
    if n >= 1000 and n % 1000 == 0:
        return f"{n // 1000}s ({n}ms)"
    return f"{n}ms"


def build_test_content(step_type: str, params: dict, ref: dict[str, tuple[str, str]]) -> str:
    if step_type != "engineer.test":
        parts = []
        if params.get("description"):
            parts.append(str(params["description"]))
        if params.get("title") and params.get("message"):
            parts.append(f"{params['title']}: {params['message']}")
        elif params.get("message"):
            parts.append(str(params["message"]))
        if not parts and params:
            parts.append(json.dumps(params, ensure_ascii=False))
        elif not parts:
            parts.append(step_type)
        return "\n".join(parts)

    cmd = params.get("command") or ""
    tc = params.get("test_case")
    if not cmd and tc:
        cmd = str(tc)
    key = actual_cmd_key(cmd) if cmd else None
    pair = ref.get(key) if key else None
    if pair:
        name, desc = pair
        body = []
        if name:
            body.append(name)
        if desc:
            body.append(desc)
        return "\n".join(body) if body else cmd or "(工程模式)"
    return cmd or "(工程模式，CSV 无匹配说明)"


def build_test_command(step_type: str, params: dict) -> str:
    if step_type == "engineer.test":
        cmd = params.get("command")
        if cmd:
            return str(cmd)
        if params.get("test_case"):
            return f"test_case={params['test_case']}"
        return "engineer.test"
    if not params:
        return step_type
    try:
        return f"{step_type} {json.dumps(params, ensure_ascii=False)}"
    except (TypeError, ValueError):
        return f"{step_type} {params!r}"


def steps_from_yaml(data: dict) -> list[dict]:
    steps = data.get("steps")
    if not isinstance(steps, list):
        return []
    return [s for s in steps if isinstance(s, dict)]


def export_one(yaml_path: Path, ref: dict[str, tuple[str, str]], out_dir: Path) -> Path:
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    meta = data.get("metadata") or {}
    seq_name = meta.get("name", yaml_path.stem)
    seq_desc = meta.get("description", "")
    created = meta.get("created_at", "")

    rows = []
    for step in steps_from_yaml(data):
        stype = step.get("type") or ""
        name = step.get("name") or step.get("id") or ""
        params = step.get("params") or {}
        if not isinstance(params, dict):
            params = {"_raw": params}
        rows.append(
            {
                "测试名称": name,
                "测试时间": format_timeout(step),
                "测试内容": build_test_content(stype, params, ref),
                "测试命令": build_test_command(stype, params),
            }
        )

    df = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{yaml_path.stem}_PVT.xlsx"

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        info = pd.DataFrame(
            [
                ["序列标识", seq_name],
                ["序列说明", seq_desc],
                ["序列创建时间(元数据)", created],
                ["源文件", str(yaml_path.name)],
            ],
            columns=["字段", "值"],
        )
        info.to_excel(writer, sheet_name="序列信息", index=False)
        df.to_excel(writer, sheet_name="测试步骤", index=False)

    return out_path


def main() -> None:
    ref = load_engineer_reference(CSV_PATH)
    written = []
    for name in SEQ_FILES:
        path = SEQ_DIR / name
        if not path.is_file():
            alt = SEQ_DIR / name.lower()
            if alt.is_file():
                path = alt
            else:
                raise FileNotFoundError(f"序列文件不存在: {SEQ_DIR / name}")
        written.append(export_one(path, ref, OUT_DIR))
    for p in written:
        print(p)


if __name__ == "__main__":
    main()
