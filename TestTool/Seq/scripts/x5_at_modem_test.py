#!/usr/bin/env python3
"""
海外版 X5 模组 AT 测试：经 S100 跳板 SSH 到 X5，对串口发送 AT 并判定结果。

对应手动流程（minicom）正常样例：
  4G   (/dev/ttyUSB2): AT+CSQ / AT+CPIN(可 ERROR) / AT+CREG? / AT+COPS?
  GNSS (/dev/ttyUSB3): AT+CGMM / AT+CGMR / AT+CGPS=1 / AT+CGPS? / AT+CGPSINFO
                       （CGPSINFO 为空 ,,,,,,,, 也算通路正常）

本脚本不依赖交互式 minicom 发 AT（直接读写 /dev/ttyUSBx）。
远端优先用 **纯 shell（stty）** 发 AT，**不要求 X5 安装 Python**；
若 shell 不可用再回退到 python3/python。
可选把仓库内 ``Seq/tools/minicom`` 推到 X5 ``/userdata/minicom``（按需，不参与 AT）。

本机命令行示例：

  python Seq/scripts/x5_at_modem_test.py --mode 4g \\
      --jump-host 192.168.126.2 --target-host 192.168.127.10 \\
      --user root --private-key-file ~/.ssh/id_ed25519

  python Seq/scripts/x5_at_modem_test.py --mode gnss \\
      --jump-host 192.168.126.2 --target-host 192.168.127.10 \\
      --user root --private-key-file ~/.ssh/id_ed25519

TestTool 序列中由 utility.run_python_script 调用，私钥可用 ``${ssh_private_key_path}``。
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jump_ssh import JumpSSHSession  # noqa: E402


def _ensure_utf8_stdio() -> None:
    """打包子进程在中文 Windows 上常为 gbk，打印非 GBK 字符会 UnicodeEncodeError。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _detach_console_when_stdio_piped() -> None:
    if sys.platform != "win32":
        return
    try:
        out = getattr(sys, "__stdout__", None) or sys.stdout
        if out is not None and hasattr(out, "isatty") and not out.isatty():
            import ctypes

            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


def _default_minicom_local() -> Path:
    """仓库内 Seq/tools/minicom（与本脚本相对）。"""
    return Path(__file__).resolve().parent.parent / "tools" / "minicom"


def _push_minicom(sess: JumpSSHSession, *, local_path: str, remote_path: str) -> None:
    """对应手动：scp minicom → X5:/userdata/minicom && chmod +x。

    远端已存在且大小一致时跳过上传。复用已有跳板会话。
    """
    local = Path(local_path).expanduser()
    if not local.is_file():
        raise FileNotFoundError(f"本机 minicom 不存在: {local}")
    local_size = local.stat().st_size
    rc, out = sess.exec(
        f"if [ -f {remote_path} ]; then wc -c < {remote_path}; else echo MISSING; fi",
        exec_timeout=30,
    )
    _ = rc
    remote_info = (out or "").strip().splitlines()[-1].strip() if out else "MISSING"
    if remote_info.isdigit() and int(remote_info) == local_size:
        print(f"[SKIP] minicom 已存在且大小一致，跳过推送: {remote_path} ({local_size} bytes)")
        rc2, out2 = sess.exec(f"chmod +x {remote_path} && ls -l {remote_path}", exec_timeout=30)
        if rc2 == 0 and out2:
            print(out2)
        return

    print(f"推送 minicom → {remote_path} （{local}，{local_size} bytes）…")
    sess.sftp_put(local, remote_path)
    rc, out = sess.exec(f"chmod +x {remote_path} && ls -l {remote_path}", exec_timeout=30)
    if rc != 0:
        raise RuntimeError(f"chmod/ls 失败: {out}")
    print(f"[OK] minicom 已推送: {out}")


