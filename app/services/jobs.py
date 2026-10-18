"""任务编排:上传 PDF → 排队 → PaddleX 转 Markdown → 打包产物。

**串行队列**:转换跑在共享 GPU 上,同时跑多个任务只会互相抢显存(实测直接
OOM),所以这里只有一个 worker 线程,所有任务排队逐个转换。队列里的任务可以
取消(取消后 worker 出队时跳过)。

状态落本地 JSON,进程重启后仍可查历史;启动时把未完成的任务重新排队。
"""
from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ..config import (
    ENGINE_DEFAULT,
    JOB_DIR,
    JOB_TIMEOUT_SEC,
    MINERU_BIN,
    MINERU_MODEL_SOURCE,
    MINERU_PYTHON,
    MINERU_VRAM_MB,
    PADDLE_DEVICE,
    PADDLE_GPU_MEM_MB,
    PADDLE_PIPELINE,
    PADDLE_PYTHON,
    PADDLEX_HOME,
)
from . import md_export

log = logging.getLogger(__name__)

WORKER_SCRIPT = Path(__file__).resolve().parent / "pdf2md.py"
MINERU_WORKER = Path(__file__).resolve().parent / "mineru2md.py"

_lock = threading.Lock()
_jobs: dict[str, "Job"] = {}

# 串行队列 + 唯一的 worker 线程
_queue: "queue.Queue[str | None]" = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_current_proc: subprocess.Popen | None = None
_current_job_id = ""

# 允许对外提供的产物
ALLOWED_OUTPUTS = ("markdown", "md_zip")


class JobError(RuntimeError):
    """面向用户的错误(会被直接展示)。"""


def _fmt_duration(seconds: float) -> str:
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "-"
    if s < 0:
        return "-"
    if s < 60:
        return f"{s:.1f} 秒"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{int(m)} 分 {sec:.1f} 秒"
    h, m = divmod(m, 60)
    return f"{int(h)} 时 {int(m)} 分"


@dataclass
class Job:
    job_id: str
    filename: str
    status: str = "uploaded"        # uploaded|queued|running|succeeded|failed|canceled
    stage: str = ""
    stage_label: str = ""
    progress: float = 0.0
    # 进度是否来自真实页数(False = 还在加载模型/未知)
    progress_known: bool = True
    message: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    src_bytes: int = 0
    page_count: int = 0
    pages_done: int = 0
    pipeline: str = ""          # 本任务用的管线(空 = 用默认)
    engine: str = ""
    device: str = ""
    outputs: dict[str, str] = field(default_factory=dict)
    sizes: dict[str, int] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    # --- 批量上传:同一批一起提交,用 batch_id 关联 ---
    batch_id: str = ""
    batch_index: int = 0
    batch_total: int = 0

    @property
    def dir(self) -> Path:
        return JOB_DIR / self.job_id

    def to_public(self) -> dict[str, Any]:
        d = asdict(self)
        keys = [k for k in self.outputs if k in ALLOWED_OUTPUTS]
        d["outputs"] = sorted(keys)
        d["downloads"] = {k: f"/api/jobs/{self.job_id}/download/{k}" for k in keys}
        d["timings_text"] = {k: _fmt_duration(v) for k, v in (self.timings or {}).items()}
        base = self.started_at or self.created_at
        end = self.finished_at or (time.time() if self.status == "running" else base)
        d["elapsed"] = round(max(0.0, end - base), 1) if self.started_at else 0.0
        return d

    def save(self) -> None:
        self.updated_at = time.time()
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "job.json").write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8"
        )


def _set(job: Job, **kw) -> None:
    with _lock:
        for k, v in kw.items():
            setattr(job, k, v)
        job.save()


# --- 上传(只入库,不启动)-------------------------------------------------

def _page_count(content: bytes) -> int:
    """用 PyMuPDF 数页数(只为了界面显示,失败不影响任务)。"""
    try:
        import fitz

        with fitz.open(stream=content, filetype="pdf") as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001
        return 0


def create_upload(filename: str, content: bytes, *, batch_id: str = "",
                  batch_index: int = 0, batch_total: int = 0) -> Job:
    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    job = Job(job_id=job_id, filename=filename or "input.pdf", src_bytes=len(content),
              page_count=_page_count(content), status="uploaded",
              message="已上传,点击「开始转换」后处理",
              batch_id=batch_id, batch_index=batch_index, batch_total=batch_total)
    job.dir.mkdir(parents=True, exist_ok=True)
    (job.dir / "source.pdf").write_bytes(content)
    with _lock:
        _jobs[job_id] = job
    job.save()
    return job


