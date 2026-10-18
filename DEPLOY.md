# 自部署指南(paper2md)

本文从零到跑通,面向一台**有 NVIDIA GPU 的 Linux 机器**(CPU 也能跑,只是慢)。
全程不依赖 Docker。

- 默认引擎 **MinerU**:文字层 + 公式/表格识别,质量最好,安装稍重;
- 备选引擎 **PaddleX**(PP-StructureV3 / PaddleOCR-VL):依赖少,质量略逊。

```
浏览器 ──HTTP──> FastAPI(:8300) ──子进程──> MinerU / PaddleX ──> Markdown + imgs
                     │
                     └─ data/jobs/<id>/:source.pdf、out/、xxx-md.zip
```

---

## 0. 硬件与环境要求

| 项 | 要求 | 说明 |
| --- | --- | --- |
| OS | Linux x86_64 | 只在 Linux 上验证过 |
| GPU | NVIDIA,单卡空闲显存 ≥ 8GB | MinerU/PaddleX 都要;显存不足会自动回落 CPU |
| 驱动 | CUDA 12.6+ | MinerU 用 torch 2.7.1+cu126 |
| Python | 3.10~3.11 | Web 服务 3.9+ 也行;引擎 venv 建议 3.11 |
| Node | 20+(仅构建前端) | 构建好的 `app/static/dist/` 不需要 Node |
| 磁盘 | ~10GB | MinerU venv ≈ 6GB + 模型 ≈ 3GB + 任务数据 |

CPU-only 机器也能用:把 `OT_PADDLE_DEVICE=cpu` 或让 MinerU 自动回落即可,速度约慢一个数量级。

---

## 1. 取代码

```bash
git clone https://github.com/<you>/paper2md.git
cd paper2md
```

---

## 2. 装 Web 服务(轻量,只有 fastapi + PyMuPDF)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## 3. 构建前端(产物进 `app/static/dist/`)

```bash
cd web
npm install --registry=https://registry.npmmirror.com   # 或官方源
npm run build
cd ..
```

> 前端没构建也能起服务,访问会看到 503 提示「前端尚未构建」。

---

## 4. 装转换引擎(二选一)

### 4.1 MinerU(推荐,默认)

MinerU 2.x 要求 `torch>=2.6,<2.8`。**单独建 venv**,不要装进系统或别的项目环境。

```bash
uv venv ~/venvs/mineru --python 3.11
# 没有 uv 就用:python3.11 -m venv ~/venvs/mineru

uv pip install --python ~/venvs/mineru/bin/python \
  "mineru==2.2.2" "torch==2.7.1" "torchvision==0.22.1" \
  -i https://pypi.tuna.tsinghua.edu.cn/simple

uv pip install --python ~/venvs/mineru/bin/python \
  boto3 click loguru "pdfminer.six==20250506" tqdm pypdfium2 pypdf reportlab pdftext \
  modelscope huggingface-hub json-repair fast-langdetect "scikit-image>=0.25" openai \
  "beautifulsoup4>=4.13.5" ultralytics "doclayout_yolo==0.0.4" dill PyYAML ftfy \
  shapely pyclipper omegaconf transformers "onnxruntime>1.17" \
  -i https://pypi.tuna.tsinghua.edu.cn/simple

# 服务器没有图形库时,opencv 要用 headless 版
uv pip uninstall --python ~/venvs/mineru/bin/python opencv-python
uv pip install --python ~/venvs/mineru/bin/python --no-deps opencv-python-headless
```

模型首次运行自动下载到 `~/.cache/modelscope`(约 2.8GB)。国内访问 HuggingFace 不通,
所以下文的 `OT_MINERU_MODEL_SOURCE=modelscope` 是默认值。

验证:

```bash
~/venvs/mineru/bin/mineru --help | head -5
```

### 4.2 PaddleX(备选,依赖少)