# 远端 AT：纯 shell（无 Python）。用 stty VMIN/VTIME，静默后 cat 返回。
_REMOTE_AT_SH = textwrap.dedent(
    r"""
    #!/bin/sh
    set +e
    PORT="$1"
    BAUD="$2"
    TO_INT="$3"
    CMDS="$4"
    # 禁止 glob，避免 AT+CREG? 等被展开
    set -f
    IFS="$(printf '\036')"

    if [ ! -e "$PORT" ]; then
      echo "cannot open $PORT: No such file or directory" >&2
      exit 1
    fi

    case "$TO_INT" in
      ''|*[!0-9]*) TO_INT=5 ;;
    esac
    VT=$((TO_INT * 10))
    if [ "$VT" -gt 255 ]; then VT=255; fi
    if [ "$VT" -lt 5 ]; then VT=5; fi

    stty -F "$PORT" "$BAUD" cs8 -cstopb -parenb clocal cread raw -echo -icanon 2>/dev/null \
      || stty -F "$PORT" "$BAUD" raw -echo -icanon 2>/dev/null \
      || stty -F "$PORT" raw -echo -icanon 2>/dev/null \
      || {
        echo "stty failed on $PORT" >&2
        exit 1
      }

    # 打开双向 fd，避免写/读各开一次丢字节
    exec 3<>"$PORT" || {
      echo "cannot open $PORT" >&2
      exit 1
    }

    # 排空残留
    stty -F "$PORT" min 0 time 1 2>/dev/null
    dd bs=256 count=8 <&3 >/dev/null 2>&1 || true

    stty -F "$PORT" min 0 time "$VT" 2>/dev/null

    for cmd in $CMDS; do
      [ -n "$cmd" ] || continue
      printf '>>> %s\n' "$cmd"
      printf '%s\r' "$cmd" >&3
      # 读到静默（VTIME）；外层 timeout 防止卡死
      if command -v timeout >/dev/null 2>&1; then
        timeout "$TO_INT" cat <&3 2>/dev/null
      else
        cat <&3 2>/dev/null
      fi
      printf '\n---\n'
      stty -F "$PORT" min 0 time 1 2>/dev/null
      dd bs=64 count=2 <&3 >/dev/null 2>&1 || true
      stty -F "$PORT" min 0 time "$VT" 2>/dev/null
    done

    exec 3>&-
    exit 0
    """
).lstrip()


# 远端 AT：Python 回退（仅当 shell 路径不可用时）
_REMOTE_AT_PY = textwrap.dedent(
    r"""
    import os, sys, time, select, termios

    def done(text):
        u = text.upper()
        lines = [ln.strip() for ln in u.splitlines() if ln.strip()]
        if not lines:
            return False
        last = lines[-1]
        return last == "OK" or last == "ERROR" or last.startswith("+CME ERROR") or last.startswith("+CMS ERROR")

    port = sys.argv[1]
    baud = int(sys.argv[2])
    cmd_timeout = float(sys.argv[3])
    commands = sys.argv[4].split("\x1e")

    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        bconst = getattr(termios, "B%d" % baud, termios.B115200)
        attrs[4] = attrs[5] = bconst
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)

        t_end = time.time() + 0.3
        while time.time() < t_end:
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                break
            try:
                os.read(fd, 4096)
            except OSError:
                break

        for cmd in commands:
            cmd = cmd.strip()
            if not cmd:
                continue
            print(">>> " + cmd, flush=True)
            os.write(fd, (cmd + "\r").encode("ascii", errors="ignore"))
            buf = b""
            deadline = time.time() + cmd_timeout
            while time.time() < deadline:
                r, _, _ = select.select([fd], [], [], 0.2)
                if r:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        chunk = b""
                    if chunk:
                        buf += chunk
                        if done(buf.decode("utf-8", errors="replace")):
                            break
            text = buf.decode("utf-8", errors="replace")
            if text and not text.endswith("\n"):
                text += "\n"
            print(text, end="", flush=True)
            print("---", flush=True)
            time.sleep(0.15)
    finally:
        os.close(fd)
    """
).lstrip()


