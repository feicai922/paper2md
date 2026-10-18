#!/usr/bin/env python3
"""PDF → Markdown 转换 worker(MinerU 管线)。

由 app 用 **MinerU 专用 venv 的 python** 调用:

    ~/.venvs/mineru/bin/python mineru2md.py \
        --pdf in.pdf --out <job>/out --stem paper [--device auto]

MinerU 的 pipeline 后端会:版面检测 → 公式识别(UniMERNet)→ 表格识别 →
对**带文字层的 PDF 直接取文字**(不重新 OCR,所以没有 OCR 错字),最后输出
一份 Markdown + images/。

产物(统一到 app 的约定):
    <out>/<stem>.md      MinerU 的 md(页间补 <!-- 第 N 页 --> 注解)
    <out>/imgs/*.jpg     插图

stdout 约定(父进程逐行解析,其余输出走 stderr):
    PROGRESS <已完成页数>/<总页数>
    RESULT   {"markdown": ..., "images": N, "pages": N, "engine": "MinerU", "device": "..."}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def emit(msg: str) -> None:
    print(msg, file=sys.stdout, flush=True)


def pick_device(force: str) -> str:
    """返回 MinerU 的 -d 参数。

    ⚠️ 这里不能用 probe_device.py —— 它是给 paddle 环境写的(要 import paddle),
    MinerU 的 venv 里没有 paddle,会永远判成 cpu。MinerU 自己用 torch,
    所以直接问 torch:哪张卡空闲显存够就用哪张。
    """
    if force and force != "auto":
        return force.replace("gpu:", "cuda:")
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        log(f"torch 不可用({exc}),回落 cpu")
        return "cpu"
    if not torch.cuda.is_available():
        log("CUDA 不可用,回落 cpu")
        return "cpu"

    need_mb = int(os.environ.get("RETAIN_LOCAL_PADDLE_GPU_MEM_MB", "16000") or 16000)
    need = need_mb * 1024 * 1024

    # 共享机器上只看显存不够:卡可能显存空着但被别人的任务跑满(util 100%),
    # 加载模型会卡几分钟。所以同时看利用率,优先「显存够 + 最闲」的卡。
    utils = _gpu_utilization()
    count = torch.cuda.device_count()
    fits: list[tuple[int, int, int]] = []      # (-util, -free, idx)
    others: list[tuple[int, int]] = []
    for i in range(count):
        try:
            free, _total = torch.cuda.mem_get_info(i)
        except Exception:  # noqa: BLE001
            continue
        util = utils.get(i, 0)
        others.append((free, i))
        if free >= need:
            fits.append((-util, -free, i))
    if fits:
        fits.sort()
        neg_util, neg_free, idx = fits[0]
        log(f"选卡 gpu:{idx}(空闲 {-neg_free // 1048576}MB, 利用率 {-neg_util}%)")
        return f"cuda:{idx}"
    # 没有卡满足 need:共享机器上硬挤会比 CPU 更慢(甚至直接 OOM),
    # 所以只有「最空的卡还够底线」才用它,否则老老实实回 CPU。
    floor_mb = int(os.environ.get("OT_MINERU_MIN_FREE_MB", "6000") or 6000)
    if others:
        free, idx = max(others)
        if free >= floor_mb * 1024 * 1024:
            log(f"没有卡满足 {need_mb}MB 空闲,用最空的 gpu:{idx}"
                f"({free // 1048576}MB, utils={utils.get(idx)}),可能较慢")
            return f"cuda:{idx}"
        log(f"最空的卡只剩 {free // 1048576}MB(低于 {floor_mb}MB 底线),回落 cpu")
        return "cpu"
    log("没有可用显卡,回落 cpu")
    return "cpu"


def _gpu_utilization() -> dict[int, int]:
    """nvidia-smi 取每张卡的 GPU 利用率;取不到就都当 0。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:  # noqa: BLE001
        return {}
    util: dict[int, int] = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            util[int(parts[0])] = int(parts[1].rstrip("% ").strip())
        except ValueError:
            continue
    return util


