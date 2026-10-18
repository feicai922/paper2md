# paper2md

自托管的 **PDF → Markdown** 转换台:上传 PDF → 点「开始转换」→ 在线预览 / 下载
**Markdown**(标题层级、段落、公式 LaTeX、表格、插图按原位置保留)。

[![部署指南](https://img.shields.io/badge/部署-DEPLOY.md-blue)](DEPLOY.md)
[![引擎](https://img.shields.io/badge/引擎-MinerU%20%2F%20PaddleX-green)](#9-引擎对比2026-10-实测)

> 默认引擎 **MinerU**:版面检测 → 公式(UniMERNet)/表格识别 → 对**带文字层的
> PDF 直接取文字**(不重新 OCR,所以没有 OCR 错字)→ 合成 Markdown。
> 另有 **PaddleX PP-StructureV3**(快、依赖少)与 **PaddleOCR-VL**(VLM)可切换。

---

## 1. 它做什么

```
浏览器 ──上传──> ocr-translate(:8300) ──存本地,不启动──┐
                                                       │ 用户点「开始转换」
                                                       ▼
                                      ① 任务进串行队列(共享 GPU,一次一个)
                                      ② 子进程(MinerU / PaddleX,按任务选)
                                         版面检测 → 公式/表格识别 → 合成 Markdown
                                      ③ 合并成一篇 md(页间 --- 分隔)
                                      ④ 打包 zip(md + imgs/)+ 入库
                                                       │
                                                       ▼
                                        在线渲染预览(公式 KaTeX)/ 下载 / 归档
```

### 产物

| 产物 | 内容 |
| --- | --- |
| `xxx.md` | 正文。标题是 `#`/`###`,公式 `$…$` / `$$…$$`,表格是 HTML `<table>`,插图内联 `imgs/*.jpg`;页与页之间 `---` 分隔并带 `<!-- 第 N 页 -->` |
| `xxx-md.zip` | 上面这份 md + `imgs/`(插图/表格/公式裁剪图,统一 **jpg**,不再是打不开的 jpx)+ `README.md` 索引 |

### 实测质量(2026-10,12 页 IEEE 论文,MinerU)

- 正文取自 PDF 文字层,没有 OCR 错字;标题层级、两栏阅读顺序正确;
- 公式输出为 LaTeX(`$$S_{row}=\mathrm{Softmax}(...)$$`),上下标结构正确;
- 表格为 HTML `<table>`(可直接显示、内容可复制);
- 插图按原位置内联,并保留图注;
- 速度:**1 分 37 秒 / 12 页**(含约 45 秒模型加载),之后约 1 秒/页。

---

## 2. 为什么不用 markitdown

试过同一份 PDF,`markitdown` 的 PDF 转换走 pdfminer 纯文本抽取:

- 两端对齐的正文被**误判成 Markdown 表格**(一行一个 `|` 表格);
- 没有阅读顺序概念,两栏论文会串行;
- 不导出图片、不识别表格结构、不认公式。

所以它修不了"排版丑、图片表格丢失"的问题。同类里真正合适的只有版面分析类引擎:
**PaddleX PP-StructureV3**(本机已缓存模型,零下载)、MinerU、Docling。这里选了
PaddleX:已有环境、已有模型,且能直接导出 Markdown。

---

## 3. 功能

- **单文件 / 批量**:一次最多 20 个 PDF,进同一个串行队列(共享 GPU,并发会 OOM);
- **真实进度**:解析 worker 的 `PROGRESS k/N`,按页推进(不是假进度条);
- **在线预览**:Markdown 真渲染(标题/表格/图片/KaTeX 公式),图片走
  `/api/jobs/{id}/images/...` 提供;
- **归档**:按日期分组,可搜索、下载、删除;
- **取消 / 删除**:取消会杀掉转换子进程;
- **重新转换**:已完成的任务可以换引擎/改参数后一键重转(源 PDF 保留,旧产物自动清理);
- **引擎可选**:MinerU(默认)/ PaddleX 标准 / PaddleX 精细,转换前在界面上选;
- **自愈**:服务重启后,排队中/转换中的任务自动重新排队。

---

## 4. 目录结构

```
paper2md/
├── app/
│   ├── main.py                 FastAPI:上传/提交/进度/预览/图片/下载/归档/SPA
│   ├── config.py               配置(引擎、显存上限、超时;默认值只依赖 $HOME)
│   └── services/
│       ├── jobs.py             串行队列 worker:起子进程、解析进度、打包、自愈
│       ├── mineru2md.py        **默认 worker**:MinerU venv 跑 pipeline(文字层+公式+表格)
│       ├── pdf2md.py           备选 worker:paddle 环境跑 PP-StructureV3 / PaddleOCR-VL
│       ├── md_export.py        打包 md + imgs → ZIP
│       └── probe_device.py     探测哪张 GPU 真能跑 Paddle(子进程内)
├── web/                        Vue 3 + Vite(Markdown 渲染 = markdown-it + KaTeX)
├── deploy/                     systemd / Caddy 示例
├── data/jobs/<id>/             每个任务:source.pdf、out/(md + imgs)、xxx-md.zip
├── DEPLOY.md                   自部署指南(引擎安装、反代、排障)
├── run.sh                      启动 Web 服务(:8300)
├── start.sh                    一键启动(幂等;顺带检查 frp,可选)
├── stop.sh                     停止 Web 服务 + frp + 残留转换进程
└── requirements.txt            fastapi / uvicorn / python-multipart / PyMuPDF
```

---

## 5. 启动

完整步骤(含引擎安装)见 **[DEPLOY.md](DEPLOY.md)**,最短路径:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd web && npm install && npm run build && cd ..      # 构建前端
./start.sh                                          # 起服务(:8300)
./stop.sh                                           # 停止
```

**依赖**:Web 侧只需 fastapi/uvicorn/multipart/**PyMuPDF**;
转换引擎另装独立 venv(MinerU 默认,见 DEPLOY.md)。

前端改动后:

```bash
cd web && npm install --registry=https://registry.npmmirror.com && npm run build
```

---

## 6. 配置(环境变量)

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `OT_HOST` / `OT_PORT` | `0.0.0.0` / `8300` | UI 监听地址 |
| `OT_DATA_DIR` | `./data` | 任务与产物目录 |
| `OT_ENGINE` | `MinerU` | 默认引擎:`MinerU` / `PP-StructureV3` / `PaddleOCR-VL` |
| `OT_MINERU_PYTHON` | `~/venvs/mineru/bin/python` | MinerU 专用 venv(torch 2.7 + mineru 2.2.2) |
| `OT_MINERU_BIN` | `~/venvs/mineru/bin/mineru` | MinerU CLI |
| `OT_MINERU_MODEL_SOURCE` | `modelscope` | 模型源(HF 在本机被墙) |
| `OT_MINERU_VRAM_MB` | `16000` | MinerU 单进程显存上限 |
| `OT_PADDLE_PYTHON` | `~/anaconda3/envs/paddle/bin/python` | 备选引擎的 python(需 paddlex) |
| `OT_PADDLE_PIPELINE` | `PP-StructureV3` | 版面分析管线;可换 `PaddleOCR-VL` / `OCR`(会丢版面) |
| `OT_PADDLE_DEVICE` | `auto` | `auto` 自动挑卡 / `cpu` / `gpu:4` |
| `OT_PADDLE_GPU_MEM_MB` | `16384` | 单任务显存上限;**同时决定选卡阈值**(上限 + 1GB 空闲) |
| `OT_PADDLEX_HOME` | `~/model_zoo/paddlex` | 模型目录 |
| `OT_JOB_TIMEOUT_SEC` | `14400` | 单任务超时,超时杀子进程 |
| `OT_PYTHON` | retain-pdf 的 venv | `run.sh` 用的解释器(仅 app 侧依赖) |

上传上限 200MB/文件,单批最多 20 个(`main.py` 顶部常量)。

---

## 7. HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 自身状态 + 引擎可用性(管线 / 设备策略 / 解释器) |
| POST | `/api/jobs` | 上传单个 PDF(multipart `file`),只入库 |
| POST | `/api/batches` | 批量上传(multipart `files`) |
| POST | `/api/jobs/{id}/start` | 提交进转换队列 |
| POST | `/api/batches/{id}/start` | 批量提交 |
| GET | `/api/jobs` / `/api/jobs/{id}` | 任务列表 / 详情(含 `downloads`) |
| GET | `/api/jobs/{id}/preview` | Markdown 预览(图片 URL 已改写到 `/images/`) |
| GET | `/api/jobs/{id}/images/{name}` | 预览用插图(限 `out/imgs/`,防目录穿越) |
| GET | `/api/jobs/{id}/download/{key}` | `key` ∈ `markdown` / `md_zip` |
| POST | `/api/jobs/{id}/cancel` | 取消(杀转换子进程) |
| DELETE | `/api/jobs/{id}` | 删除任务及产物 |
| GET | `/api/archive` | 按日期分组的归档 |

---

## 8. 已知限制 / 踩过的坑

1. **串行转换。** 共享 GPU 上并发跑两个 PP-StructureV3 会直接 OOM,所以只有一个
   worker。批量提交会排队,前端会显示"其余排队中"。
2. **每个文档都要重新加载模型**(MinerU 约 45 秒,PaddleX 约 27 秒)。为了简单
   可靠,转换是一次性子进程;批量场景可以把 worker 改成常驻(后续可做)。
3. **显存与选卡。** 默认给单任务 16GB 上限,并据此挑卡(需要"上限 + 1GB"的空闲)。
   没有满足条件的卡会**回落 CPU**,速度慢一个数量级,界面上会提示。
4. **进度只在页级。** 模型加载阶段(前 30~60 秒)显示"加载模型…",之后按页推进。
5. **英文断词偶有粘连**(如 `respectively.Similarly`、`ABrief StudyofMachine`):
   这是 PaddleOCR 识别层的特性,不是 Markdown 合成问题。对公式/表格/图注影响不大,
   若要更干净可以在后处理里做规则补空格(未实现,避免误伤 `et al.`、
   `ResNet-50` 这类写法)。
6. **扫描件 / 图片型 PDF** 也能转,靠 OCR 识别文字;清晰度决定准确率。
7. **表格是 HTML `<table>`**,不是 Markdown 管道表格 —— 复杂跨行跨列只有 HTML 能
   表达。渲染器都支持;若要纯 md 表格,需要自己再做一次降级转换。
8. **服务没有登录鉴权**(按需求去掉)。经 frp 暴露公网时,建议在外面加一层
   Basic Auth,否则谁拿到地址都能上传/删除。
9. **`no_proxy` 里的 `[::1]`** 曾把子进程(httpx)搞崩;现在 app 侧不再有 httpx
   依赖,已不受影响(相关处理保留在 `local-stack/start-backend.sh` 供回退使用)。

---

## 9. 引擎对比(2026-10 实测)

同一份样本:某 IEEE 论文第 6~8 页(含 1 张结果表 + 2 个行间公式 + 1 张框架图)。

| 方案 | 文本质量 | 公式 LaTeX | 表格 | 图片 | 3 页耗时 | 部署成本 |
| --- | --- | --- | --- | --- | --- | --- |
| **MinerU 2.x**(默认) | ★★★ 文字层,零 OCR 错字 | ★★★ 结构完整(`K^{T}` 正确) | ★★ 11 行,个别行会并格 | ✅ 5 图 | GPU 52s / CPU 110s(含 45s 模型加载) | 重:独立 venv + torch 2.7 + 2.8G 模型 |
| **PaddleX PaddleOCR-VL** | ★★ 好,偶有 `H-MSA` 这类错 | ★★ `K^{T}` 正确 | ★★★ 表头最准 | ✅ 10 图(有冗余) | GPU 125s | 已有 |
| **PaddleX PP-StructureV3** | ★★ 好,偶有 `self-atention` | ★ 上标出错(`K^{†}`) | ★★ 11 行,表头合并 | ✅ 6 图 | GPU 51s | 已有 |
| **PyMuPDF4LLM** | ★★★ 文字层 | ❌ 完全不输出公式 | ★ 管道表,表头被竖排标题污染 | ✅ 6 PNG | 4s | pip 一个包 |
| **markitdown** | ✗ 正文被当成表格 | ❌ | ❌ | ❌ | 快 | 已装 |

结论:

* **默认用 MinerU**:文字取自 PDF 文字层(没有 OCR 错字),公式是干净 LaTeX,
  表格能识别;固定约 45 秒模型加载,之后约 1 秒/页;
* 机器上装不了/不想装 MinerU 依赖 → 用 **PP-StructureV3**(依赖少,10~20 秒/页,
  偶有英文错字);
* 只看重文字和表格、不需要公式 → PyMuPDF4LLM 最快最准;
* markitdown 的 PDF 通道是 pdfminer 纯文本抽取,会把正文当表格、丢图片,不适用。

### MinerU 的安装(已装好,记录备查)

```bash
uv venv ~/venvs/mineru --python 3.11
# MinerU 2.x 要求 torch<2.8;本机 vLLM 环境的 torch 2.9+cu128 在驱动 12.9 上会报
# "NVIDIA driver too old",所以必须独立 venv + torch 2.7.1
uv pip install --python ~/venvs/mineru/bin/python "mineru==2.2.2" \
  "torch==2.7.1" "torchvision==0.22.1" -i https://pypi.tuna.tsinghua.edu.cn/simple
uv pip install --python ~/venvs/mineru/bin/python \
  boto3 click loguru pdfminer.six==20250506 tqdm pypdfium2 pypdf reportlab pdftext \
  modelscope huggingface-hub json-repair fast-langdetect scikit-image openai \
  beautifulsoup4 ultralytics doclayout_yolo==0.0.4 dill PyYAML ftfy shapely \
  pyclipper omegaconf transformers onnxruntime -i https://pypi.tuna.tsinghua.edu.cn/simple
uv pip install --python ~/venvs/mineru/bin/python --no-deps opencv-python-headless

# 模型随首次运行下载到 ~/.cache/modelscope(约 2.8G,现已缓存)
# 单独调试:
MINERU_MODEL_SOURCE=modelscope ~/venvs/mineru/bin/mineru \
  -p input.pdf -o out -b pipeline -d cuda:0 --vram 16000 --source modelscope
```