def _run_at_session(
    sess: JumpSSHSession,
    *,
    port: str,
    commands: list[str],
    baud: int,
    cmd_timeout: float,
    exec_timeout: int,
) -> str:
    import base64
    import shlex

    cmds_joined = "\x1e".join(commands)
    to_int = max(1, int(cmd_timeout) if cmd_timeout >= 1 else 1)
    sh_b64 = base64.b64encode(_REMOTE_AT_SH.encode("utf-8")).decode("ascii")
    py_b64 = base64.b64encode(_REMOTE_AT_PY.encode("utf-8")).decode("ascii")

    # 优先 shell（无 Python）；失败再试 python3/python
    remote = (
        "set +e; "
        "FSH=$(mktemp /tmp/tt_at_XXXXXX.sh) || exit 1; "
        f"echo {shlex.quote(sh_b64)} | base64 -d > \"$FSH\" || {{ rm -f \"$FSH\"; exit 1; }}; "
        "chmod +x \"$FSH\"; "
        f"sh \"$FSH\" {shlex.quote(port)} {baud} {to_int} {shlex.quote(cmds_joined)}; "
        "RC=$?; rm -f \"$FSH\"; "
        "if [ \"$RC\" -eq 0 ]; then exit 0; fi; "
        "echo '[fallback] shell AT 失败，尝试 python…' >&2; "
        "PY=$(command -v python3 || command -v python); "
        "if [ -z \"$PY\" ]; then "
        "  echo 'X5 无 python3/python，且 shell AT 失败' >&2; exit \"$RC\"; "
        "fi; "
        "FPY=$(mktemp /tmp/tt_at_XXXXXX.py) || exit 1; "
        f"echo {shlex.quote(py_b64)} | base64 -d > \"$FPY\" || {{ rm -f \"$FPY\"; exit 1; }}; "
        f"\"$PY\" \"$FPY\" {shlex.quote(port)} {baud} {cmd_timeout} {shlex.quote(cmds_joined)}; "
        "RC2=$?; rm -f \"$FPY\"; exit $RC2"
    )
    rc, output = sess.exec(remote, exec_timeout=exec_timeout)
    # 与产线旧逻辑一致：仅当非零退出且无输出时失败；有 stdout 仍交给 judge_* 判定
    if rc != 0 and not output:
        raise RuntimeError(f"远端 AT 会话失败，exit={rc}")
    if "No such file or directory" in output or "cannot open" in output.lower():
        raise RuntimeError(f"无法打开串口 {port}:\n{output}")
    if "stty failed" in output:
        raise RuntimeError(f"串口 stty 配置失败 {port}:\n{output}")
    return output


def _blocks(output: str) -> dict[str, str]:
    """按 >>> CMD / --- 切分为 {CMD: response}。"""
    result: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in output.splitlines():
        if line.startswith(">>> "):
            if current is not None:
                result[current] = "\n".join(buf).strip()
            current = line[4:].strip().upper()
            buf = []
        elif line.strip() == "---":
            if current is not None:
                result[current] = "\n".join(buf).strip()
            current = None
            buf = []
        else:
            if current is not None:
                buf.append(line)
    if current is not None:
        result[current] = "\n".join(buf).strip()
    return result


def _csq_to_dbm(csq: int) -> int | None:
    if csq == 99 or csq < 0:
        return None
    return -113 + 2 * csq


