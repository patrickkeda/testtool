import json
from pathlib import Path
import sys

# 允许从仓库根目录运行脚本：把 `TestTool/` 加到 sys.path，导入 `src.*`
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "TestTool"))

from src.testcases.context import Context  # noqa: E402
from src.testcases.base import StepResult  # noqa: E402
from src.testcases.steps.cases.create_device_json import CreateDeviceJsonStep  # noqa: E402


def main() -> int:
    # 固定输入，复现 Step6 -> Step7 数据链路
    sn = "8010003AHQ26AEA0100"
    x5 = "0x3281325c0411521501b30ea700120040"
    s100 = "06484316339235d2101807130000207d"

    ctx = Context(port="PortA")
    ctx.set_sn(sn)

    step7 = CreateDeviceJsonStep(step_id="step_7", step_name="CreateDeviceJson", timeout=30, retries=0, on_failure="fail")

    out_dir = Path("TestTool") / "Result" / "upload"
    out_path = out_dir / sn / "device.json"
    if out_path.exists():
        out_path.unlink()

    # 情况1：不写入 step_6 结果 -> 预期 UNKNOWN
    r1 = step7.run(ctx, {"step_6_id": "step_6", "output_dir": str(out_dir)})
    print("case1 passed:", r1.passed, "file:", out_path.exists())
    if out_path.exists():
        print(out_path.read_text(encoding="utf-8"))

    # 清理输出
    if out_path.exists():
        out_path.unlink()

    # 情况2：写入 step_6 结果 -> 预期提取成功
    ctx.set_result("step_6", StepResult(passed=True, data={"x5": x5, "s100": s100}, message="mock step6"))
    r2 = step7.run(ctx, {"step_6_id": "step_6", "output_dir": str(out_dir)})
    print("case2 passed:", r2.passed, "file:", out_path.exists())
    if out_path.exists():
        print(out_path.read_text(encoding="utf-8"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

