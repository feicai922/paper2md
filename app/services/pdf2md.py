#!/usr/bin/env python3
"""PDF → Markdown 转换 worker(PaddleX PP-StructureV3)。

由 app 以 **paddle 环境的 python** 调用(不是本服务自己的 venv):

    ~/.venvs/paddle/bin/python pdf2md.py \
        --pdf in.pdf --out <job>/out [--pipeline PP-StructureV3] [--device auto]

产物:

    <out>/<stem>.md      合并后的 Markdown(页面之间用 --- 分隔并带页注解)
    <out>/imgs/*.jpg     图片 / 表格 / 公式的裁剪图,jpg 格式(不再是 jpx)

为什么要这条管线
----------------
PP-StructureV3 是**版面分析**管线:先检测版面块(title/paragraph/table/figure/
formula),再分别识别,最后合成 Markdown —— 标题层级、段落合并、公式 LaTeX、
表格 HTML、图片按原位置内联都能保住。轻量 PP-OCR 管线只输出"文本行",拿到的
md 就是一堵墙,表格/图片全丢(这正是之前的毛病)。

stdout 约定(父进程逐行解析,其余输出都走 stderr):

    PROGRESS <已完成页数>/<总页数>
    RESULT   {"markdown": "...", "images": N, "pages": N, "engine": "...", "device": "..."}
"""
from __future__ import annotations

import argparse
import re
import json
import os
import shutil
import sys
import time
from pathlib import Path


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def emit(msg: str) -> None:
    print(msg, file=sys.stdout, flush=True)


def page_count(pdf: Path) -> int:
    """数页数(只为进度条;失败不致命)。"""
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(pdf))
        n = len(doc)
        doc.close()
        return n
    except Exception:  # noqa: BLE001
        return 0


def pick_device(force: str) -> str:
    """选设备:auto 时交给 probe_device(挑显存够的卡,拿不到就 CPU)。"""
    if force and force != "auto":
        log(f"设备被显式指定为 {force}")
        return force
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from probe_device import probe_in_subprocess

        info = probe_in_subprocess(sys.executable, timeout=180)
        log(f"设备探测: {info.get('device')} ({info.get('reason', '')})")
        return info.get("device") or "cpu"
    except Exception as exc:  # noqa: BLE001
        log(f"设备探测失败({exc}),回落 cpu")
        return "cpu"


# --- 后处理:补回 OCR 分行拼接时丢掉的空格 -------------------------------
# 现象:`features.However`、`[23],DeepSnake`、`network;long-range` —— 整段正文
# 读起来像是黏在一起。规则只在**纯正文**上生效:HTML 标签、公式、URL 全部先
# 摘出去,避免把 `<img src="imgs/a.jpg">` 或 `$3.5$` 改坏。
_PROTECT = re.compile(
    r"(<[^>]*>|\$\$[\s\S]*?\$\$|\$[^$\n]*\$|https?://\S+|www\.\S+"
    r"|`[^`\n]*`|\]\([^)]*\))"        # 行内代码与 markdown 链接目标也要保护
)
# 逗号/分号/冒号 + 字母 → 补空格(任何大小写)
_RULE_PUNCT = re.compile(r"([,;:])(?=[A-Za-z])")
# 句号 + 字母 → 补空格("features.However" / "branches.which")。
# 句号后跟数字不动,以免误伤 0.5 这类小数。
_RULE_PERIOD = re.compile(r"\.(?=[A-Za-z])")


def fix_spacing(text: str) -> str:
    if not text:
        return text
    parts: list[str] = []
    for part in _PROTECT.split(text):
        if not part:
            continue
        if _PROTECT.fullmatch(part):
            parts.append(part)                 # 标签/公式/URL 原样保留
            continue
        part = _RULE_PUNCT.sub(r"\1 ", part)
        part = _RULE_PERIOD.sub(". ", part)
        parts.append(part)
    return "".join(parts)