def judge_4g(output: str, *, min_csq: int, min_rssi_dbm: int | None) -> bool:
    blocks = _blocks(output)
    print(output)
    ok = True

    # AT+CSQ
    csq_body = blocks.get("AT+CSQ", "")
    m = re.search(r"\+CSQ:\s*(\d+)\s*,\s*(\d+)", csq_body)
    if not m:
        print("[FAIL] AT+CSQ 无有效响应", file=sys.stderr)
        return False
    rssi, ber = int(m.group(1)), int(m.group(2))
    dbm = _csq_to_dbm(rssi)
    print(f"CSQ rssi={rssi} ber={ber} ≈ {dbm} dBm" if dbm is not None else f"CSQ rssi={rssi} ber={ber} (未知)")
    if rssi == 99:
        print("[FAIL] CSQ=99 信号不可检测", file=sys.stderr)
        ok = False
    elif min_rssi_dbm is not None:
        if dbm is None or dbm < min_rssi_dbm:
            print(f"[FAIL] 信号强度不足：{dbm} dBm < 阈值 {min_rssi_dbm} dBm", file=sys.stderr)
            ok = False
        else:
            print(f"[OK] 信号强度满足阈值 {min_rssi_dbm} dBm")
    elif rssi < min_csq:
        print(f"[FAIL] CSQ={rssi} < 阈值 {min_csq}", file=sys.stderr)
        ok = False
    else:
        print(f"[OK] CSQ={rssi} >= {min_csq}")

    # AT+CPIN：产线文档/实测多为无 '?' 写法，模组常回 ERROR，不作为失败项。
    # 是否入网以 CREG/COPS 为准（例：CREG 0,5 + COPS "CHINA MOBILE"）。
    cpin = blocks.get("AT+CPIN", "") or blocks.get("AT+CPIN?", "")
    if cpin:
        if "READY" in cpin.upper():
            print("[OK] CPIN READY")
        elif "ERROR" in cpin.upper():
            print("[WARN] AT+CPIN 返回 ERROR（与 minicom 实测一致，忽略；用 CREG/COPS 判注册）")
        else:
            print(f"[WARN] AT+CPIN 响应: {cpin!r}（忽略）")

    # AT+CREG?  → <n>,<stat>；stat 1=home, 5=roaming
    creg = blocks.get("AT+CREG?", "")
    m = re.search(r"\+CREG:\s*\d+\s*,\s*(\d+)", creg)
    if not m:
        print(f"[FAIL] CREG 无有效响应: {creg!r}", file=sys.stderr)
        ok = False
    else:
        stat = int(m.group(1))
        if stat not in (1, 5):
            print(f"[FAIL] 网络未注册 CREG stat={stat}（期望 1 或 5）", file=sys.stderr)
            ok = False
        else:
            print(f"[OK] CREG registered (stat={stat})")

    # AT+COPS?
    cops = blocks.get("AT+COPS?", "")
    m = re.search(r'\+COPS:\s*\d+\s*,\s*\d+\s*,\s*"([^"]+)"', cops)
    if not m:
        # 允许无引号数字形式，但至少要有 +COPS: 且非仅 0
        if "+COPS:" not in cops or re.search(r"\+COPS:\s*0\s*$", cops.strip()):
            print(f"[FAIL] 无运营商信息: {cops!r}", file=sys.stderr)
            ok = False
        else:
            print(f"[OK] COPS: {cops}")
    else:
        print(f"[OK] 运营商: {m.group(1)}")

    return ok


def judge_gnss(output: str, *, require_fix: bool, expect_model: str) -> bool:
    """文档全套 GNSS AT；正常截图下 CGPSINFO 为空字段也通过。

    文档命令：AT+CGMM / AT+CGMR / AT+CGPS=1 / AT+CGPS? / AT+CGPSINFO
    正常样例：CGMM=SIMCOM_SIM7600G-H；CGPSINFO: ,,,,,,,,
    """
    blocks = _blocks(output)
    print(output)
    ok = True

    cgmm = blocks.get("AT+CGMM", "")
    if not cgmm or "ERROR" in cgmm.upper():
        print(f"[FAIL] AT+CGMM 失败: {cgmm!r}", file=sys.stderr)
        ok = False
    else:
        model_lines = [
            ln.strip()
            for ln in cgmm.splitlines()
            if ln.strip() and ln.strip().upper() not in ("OK", "AT+CGMM")
        ]
        model = model_lines[0] if model_lines else ""
        print(f"[OK] CGMM: {model or cgmm}")
        if expect_model and expect_model.upper() not in (model or cgmm).upper():
            print(
                f"[FAIL] 模组型号不匹配：期望含 {expect_model!r}，实际 {model!r}",
                file=sys.stderr,
            )
            ok = False

    # 文档要求的后续命令：必须出现且不能是裸 ERROR
    for cmd, label in (
        ("AT+CGMR", "CGMR"),
        ("AT+CGPS=1", "CGPS=1"),
        ("AT+CGPS?", "CGPS?"),
    ):
        body = blocks.get(cmd, "")
        if not body:
            print(f"[FAIL] 缺少 {cmd} 响应", file=sys.stderr)
            ok = False
            continue
        # CGPS? 正常含 +CGPS:…；其它命令末行应为 OK
        if "ERROR" in body.upper() and "+CGPS:" not in body.upper():
            print(f"[FAIL] {cmd} 失败: {body!r}", file=sys.stderr)
            ok = False
        else:
            first = next((ln for ln in body.splitlines() if ln.strip()), "")
            print(f"[OK] {label}: {first or 'OK'}")

    info = blocks.get("AT+CGPSINFO", "")
    m = re.search(r"\+CGPSINFO:\s*(.*)", info, re.IGNORECASE)
    if not m or re.search(r"\bERROR\b", info, re.IGNORECASE):
        print(f"[FAIL] AT+CGPSINFO 无有效响应: {info!r}", file=sys.stderr)
        return False
    payload = m.group(1).strip()
    fields = [f.strip() for f in payload.split(",")]
    has_fix = bool(fields) and bool(fields[0]) and fields[0] not in ("", "0")
    if require_fix and not has_fix:
        print(f"[FAIL] GNSS 未定位: +CGPSINFO: {payload}", file=sys.stderr)
        ok = False
    elif has_fix:
        print(f"[OK] GNSS 已定位: {payload}")
    else:
        print(f"[OK] CGPSINFO 通路正常（未定位属正常）: +CGPSINFO: {payload}")

    return ok