def create_batch(files: list[tuple[str, bytes]]) -> tuple[str, list[Job]]:
    """批量上传:多个 PDF 共享一个 batch_id,后续一起提交。返回 (batch_id, jobs)。"""
    batch_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    total = len(files)
    jobs = [
        create_upload(name, content, batch_id=batch_id,
                      batch_index=i, batch_total=total)
        for i, (name, content) in enumerate(files)
    ]
    log.info("批量上传 %s: %d 个文件", batch_id, total)
    return batch_id, jobs


def start_batch(job_ids: list[str], pipeline: str = "") -> tuple[list[Job], list[str]]:
    """批量提交(进同一个串行队列)。返回 (已提交, 错误列表)。"""
    started: list[Job] = []
    errors: list[str] = []
    for jid in job_ids:
        try:
            started.append(start_job(jid, pipeline=pipeline))
        except Exception as exc:  # noqa: BLE001
            log.warning("批量提交 %s 失败: %s", jid, exc)
            errors.append(f"{jid}: {exc}")
            j = get_job(jid)
            if j:
                started.append(j)
    return started, errors


# --- 入队 / worker --------------------------------------------------------

def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_worker_loop, name="convert-worker", daemon=True)
        _worker.start()
        log.info("转换 worker 已启动(串行队列)")