def page_count(pdf: Path) -> int:
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(pdf))
        n = len(doc)
        doc.close()
        return n
    except Exception:  # noqa: BLE001
        return 0


_TQDM = re.compile(r"Processing pages:\s+(\d+)%\|[^|]*\|\s*(\d+)/(\d+)")


def main() -> int:
    parser = argparse.ArgumentParser(description="PDF → Markdown(MinerU)")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--stem", default="")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--mineru", default="mineru", help="mineru 可执行文件")
    parser.add_argument("--source", default="modelscope", help="模型源")
    parser.add_argument("--vram", default="16000")
    args = parser.parse_args()

    pdf = Path(args.pdf).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    if not pdf.is_file():
        log(f"输入 PDF 不存在: {pdf}")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    stem = (args.stem or pdf.stem).strip() or "document"

    device = pick_device(args.device)
    emit(f"DEVICE {device.replace('cuda:', 'gpu:')}")

    raw_dir = out / "_mineru"
    shutil.rmtree(raw_dir, ignore_errors=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    env = {**os.environ, "MINERU_MODEL_SOURCE": args.source, "PYTHONUNBUFFERED": "1"}
    cmd = [
        args.mineru, "-p", str(pdf), "-o", str(raw_dir),
        "-b", "pipeline", "-d", device, "--vram", args.vram,
        "--source", args.source,
    ]
    log("运行: " + " ".join(cmd))
    started = time.time()

    total = page_count(pdf)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=env,
    )
    assert proc.stdout is not None
    tail: list[str] = []
    last_pct = -1
    buf = ""
    while True:
        ch = proc.stdout.read(1)
        if not ch:
            break
        # tqdm 用 \r 刷新同一行,不能按行读 —— 逐字符攒到 \r 或 \n 再解析
        if ch in "\r\n":
            line = buf.strip()
            buf = ""
            if not line:
                continue
            m = _TQDM.search(line)
            if m:
                pct, done, tot = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if pct != last_pct:
                    last_pct = pct
                    emit(f"PROGRESS {done}/{tot}")
                    log(f"页进度 {done}/{tot}（{pct}%）")
                continue
            tail.append(line)
            if len(tail) > 300:
                tail.pop(0)
        else:
            buf += ch
            if len(buf) > 4000:
                buf = buf[-2000:]

    rc = proc.wait()
    if rc != 0:
        detail = "\n".join(tail[-15:]).strip()[-1500:]
        log(f"MinerU 失败(rc={rc}): {detail}")
        return rc or 1

    # MinerU 产物:raw/<pdf名>/auto/<pdf名>.md + images/
    md_candidates = sorted(raw_dir.rglob("*.md"))
    if not md_candidates:
        log("MinerU 没有产出 Markdown")
        return 3
    src_md = md_candidates[0]

    # MinerU 的 md 不带页标记 —— 保留原文,不硬插分隔符(插错比不插更糟)
    text = src_md.read_text(encoding="utf-8", errors="replace")

    # MinerU 的图放在 images/,本服务统一用 imgs/ —— 不改引用就全是断链
    text = text.replace("](images/", "](imgs/").replace('src="images/', 'src="imgs/')

    dst_md = out / f"{stem}.md"
    dst_md.write_text(text, encoding="utf-8")

    src_imgs = src_md.parent / "images"
    dst_imgs = out / "imgs"
    shutil.rmtree(dst_imgs, ignore_errors=True)
    images = 0
    if src_imgs.is_dir():
        shutil.move(str(src_imgs), str(dst_imgs))
        images = len([p for p in dst_imgs.iterdir() if p.is_file()])
    shutil.rmtree(raw_dir, ignore_errors=True)

    emit("RESULT " + json.dumps({
        "markdown": str(dst_md),
        "images": images,
        "pages": total or 0,
        "chars": len(text),
        "engine": "MinerU",
        "device": device.replace("cuda:", "gpu:"),
        "elapsed": round(time.time() - started, 1),
    }, ensure_ascii=False))
    log(f"完成: {total or '?'} 页 / {images} 图 / {len(text)} 字符 / "
        f"{time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