def run_4g(sess: JumpSSHSession, **kwargs) -> bool:
    min_csq = kwargs.pop("min_csq")
    min_rssi_dbm = kwargs.pop("min_rssi_dbm")
    port = kwargs.pop("port")
    baud = kwargs.pop("baud")
    cmd_timeout = kwargs.pop("cmd_timeout")
    exec_timeout = kwargs.pop("exec_timeout")
    output = _run_at_session(
        sess,
        port=port,
        # 与产线 minicom 一致：AT+CPIN（无 ?）；ERROR 不判失败
        commands=["AT+CSQ", "AT+CPIN", "AT+CREG?", "AT+COPS?"],
        baud=baud,
        cmd_timeout=cmd_timeout,
        exec_timeout=exec_timeout,
    )
    return judge_4g(output, min_csq=min_csq, min_rssi_dbm=min_rssi_dbm)


def run_gnss(sess: JumpSSHSession, **kwargs) -> bool:
    require_fix = kwargs.pop("require_fix")
    expect_model = kwargs.pop("expect_model")
    port = kwargs.pop("port")
    baud = kwargs.pop("baud")
    cmd_timeout = kwargs.pop("cmd_timeout")
    exec_timeout = kwargs.pop("exec_timeout")
    gps_wait = kwargs.pop("gps_wait")
    gps_retries = kwargs.pop("gps_retries")

    # 文档第 5 节全套；CGPS=1 后再查 INFO
    commands = ["AT+CGMM", "AT+CGMR", "AT+CGPS=1", "AT+CGPS?", "AT+CGPSINFO"]
    output = _run_at_session(
        sess,
        port=port,
        commands=commands,
        baud=baud,
        cmd_timeout=cmd_timeout,
        exec_timeout=exec_timeout,
    )

    if require_fix:
        info_outputs: list[str] = [output]
        for i in range(max(1, gps_retries)):
            blocks = _blocks(info_outputs[-1])
            info = blocks.get("AT+CGPSINFO", "")
            m = re.search(r"\+CGPSINFO:\s*([^,\s]+)", info)
            if m and m.group(1):
                break
            import time

            wait = gps_wait if i == 0 else max(2.0, gps_wait / 2)
            print(f"等待 GNSS 定位 {wait:.0f}s（第 {i + 1}/{gps_retries} 次）…")
            time.sleep(wait)
            part = _run_at_session(
                sess,
                port=port,
                commands=["AT+CGPSINFO"],
                baud=baud,
                cmd_timeout=cmd_timeout,
                exec_timeout=exec_timeout,
            )
            info_outputs.append(part)
        output = "\n".join(info_outputs)

    return judge_gnss(output, require_fix=require_fix, expect_model=expect_model)


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    _detach_console_when_stdio_piped()
    ap = argparse.ArgumentParser(description="X5 4G/GNSS AT 测试（经跳板 SSH）")
    ap.add_argument("--mode", choices=("4g", "gnss"), required=True)
    ap.add_argument("--jump-host", required=True)
    ap.add_argument("--target-host", required=True)
    ap.add_argument("--user", default="root")
    ap.add_argument("--private-key-file", required=True)
    ap.add_argument("--jump-port", type=int, default=22)
    ap.add_argument("--target-port", type=int, default=22)
    ap.add_argument("--connect-timeout", type=int, default=60)
    ap.add_argument("--exec-timeout", type=int, default=180)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--cmd-timeout", type=float, default=5.0)
    ap.add_argument(
        "--port",
        default="",
        help="串口路径；默认 4g=/dev/ttyUSB2，gnss=/dev/ttyUSB3",
    )
    # 4G
    ap.add_argument(
        "--min-csq",
        type=int,
        default=15,
        help="CSQ RSSI 下限（一般可用≥15）；若指定 --min-rssi-dbm 则优先用 dBm",
    )
    ap.add_argument(
        "--min-rssi-dbm",
        type=int,
        default=None,
        help="可选：按 dBm= -113+2*CSQ 判定，例如 -75",
    )
    # GNSS
    ap.add_argument(
        "--require-fix",
        type=int,
        default=0,
        help="1=要求 CGPSINFO 有经纬度；0=仅检查通路（产线正常截图为空 ,,,,,,,,）",
    )
    ap.add_argument(
        "--expect-model",
        default="SIM7600",
        help="AT+CGMM 响应需包含的型号子串；空字符串则不校验型号",
    )
    ap.add_argument("--gps-wait", type=float, default=15.0, help="require_fix=1 时首次等待秒数")
    ap.add_argument("--gps-retries", type=int, default=4, help="require_fix=1 时轮询次数")
    ap.add_argument(
        "--push-minicom",
        default="",
        help="本机 minicom 路径；填 auto 则用 Seq/tools/minicom；空=不推送",
    )
    ap.add_argument(
        "--minicom-remote",
        default="/userdata/minicom",
        help="推送到 X5 的路径（默认 /userdata/minicom）",
    )
    ns = ap.parse_args(argv)

    common = dict(
        exec_timeout=ns.exec_timeout,
        baud=ns.baud,
        cmd_timeout=ns.cmd_timeout,
    )

    try:
        with JumpSSHSession.connect(
            jump_host=ns.jump_host.strip(),
            target_host=ns.target_host.strip(),
            username=ns.user.strip(),
            private_key_file=ns.private_key_file.strip(),
            jump_port=ns.jump_port,
            target_port=ns.target_port,
            connect_timeout=ns.connect_timeout,
        ) as sess:
            push_raw = (ns.push_minicom or "").strip()
            if push_raw:
                local_m = (
                    str(_default_minicom_local())
                    if push_raw.lower() == "auto"
                    else push_raw
                )
                _push_minicom(
                    sess,
                    local_path=local_m,
                    remote_path=(ns.minicom_remote or "/userdata/minicom").strip(),
                )

            if ns.mode == "4g":
                port = (ns.port or "/dev/ttyUSB2").strip()
                ok = run_4g(
                    sess,
                    port=port,
                    min_csq=ns.min_csq,
                    min_rssi_dbm=ns.min_rssi_dbm,
                    **common,
                )
            else:
                port = (ns.port or "/dev/ttyUSB3").strip()
                ok = run_gnss(
                    sess,
                    port=port,
                    require_fix=bool(ns.require_fix),
                    expect_model=(ns.expect_model or "").strip(),
                    gps_wait=ns.gps_wait,
                    gps_retries=ns.gps_retries,
                    **common,
                )
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] 运行失败: {e}", file=sys.stderr)
        return 1

    if ok:
        print(f"[OK] [{ns.mode.upper()}] 测试通过")
        return 0
    print(f"[FAIL] [{ns.mode.upper()}] 测试失败", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
