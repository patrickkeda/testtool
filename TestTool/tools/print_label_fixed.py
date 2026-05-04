from __future__ import annotations

import argparse
from pathlib import Path
import yaml

from src.testcases.steps.cases.zebra_printer import ZebraPrintStep


def _load_printer_config(project_root: Path) -> dict:
    config_path = project_root / "Config" / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    printer = data.get("printer", {})
    return printer if isinstance(printer, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fixed single-path Zebra label print")
    parser.add_argument("--imei", required=True, help="IMEI text")
    parser.add_argument("--scramble", required=True, help="Scramble text")
    parser.add_argument(
        "--printer-name",
        default="ZDesigner 110Xi4 600 dpi (副本 1)",
        help="Windows printer queue name",
    )
    parser.add_argument("--copies", type=int, default=1, help="Print copies")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    imei_font = project_root / "Result" / "font_sources" / "vbot_zip" / "Vbot Sans" / "Vbot Sans-Regular.ttf"
    scramble_font = project_root / "Result" / "font_sources" / "许可标志样式矢量图及字体库" / "HYCuSong-CAICT.ttf"

    if not imei_font.exists():
        raise FileNotFoundError(f"IMEI font not found: {imei_font}")
    if not scramble_font.exists():
        raise FileNotFoundError(f"Scramble font not found: {scramble_font}")

    cfg = _load_printer_config(project_root)
    hardlock_zpl = str(cfg.get("hardlock_zpl", "^XA^PW2457^LL732^LH0,0^LT0^LS0^PR3,3~SD15^XZ"))

    step = ZebraPrintStep("fixed_print", "fixed_print")
    zpl = step._build_fixed_fields_image_zpl(
        imei=args.imei,
        scramble=args.scramble,
        params={
            "imei_font_source": str(imei_font),
            "scramble_font_source": str(scramble_font),
            "hardlock_enabled": bool(cfg.get("hardlock_enabled", True)),
            "hardlock_zpl": hardlock_zpl,
            "image_imei_x_px": int(cfg.get("image_imei_x_px", 439)),
            "image_imei_y_px": int(cfg.get("image_imei_y_px", 611)),
            "image_scramble_x_px": int(cfg.get("image_scramble_x_px", 1616)),
            "image_scramble_y_px": int(cfg.get("image_scramble_y_px", 557)),
            "image_imei_font_px": int(cfg.get("image_imei_font_px", 43)),
            "image_scramble_font_px": int(cfg.get("image_scramble_font_px", 67)),
            "image_threshold": int(cfg.get("image_threshold", 175)),
        },
    )
    payload = zpl.encode("utf-8", errors="replace")
    ZebraPrintStep._send_via_local_printer(args.printer_name, max(1, int(args.copies)), payload)
    print(f"PRINT_OK_FIXED imei={args.imei} scramble={args.scramble} bytes={len(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