```bash
conda create -n paddle python=3.11 -y
conda activate paddle
pip install "paddlex[ocr]" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

首次转换会自动下载版面/表格/公式模型(几百 MB ~ 1GB)。
把 `OT_PADDLE_PYTHON` 指到 `~/anaconda3/envs/paddle/bin/python` 即可。

---

## 5. 配置与启动

所有配置都用环境变量,默认值不含任何个人路径:

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `OT_ENGINE` | `MinerU` | 默认引擎:`MinerU` / `PP-StructureV3` / `PaddleOCR-VL` |
| `OT_HOST` / `OT_PORT` | `0.0.0.0` / `8300` | 监听地址 |
| `OT_DATA_DIR` | `./data` | 任务与产物目录 |
| `OT_MINERU_PYTHON` | `~/venvs/mineru/bin/python` | MinerU venv |
| `OT_MINERU_BIN` | `~/venvs/mineru/bin/mineru` | MinerU CLI |
| `OT_MINERU_MODEL_SOURCE` | `modelscope` | 模型源;能上 HF 可改 `huggingface` |
| `OT_MINERU_VRAM_MB` | `16000` | MinerU 显存上限 |
| `OT_PADDLE_PYTHON` | `~/anaconda3/envs/paddle/bin/python` | 备选引擎解释器 |
| `OT_PADDLE_DEVICE` | `auto` | `auto` 自动挑卡 / `cpu` / `gpu:1` |
| `OT_PADDLE_GPU_MEM_MB` | `16384` | 备选引擎显存上限,同时是选卡阈值 |
| `OT_JOB_TIMEOUT_SEC` | `14400` | 单任务超时 |
| `OT_PYTHON` | `.venv/bin/python` | `run.sh` 用的 Web 解释器 |

启动:

```bash
./start.sh                 # 幂等:已在跑就跳过;顺带检查 frp(可选)
# 或前台:
OT_ENGINE=MinerU ./run.sh
```

看到 `GET /health 200` 即就绪。冒烟测试:

```bash
curl -sF "file=@some.pdf" http://127.0.0.1:8300/api/jobs | tee /tmp/j.json
JOB=$(python3 -c "import json;print(json.load(open('/tmp/j.json'))['job_id'])")
curl -sX POST http://127.0.0.1:8300/api/jobs/$JOB/start
# 轮询
curl -s http://127.0.0.1:8300/api/jobs/$JOB | python3 -m json.tool | head -20
```

---

## 6. 常驻运行(systemd)

```bash
sudo cp deploy/paper2md.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now paper2md
journalctl -u paper2md -f
```

> 服务以哪个用户跑,`~/venvs/mineru` 就要装在那个用户下。

---

## 7. 反向代理 + 访问控制

**本项目没有登录鉴权**(任何能访问 8300 的人都能上传/删除任务),公网暴露前请务必加一层:

```nginx
server {
    listen 443 ssl;
    server_name md.example.com;

    client_max_body_size 220m;      # 上传上限 200MB

    location / {
        auth_basic           "paper2md";
        auth_basic_user_file /etc/nginx/.htpasswd;   # htpasswd -c 生成

        proxy_pass         http://127.0.0.1:8300;
        proxy_set_header   Host $host;
        proxy_read_timeout 3600s;   # 转换是长任务,别让网关先掐断
    }
}
```

Caddy 版本见 `deploy/Caddyfile.example`。

内网穿透(frp)同理:配置文件 `frp/frpc.toml` 含服务器地址与 token,**已在 .gitignore 里排除**,
不要提交。

---

## 8. 故障排查

| 现象 | 原因 / 处理 |
| --- | --- |
| `/health` 里 `engine.mineru.available=false` | `OT_MINERU_PYTHON` 路径不对,或没建 venv |
| 转换失败,日志含 `NVIDIA driver too old` | torch 版本高于驱动支持。MinerU 必须 `torch<2.8`;装 2.7.1+cu126 |
| 转换失败,日志含 `OutOfMemoryError` | 卡被占满。用 `OT_PADDLE_DEVICE=gpu:N` 指定空闲卡,或调小 `OT_*_VRAM_MB` |
| 日志含 `libxcb.so.1` / `libXext.so.6` | 服务器缺 X 库,装 `opencv-python-headless` 替代 `opencv-python` |
| 日志含 `Invalid port: ':1]'`(老版本) | shell 的 `no_proxy` 里有 `[::1]`,httpx 解析崩;把方括号项去掉 |
| 模型下载卡住 | `OT_MINERU_MODEL_SOURCE=modelscope`;或手动下到 `~/.cache/modelscope` |
| 页面 503「前端尚未构建」 | 在 `web/` 下 `npm install && npm run build` |
| 转换很慢 | 确认命中了 GPU(任务卡片里显示 `MinerU · gpu:N`);回落 CPU 会慢一个数量级 |
| 进度长时间停在「加载模型」 | 正常:模型加载固定 30~60 秒,之后按页推进 |

---

## 9. 运维

- 任务数据都在 `OT_DATA_DIR/jobs/<id>/`,删任务会连产物一起删;
- 单个任务目录 = 源 PDF + `out/`(md + imgs)+ `<stem>-md.zip`,12 页论文约 10MB;
- 想换引擎/参数重转:任务卡片上的「重新转换」(源 PDF 保留,旧产物自动清理);
- 升级:`git pull` → `cd web && npm run build` → 重启服务;
  引擎升级另需更新对应 venv。