def _worker_loop() -> None:
    while True:
        job_id = _queue.get()
        try:
            if job_id is None:
                return
            _convert(job_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("转换 %s 异常: %s", job_id, exc)
            job = get_job(job_id)
            if job:
                _set(job, status="failed", error=str(exc)[:1500],
                     message="转换异常", progress_known=True, finished_at=time.time())
        finally:
            _queue.task_done()


def start_job(job_id: str, pipeline: str = "") -> Job:
    """把任务放进队列。真正的转换由唯一的 worker 串行执行。

    pipeline 为空表示用默认管线;选了别的会记在任务上,worker 按任务执行。
    """
    job = get_job(job_id)
    if not job:
        raise JobError("任务不存在")
    if job.status == "queued":
        raise JobError("任务已在队列中")
    if job.status == "running":
        raise JobError("任务正在转换中")
    # 已完成的任务也允许重转(换了引擎/参数后想用同一份 PDF 再来一次)

    src = job.dir / "source.pdf"
    if not src.is_file():
        raise JobError("找不到已上传的 PDF")

    _set(job, status="queued", stage="queue", stage_label="排队", progress=0.0,
         progress_known=False, pipeline=pipeline.strip(),
         message="排队中…(同一时间只转换一个文档)",
         error="", pages_done=0, started_at=0.0, finished_at=0.0,
         outputs={}, sizes={}, timings={})
    _ensure_worker()
    _queue.put(job_id)
    log.info("任务 %s 入队(队列长度 %d)", job_id, _queue.qsize())
    return job


# --- 转换 ----------------------------------------------------------------

def _convert(job_id: str) -> None:
    global _current_proc, _current_job_id

    job = get_job(job_id)
    if not job or job.status != "queued":
        return                      # 已被取消 / 已处理
    src = job.dir / "source.pdf"
    if not src.is_file():
        _set(job, status="failed", error="找不到已上传的 PDF",
             message="文件缺失", progress_known=True, finished_at=time.time())
        return

    out_dir = job.dir / "out"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 清掉上一次的产物(换引擎重转时,旧的 md/zip/json 会留在任务目录里占地方)
    for old in job.dir.iterdir():
        if old.is_file() and old.name != "job.json" and old.suffix in (".md", ".zip", ".json"):
            try:
                old.unlink()
            except OSError:
                pass

    pipeline = job.pipeline or ENGINE_DEFAULT
    _set(job, status="running", stage="convert", stage_label="转换",
         progress=0.02, progress_known=False,
         message=f"加载模型 {pipeline}（首次约 30~60 秒）…",
         started_at=time.time(), finished_at=0.0, pages_done=0)

    env = {
        **os.environ,
        "PADDLEX_HOME": PADDLEX_HOME,
        # probe_device 用它决定"这张卡放不放得下"
        "RETAIN_LOCAL_PADDLE_GPU_MEM_MB": str(PADDLE_GPU_MEM_MB),
        "PYTHONUNBUFFERED": "1",
    }
    stem = Path(job.filename).stem or "document"
    if pipeline == "MinerU":
        cmd = [
            MINERU_PYTHON, str(MINERU_WORKER),
            "--pdf", str(src), "--out", str(out_dir),
            "--stem", stem, "--device", PADDLE_DEVICE,
            "--mineru", MINERU_BIN,
            "--source", MINERU_MODEL_SOURCE,
            "--vram", str(MINERU_VRAM_MB),
        ]
    else:
        cmd = [
            PADDLE_PYTHON, str(WORKER_SCRIPT),
            "--pdf", str(src), "--out", str(out_dir),
            "--pipeline", pipeline, "--device", PADDLE_DEVICE,
            "--stem", stem,
        ]
    log.info("开始转换 %s: %s", job_id, " ".join(cmd[1:3]))
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
    except Exception as exc:  # noqa: BLE001
        _set(job, status="failed", error=f"无法启动转换进程: {exc}",
             message="启动失败", progress_known=True, finished_at=time.time())
        return
    _current_proc, _current_job_id = proc, job_id

    lines: "queue.Queue[str | None]" = queue.Queue()

    def _pump() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    threading.Thread(target=_pump, name=f"pump-{job_id}", daemon=True).start()

    result: dict | None = None
    tail: list[str] = []
    deadline = time.time() + JOB_TIMEOUT_SEC
    stop_reason = ""

    while True:
        try:
            line = lines.get(timeout=1.0)
        except queue.Empty:
            line = ""
        if line is None:            # 进程输出结束
            break
        if line:
            text = line.rstrip("\n")
            if text.startswith("DEVICE "):
                dev = text[len("DEVICE "):].strip()
                hint = ("在 " + dev + " 上转换") if dev.startswith("gpu") else "没有空闲 GPU,回落 CPU（会慢很多）"
                _set(job, device=dev, message=hint + "…")
            elif text.startswith("PROGRESS "):
                payload = text[len("PROGRESS "):].strip()
                done, _, total = payload.partition("/")
                try:
                    done_n = int(done)
                    total_n = int(total)
                except ValueError:
                    done_n, total_n = 0, 0
                if total_n > 0:
                    frac = 0.05 + 0.90 * min(1.0, done_n / total_n)
                    _set(job, progress=round(frac, 4), progress_known=True,
                         pages_done=done_n,
                         message=f"转换中 {done_n}/{total_n} 页…")
                else:
                    _set(job, progress=0.5, progress_known=False,
                         pages_done=done_n, message=f"已转换 {done_n} 页…")
            elif text.startswith("RESULT "):
                try:
                    result = json.loads(text[len("RESULT "):])
                except json.JSONDecodeError:
                    log.warning("无法解析 worker RESULT 行: %s", text[:200])
            else:
                tail.append(text)
                if len(tail) > 200:
                    tail.pop(0)

        # 周期性检查:取消 / 超时(读 stdout 会阻塞,所以用 1 秒超时回到这里)
        job = get_job(job_id) or job
        if job.status == "canceled":
            stop_reason = "canceled"
            _terminate(proc)
            break
        if time.time() > deadline:
            stop_reason = "timeout"
            _terminate(proc)
            break

    try:
        rc = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = proc.wait()
    _current_proc, _current_job_id = None, ""

    job = get_job(job_id) or job
    if stop_reason == "canceled" or job.status == "canceled":
        _set(job, status="canceled", message="已取消", progress_known=True,
             finished_at=time.time())
        log.info("任务 %s 已取消", job_id)
        return
    if stop_reason == "timeout":
        _set(job, status="failed", progress_known=True,
             error=f"转换超过 {JOB_TIMEOUT_SEC // 60} 分钟仍未完成,已终止",
             message="超时", finished_at=time.time())
        return
    if rc != 0 or not result:
        detail = "\n".join(tail[-12:]).strip()[-1500:] or f"worker 退出码 {rc}"
        _set(job, status="failed", error=detail, message="转换失败",
             progress_known=True, finished_at=time.time())
        log.warning("任务 %s 转换失败(rc=%s): %s", job_id, rc, detail[:300])
        return

    _finish(job, result)


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except Exception:  # noqa: BLE001
        pass


def _finish(job: Job, result: dict) -> None:
    """打包 md + imgs,更新任务状态。"""
    out_dir = job.dir / "out"
    stem = Path(job.filename).stem or "document"
    md_path = Path(result.get("markdown") or (out_dir / f"{stem}.md"))
    if not md_path.is_file():
        _set(job, status="failed", error="转换结束但没有 Markdown 产物",
             message="产物缺失", progress_known=True, finished_at=time.time())
        return

    _set(job, stage="export", stage_label="打包", progress=0.97,
         message="打包 Markdown 与图片…")
    zip_path = job.dir / f"{stem}-md.zip"
    try:
        info = md_export.build_zip(out_dir=out_dir, stem=stem, zip_path=zip_path,
                                   pages=int(result.get("pages") or job.page_count or 0))
    except Exception as exc:  # noqa: BLE001
        log.warning("打包失败(%s): %s", job.job_id, exc)
        info = {"zip_bytes": 0, "images": 0}

    elapsed = time.time() - (job.started_at or job.created_at)
    outs = {"markdown": str(md_path)}
    sizes = {"markdown": md_path.stat().st_size}
    if info.get("zip_bytes"):
        outs["md_zip"] = str(zip_path)
        sizes["md_zip"] = info["zip_bytes"]

    _set(job,
         status="succeeded", stage="done", stage_label="完成", progress=1.0,
         progress_known=True,
         message=(f"完成(耗时 {_fmt_duration(elapsed)} · "
                  f"{result.get('pages') or job.page_count} 页 · "
                  f"{result.get('images', 0)} 图)"),
         outputs=outs, sizes=sizes, timings={"total": elapsed},
         engine=str(result.get("engine") or PADDLE_PIPELINE),
         device=str(result.get("device") or ""),
         pages_done=int(result.get("pages") or job.pages_done or 0),
         page_count=int(result.get("pages") or job.page_count or 0),
         finished_at=time.time())
    log.info("任务 %s 完成: %.1fs,产物 %s", job.job_id, elapsed, list(outs))


# --- 查询 / 取消 / 产物 ---------------------------------------------------

def get_job(job_id: str) -> Job | None:
    with _lock:
        job = _jobs.get(job_id)
    if job:
        return job
    meta = JOB_DIR / job_id / "job.json"
    if meta.is_file():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            job = Job(**{k: v for k, v in data.items() if k in Job.__dataclass_fields__})
            with _lock:
                _jobs[job_id] = job
            return job
        except Exception:  # noqa: BLE001
            return None
    return None


def list_jobs(limit: int = 50) -> list[Job]:
    out = []
    for d in sorted(JOB_DIR.glob("*/job.json"),
                    key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        j = get_job(d.parent.name)
        if j:
            out.append(j)
    return out


def archive(limit: int = 500) -> dict:
    """归档视图:按日期分组。"""
    by_date: dict[str, list] = {}
    for j in list_jobs(limit=limit):
        day = time.strftime("%Y-%m-%d", time.localtime(j.created_at))
        by_date.setdefault(day, []).append(j.to_public())

    dates = [
        {"date": day, "count": len(by_date[day]), "jobs": by_date[day]}
        for day in sorted(by_date.keys(), reverse=True)
    ]
    return {"dates": dates, "total": sum(d["count"] for d in dates)}


def cancel_job(job_id: str) -> bool:
    job = get_job(job_id)
    if not job or job.status not in ("queued", "running"):
        return False
    _set(job, status="canceled", message="已取消", progress_known=True)
    # 正在转换:杀掉子进程(worker 的循环里也会看到 canceled 再兜一次)
    if job_id == _current_job_id and _current_proc and _current_proc.poll() is None:
        _terminate(_current_proc)
    return True


def output_path(job: Job, key: str) -> Path | None:
    if key not in ALLOWED_OUTPUTS:
        return None
    p = job.outputs.get(key)
    if not p:
        return None
    path = Path(p)
    return path if path.is_file() else None


def delete_job(job_id: str) -> bool:
    job = get_job(job_id)
    if not job:
        return False
    if job.status in ("queued", "running"):
        cancel_job(job_id)
    shutil.rmtree(job.dir, ignore_errors=True)
    with _lock:
        _jobs.pop(job_id, None)
    return True


def any_running() -> bool:
    return any(j.status in ("queued", "running") for j in list_jobs(limit=200))


def resume_orphans() -> int:
    """启动自愈:把上次没跑完的任务重新排队(转换不可续跑,只能重来)。"""
    fixed = 0
    for job in list_jobs(limit=500):
        if job.status not in ("queued", "running"):
            continue
        if not (job.dir / "source.pdf").is_file():
            _set(job, status="failed", error="源文件已丢失", message="启动自愈失败",
                 progress_known=True, finished_at=time.time())
            fixed += 1
            continue
        _set(job, status="queued", message="服务重启,重新排队…", progress=0.0,
             progress_known=False, pages_done=0, started_at=0.0, finished_at=0.0)
        _ensure_worker()
        _queue.put(job.job_id)
        fixed += 1
    if fixed:
        log.info("启动自愈:重新排队 %d 个任务", fixed)
    return fixed
