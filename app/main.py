"""PDF → Markdown 服务:上传 PDF → 排队转换 → 在线预览 / 下载。

转换由 PaddleX PP-StructureV3 管线在 paddle 环境的子进程里跑(版面分析 +
OCR),本服务负责上传、排队、进度、产物打包与预览(见 services/jobs.py)。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .config import (BASE_DIR, ENGINE_DEFAULT, MINERU_PYTHON, PADDLE_DEVICE,
                     PADDLE_PIPELINE, PADDLE_PYTHON, PIPELINES)
from .services import jobs as jobsvc

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ocr-translate")

app = FastAPI(title="PDF → Markdown", version="0.5.0")

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_BATCH_FILES = 20
# Markdown 预览最多返回多少字符(整篇可能很大,前端只做预览)
MAX_PREVIEW_CHARS = 400_000

STATIC_DIR = BASE_DIR / "app" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
DIST_DIR = STATIC_DIR / "dist"
INDEX_FILE = DIST_DIR / "index.html"


# --- 启动 ----------------------------------------------------------------

@app.on_event("startup")
def _startup() -> None:
    # 自愈:上次没跑完的任务(排队/转换中)重新排队;转换不可续跑,只能重来
    try:
        fixed = jobsvc.resume_orphans()
        if fixed:
            log.info("启动自愈完成:%d 个任务", fixed)
    except Exception as exc:  # noqa: BLE001
        log.warning("启动自愈失败: %s", exc)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "engine": {
            "pipeline": ENGINE_DEFAULT,
            "paddle_pipeline": PADDLE_PIPELINE,
            "mineru": {"python": MINERU_PYTHON, "available": Path(MINERU_PYTHON).exists()},
            "pipelines": PIPELINES,
            "device": PADDLE_DEVICE,
            "python": PADDLE_PYTHON,
            "available": Path(PADDLE_PYTHON).exists(),
        },
    }


# --- 上传 ----------------------------------------------------------------

def _validate_pdf(name: str, content: bytes) -> None:
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, f"只支持 PDF 文件:{name}")
    if not content:
        raise HTTPException(400, f"文件内容为空:{name}")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件过大(上限 {MAX_UPLOAD_BYTES // 1024 // 1024}MB):{name}")
    if not content.startswith(b"%PDF"):
        raise HTTPException(400, f"不是有效的 PDF(缺少 %PDF 头):{name}")


@app.post("/api/jobs")
async def upload(file: UploadFile = File(...)) -> JSONResponse:
    """单文件上传,**不启动**转换。等用户点「开始转换」。"""
    name = file.filename or "input.pdf"
    content = await file.read()
    _validate_pdf(name, content)
    job = jobsvc.create_upload(name, content)
    log.info("上传 %s: %s (%.1f MB)", job.job_id, name, len(content) / 1048576)
    return JSONResponse(job.to_public())


@app.post("/api/batches")
async def upload_batch(files: list[UploadFile] = File(...)) -> JSONResponse:
    """批量上传:多个 PDF 一次入库,随后用 /api/batches/{id}/start 一起提交。"""
    payload: list[tuple[str, bytes]] = []
    for f in files:
        name = f.filename or "input.pdf"
        content = await f.read()
        _validate_pdf(name, content)
        payload.append((name, content))

    if not payload:
        raise HTTPException(400, "没有收到文件")
    if len(payload) > MAX_BATCH_FILES:
        raise HTTPException(400, f"一次最多 {MAX_BATCH_FILES} 个文件")

    batch_id, jobs = jobsvc.create_batch(payload)
    log.info("批量上传 %s: %d 个文件", batch_id, len(jobs))
    return JSONResponse({
        "batch_id": batch_id,
        "count": len(jobs),
        "jobs": [j.to_public() for j in jobs],
    })


# --- 任务 ----------------------------------------------------------------

def _pick_pipeline(payload: dict) -> str:
    """只接受白名单里的管线名,非法值退回默认。"""
    name = str((payload or {}).get("pipeline") or "").strip()
    return name if name in PIPELINES else ""


@app.post("/api/batches/{batch_id}/start")
def start_batch(batch_id: str, payload: dict = Body(default={})) -> JSONResponse:
    jobs = [j for j in jobsvc.list_jobs(limit=500) if j.batch_id == batch_id]
    if not jobs:
        raise HTTPException(404, "批次不存在")
    pending = [j.job_id for j in jobs if j.status in ("uploaded", "failed", "canceled")]
    if not pending:
        raise HTTPException(409, "该批次没有待提交的任务")

    started, errors = jobsvc.start_batch(pending, pipeline=_pick_pipeline(payload))
    return JSONResponse({
        "started": len([j for j in started if j.status == "queued"]),
        "errors": errors,
        "jobs": [j.to_public() for j in started],
    })


@app.post("/api/jobs/{job_id}/start")
def start(job_id: str, payload: dict = Body(default={})) -> JSONResponse:
    try:
        job = jobsvc.start_job(job_id, pipeline=_pick_pipeline(payload))
    except jobsvc.JobError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.warning("提交任务 %s 失败: %s", job_id, exc)
        raise HTTPException(500, f"提交失败:{exc}") from exc
    return JSONResponse(job.to_public())


@app.get("/api/jobs")
def list_jobs() -> JSONResponse:
    return JSONResponse([j.to_public() for j in jobsvc.list_jobs()])


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    job = jobsvc.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return JSONResponse(job.to_public())


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str) -> JSONResponse:
    if not jobsvc.cancel_job(job_id):
        raise HTTPException(409, "任务不在可取消状态")
    return JSONResponse({"ok": True})


@app.delete("/api/jobs/{job_id}")
def delete(job_id: str) -> JSONResponse:
    if not jobsvc.delete_job(job_id):
        raise HTTPException(404, "任务不存在")
    return JSONResponse({"ok": True})


# --- 预览与图片 -----------------------------------------------------------

# 正文里的图片引用两种写法都要改写:
#   <img src="imgs/xxx.jpg">
#   ![说明](imgs/xxx.jpg)
_IMG_REF = re.compile(r'(?P<prefix>!\[[^\]]*\]\(|src=")imgs/(?P<name>[^")\s]+)')


def _inline_images(markdown: str, job_id: str) -> str:
    return _IMG_REF.sub(
        lambda m: f'{m.group("prefix")}/api/jobs/{job_id}/images/{m.group("name")}',
        markdown,
    )


@app.get("/api/jobs/{job_id}/preview")
def preview(job_id: str) -> JSONResponse:
    """返回 Markdown 正文供界面预览(图片改成可访问的 URL,最多 40 万字符)。"""
    job = jobsvc.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    path = jobsvc.output_path(job, "markdown")
    if not path:
        raise HTTPException(404, "尚未生成 Markdown")
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(MAX_PREVIEW_CHARS)
    except OSError as exc:
        raise HTTPException(500, f"读取 Markdown 失败:{exc}") from exc
    return JSONResponse({
        "text": _inline_images(text, job_id),
        "truncated": path.stat().st_size > len(text.encode("utf-8")),
    })


@app.get("/api/jobs/{job_id}/images/{name}")
def image(job_id: str, name: str) -> FileResponse:
    """预览用的插图(只允许取 out/imgs 下的文件,防目录穿越)。"""
    job = jobsvc.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    base = (job.dir / "out" / "imgs").resolve()
    try:
        path = (base / name).resolve()
        path.relative_to(base)
    except (ValueError, OSError):
        raise HTTPException(404, "图片不存在") from None
    if not path.is_file():
        raise HTTPException(404, "图片不存在")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


DOWNLOAD_META = {
    # key: (文件名后缀, media_type)
    "markdown": (".md", "text/markdown; charset=utf-8"),
    "md_zip": ("-md.zip", "application/zip"),
}


@app.get("/api/jobs/{job_id}/download/{key}")
def download(job_id: str, key: str) -> FileResponse:
    job = jobsvc.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    path = jobsvc.output_path(job, key)
    if not path:
        raise HTTPException(404, "产物不存在或尚未生成")
    suffix, media = DOWNLOAD_META[key]
    return FileResponse(path, media_type=media,
                        filename=f"{Path(job.filename).stem}{suffix}")


# --- 归档(按日期) --------------------------------------------------------

@app.get("/api/archive")
def archive() -> JSONResponse:
    return JSONResponse(jobsvc.archive(limit=500))


# 注意:不要用 app.mount("/", StaticFiles(...)) —— 它会接管根路径下**所有**请求,
# 导致后面的 SPA 兜底路由永远匹配不到,刷新 /archive 就 404(实测踩过)。
# 改为显式路由:先尝试把路径当静态文件返回,取不到再交给 Vue Router。


@app.get("/{full_path:path}", response_class=HTMLResponse)
def spa(full_path: str) -> HTMLResponse:
    """静态文件优先,否则交给 Vue Router(SPA 兜底)。"""
    if full_path:
        candidate = (DIST_DIR / full_path).resolve()
        try:
            candidate.relative_to(DIST_DIR.resolve())   # 防目录穿越
        except ValueError:
            raise HTTPException(404, "not found") from None
        if candidate.is_file():
            # 带内容哈希的资源可长缓存;index.html 必须禁缓存,否则会引用旧 js/css
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} \
                if "-" in candidate.stem and candidate.suffix in (".js", ".css") \
                else {"Cache-Control": "no-cache"}
            return FileResponse(candidate, headers=headers)

    if not INDEX_FILE.is_file():
        return HTMLResponse(
            "<h1>前端尚未构建</h1>"
            "<p>请在 ocr-translate/web 下执行:</p>"
            "<pre>npm install --registry=https://registry.npmmirror.com\nnpm run build</pre>",
            status_code=503,
        )
    return HTMLResponse(
        INDEX_FILE.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )
