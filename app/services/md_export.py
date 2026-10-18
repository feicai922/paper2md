"""把转换产物打成 ZIP:Markdown 正文 + imgs/ 插图 + 一份 README 索引。"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)


def _readme(stem: str, md_path: Path, images: list[Path], pages: int) -> str:
    lines = [
        f"# {stem}",
        "",
        "本文档由 **PP-StructureV3 版面分析 + OCR** 转成 Markdown,"
        "标题层级、公式(LaTeX)、表格(HTML)与插图均按原位置保留。",
        "",
        "## 内容",
        "",
        "| 文件 | 说明 |",
        "| --- | --- |",
        f"| `{md_path.name}` | 转换后的正文;页与页之间用 `---` 分隔,并带 `<!-- 第 N 页 -->` 注解 |",
        f"| `imgs/` | 从原文裁出的 {len(images)} 张图(插图 / 表格 / 公式) |",
        "",
        "## 元信息",
        "",
        f"- 页数:{pages or '—'}",
        f"- 插图数:{len(images)}",
        f"- 正文字符数:{len(md_path.read_text(encoding='utf-8', errors='replace'))}",
        "",
        "## 阅读提示",
        "",
        "- 表格是 HTML `<table>`,浏览器/多数 Markdown 渲染器可直接显示。",
        "- 公式是 `$…$` / `$$…$$` 形式的 LaTeX。",
        "- 图片引用形如 `imgs/img_in_image_box_92_166_1093_499.jpg`,"
        "文件名里的数字是该图在页面上的像素框(便于回溯定位)。",
        "",
    ]
    return "\n".join(lines)


def build_zip(*, out_dir: Path, stem: str, zip_path: Path, pages: int = 0) -> dict:
    """打包 out_dir 下的 md + imgs,返回统计信息。

    产物结构:
        xxx-md.zip
          README.md
          xxx.md
          imgs/*.jpg
    """
    md_path = out_dir / f"{stem}.md"
    if not md_path.is_file():
        raise FileNotFoundError(f"找不到 Markdown: {md_path}")
    imgs_dir = out_dir / "imgs"
    images = sorted(p for p in imgs_dir.iterdir() if p.is_file()) if imgs_dir.is_dir() else []

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", _readme(stem, md_path, images, pages))
        zf.write(md_path, md_path.name)
        for p in images:
            zf.write(p, f"imgs/{p.name}")

    size = zip_path.stat().st_size
    log.info("打包完成: %s(%d 图, %.1f MB)", zip_path.name, len(images), size / 1048576)
    return {"zip_bytes": size, "images": len(images)}