def _page_index(path: Path) -> int:
    """从 `xxx_3.md` 里取页序号;取不到就排最后。"""
    stem = path.stem
    tail = stem.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 10 ** 9


def main() -> int:
    parser = argparse.ArgumentParser(description="PDF → Markdown(PaddleX)")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pipeline", default="PP-StructureV3")
    parser.add_argument("--device", default="auto", help="auto / cpu / gpu:4")
    parser.add_argument("--stem", default="", help="输出 Markdown 的文件名(不含扩展名)")
    args = parser.parse_args()

    pdf = Path(args.pdf).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    if not pdf.is_file():
        log(f"输入 PDF 不存在: {pdf}")
        return 2
    out.mkdir(parents=True, exist_ok=True)

    # 共享 GPU:auto_growth 按需增长,并给一个硬上限防把别人的卡吃满
    os.environ.setdefault("FLAGS_allocator_strategy", "auto_growth")
    mem = os.environ.get("RETAIN_LOCAL_PADDLE_GPU_MEM_MB", "").strip() or "16384"
    device = pick_device(args.device)
    emit(f"DEVICE {device}")
    if str(device).lower().startswith("gpu") and mem and mem != "0":
        os.environ["FLAGS_gpu_memory_limit_mb"] = mem
        log(f"显存上限 {mem}MB")

    from paddlex import create_pipeline  # 延迟导入:--help 不拖模型

    started = time.time()
    try:
        pipe = create_pipeline(pipeline=args.pipeline, device=device)
    except Exception as exc:  # noqa: BLE001
        log(f"创建管线 {args.pipeline} 失败: {exc}")
        return 3
    log(f"管线 {args.pipeline} 就绪: {time.time() - started:.1f}s, device={device}")

    total = page_count(pdf)
    pages_dir = out / "_pages"
    shutil.rmtree(pages_dir, ignore_errors=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    done = 0
    try:
        results = pipe.predict(
            input=str(pdf),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        for res in results:
            done += 1
            try:
                res.save_to_markdown(save_path=str(pages_dir))
            except Exception as exc:  # noqa: BLE001
                log(f"第 {done} 页导出 Markdown 失败: {exc}")
            emit(f"PROGRESS {done}/{total or '?'}")
    except Exception as exc:  # noqa: BLE001
        log(f"转换失败(第 {done + 1} 页): {exc}")
        return 4

    page_files = sorted(pages_dir.glob("*.md"), key=_page_index)
    if not page_files:
        log("没有任何 Markdown 页产物")
        return 5

    chunks: list[str] = []
    for i, p in enumerate(page_files, 1):
        text = p.read_text(encoding="utf-8", errors="replace").strip()
        chunks.append(f"<!-- 第 {i} 页 -->\n\n{text}" if text else f"<!-- 第 {i} 页(空) -->")
    markdown = fix_spacing("\n\n---\n\n".join(chunks)) + "\n"

    stem = (args.stem or pdf.stem).strip() or "document"
    md_path = out / f"{stem}.md"
    md_path.write_text(markdown, encoding="utf-8")

    # 逐页导出的图片在 _pages/imgs,md 里的引用是 imgs/xxx.jpg —— 挪到 out/imgs
    src_imgs = pages_dir / "imgs"
    dst_imgs = out / "imgs"
    images = 0
    if src_imgs.is_dir():
        shutil.rmtree(dst_imgs, ignore_errors=True)
        shutil.move(str(src_imgs), str(dst_imgs))
        images = len([p for p in dst_imgs.iterdir() if p.is_file()])
    shutil.rmtree(pages_dir, ignore_errors=True)

    emit("RESULT " + json.dumps({
        "markdown": str(md_path),
        "images": images,
        "pages": len(page_files),
        "chars": len(markdown),
        "engine": args.pipeline,
        "device": device,
        "elapsed": round(time.time() - started, 1),
    }, ensure_ascii=False))
    log(f"完成: {len(page_files)} 页 / {images} 张图 / {len(markdown)} 字符 / "
        f"{time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
