#!/usr/bin/env python
"""探测当前节点上可用的 Paddle OCR 设备。

背景:Paddle 官方 wheel 只编了较新架构的 kernel。
* P100(Tesla,**算力 6.0**)→ 会报 `This program was not compiled for SM 60`,
  必须回落 CPU;
* TITAN RTX(7.5) / RTX 3090(8.6) / RTX 4090(8.9) / A6000(8.6) → GPU 可用。

判定方式不是"猜算力",而是**真的跑一个小算子**(sort)看是否抛异常 ——
算力够但驱动/显存有问题时同样会失败,实际试一次最可靠。

输出一行 JSON,便于被 shell / Python 调用方解析:
  {"mode": "gpu", "device": "gpu:1"}  或  {"mode": "cpu", "device": "cpu", "reason": "..."}
"""
from __future__ import annotations

import json
import os
import sys


def _need_free_mb() -> int:
    """选卡需要多少空闲显存(MB)。

    必须与 paddle_local_ocr.py 的显存上限对齐:后者默认按
    RETAIN_LOCAL_PADDLE_GPU_MEM_MB(共享卡常设 8192)硬限,Paddle 会把这块额度
    全部吃掉。若这里只按 4GB 选卡,就会挑到一张"看着闲、实际放不下 8GB"的卡,
    任务直接 OutOfMemoryError(实测踩过)。
    """
    margin = 1024
    limit = 8192                       # paddle_local_ocr.py 的默认上限
    raw = os.environ.get("RETAIN_LOCAL_PADDLE_GPU_MEM_MB", "").strip()
    try:
        if raw:
            limit = int(raw)
    except ValueError:
        pass
    if limit <= 0:                     # 0 = 不限,退回最低要求
        limit = int(os.environ.get("OT_OCR_MIN_FREE_MB", "4096"))
        return max(0, limit)
    return limit + margin


def _candidate_gpus() -> list[int]:
    """返回候选 GPU 序号:优先显存够用的,其次任意可见的。"""
    raw = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    if raw:
        ids = []
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        if ids:
            return ids
    try:
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.used,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except Exception:
        return []
    need = _need_free_mb()
    free, all_ids = [], []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            idx = int(parts[0])
            used = int(parts[1].split()[0])
            total = int(parts[2].split()[0])
        except (ValueError, IndexError):
            continue
        all_ids.append(idx)
        if total - used > need:
            free.append(idx)
    # 优先空闲卡,再退回全部
    return free or all_ids


def probe() -> dict:
    """在当前进程内探测。

    ⚠️ 注意:Paddle 在不支持当前算力的卡上**不是抛 Python 异常,而是直接 abort
    (SIGABRT / core dumped)** —— 例如 P100 上会打印
    `This program was not compiled for SM 60` 然后整个进程挂掉。
    所以**不要在本进程里调用它**,要用 probe_in_subprocess()。
    """
    try:
        import paddle
    except Exception as exc:  # noqa: BLE001
        return {"mode": "cpu", "device": "cpu", "reason": f"paddle 不可用: {exc}"}

    if not paddle.is_compiled_with_cuda():
        return {"mode": "cpu", "device": "cpu", "reason": "paddle 未编译 CUDA"}

    cands = _candidate_gpus()
    if not cands:
        return {"mode": "cpu", "device": "cpu", "reason": "没有可用 GPU 或显存不足"}

    last = "未知"
    for idx in cands:
        try:
            paddle.device.set_device(f"gpu:{idx}")
            # 关键:sort/topk 走 cccl/cub,正是 P100 上缺失的那个 kernel。
            # 能跑通说明这张卡真的可用。
            x = paddle.rand([256])
            paddle.sort(x)
            paddle.topk(x, k=5)
            cap = paddle.device.cuda.get_device_capability(idx)
            return {
                "mode": "gpu",
                "device": f"gpu:{idx}",
                "reason": f"算力 {cap[0]}.{cap[1]} 可用",
            }
        except Exception as exc:  # noqa: BLE001
            last = (str(exc).splitlines() or [type(exc).__name__])[0][:120]
    return {"mode": "cpu", "device": "cpu",
            "reason": f"所有候选 GPU 均不可用(最后一错: {last})"}


# 真正跑探测的子命令:probe_device.py --run
def _run_and_print() -> None:
    print(json.dumps(probe(), ensure_ascii=False))


def probe_in_subprocess(python_bin: str | None = None, timeout: int = 180) -> dict:
    """在**独立子进程**里探测,避免 Paddle abort 拖垮调用方。

    返回 {"mode","device","reason"};任何异常/超时都安全回落 cpu。
    """
    import subprocess

    py = python_bin or sys.executable
    env = {**os.environ}
    # 清掉可能干扰探测的强制设备设置
    env.pop("RETAIN_LOCAL_PADDLE_DEVICE", None)
    try:
        proc = subprocess.run(
            [py, os.path.abspath(__file__), "--run"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return {"mode": "cpu", "device": "cpu", "reason": "设备探测超时"}

    if proc.returncode != 0:
        # 典型:P100 上 SIGABRT(-6)
        tail = (proc.stderr or "").strip().splitlines()
        hint = ""
        for line in tail:
            if "SM " in line or "not compiled" in line or "core dumped" in line:
                hint = line.strip()[:120]
                break
        if not hint and tail:
            hint = tail[-1][:120]
        return {"mode": "cpu", "device": "cpu",
                "reason": f"探测失败(exit={proc.returncode}){': ' + hint if hint else ''}"}

    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return {"mode": "cpu", "device": "cpu", "reason": "探测无输出"}
    try:
        return json.loads(line[-1])
    except json.JSONDecodeError:
        return {"mode": "cpu", "device": "cpu", "reason": "探测输出无法解析"}


if __name__ == "__main__":
    # `--run` 是给 probe_in_subprocess 用的;直接执行时也走同样的输出。
    _run_and_print()
