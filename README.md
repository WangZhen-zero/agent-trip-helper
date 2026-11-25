# 行知 · 国内多城市旅行助手

这是一个可本地运行的 Vue 3 + TypeScript / FastAPI 应用。它使用“独立出发城市 + 1–3 座旅游城市”：出发城市只用于首段交通，不生成游玩日程。景点、天气、酒店、交通和行程规划采用固定职责模块；天气通过 Open-Meteo 获取，铁路计划车次通过 RailGo 查询，地图服务提供其他交通方式与市内接驳参考，模型只整合已验证事实。

这是一条可观测的工作流，不把每个模块都描述成会自主推理的 Agent。首版不包含账户、数据库、票务、酒店库存或预订；交通建议和预算均为参考估算。

## 运行要求

- Anaconda / Miniconda，Python 3.11（Python 3.10+ 亦可）
- Node.js 22.12+ 与 npm；本项目已用 Node 24 验证构建。

## Conda 环境

在项目根目录执行：

```powershell
conda env create -f environment.yml
conda activate agent-trip-helper
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

另开一个终端：

```powershell
conda activate agent-trip-helper
cd frontend
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:5173`。默认 `DEMO_MODE=true`，无需任何密钥，且页面不会请求外部地图、图片或模型服务。

如果 Conda 报 `NoWritablePkgsDirError`，说明其包缓存目录不可写，不是 `environment.yml` 有问题。可在当前 PowerShell 会话将缓存设为用户可写目录后重试：

```powershell
$env:CONDA_PKGS_DIRS = "$env:USERPROFILE\.conda\pkgs"
conda env create -f environment.yml
```

也可让管理员修复 Anaconda 安装目录中 `pkgs` 的写权限。不要以管理员身份长期运行开发工具来规避该问题。

## 配置真实服务

将根目录 `.env.example` 复制为 `.env`，只在 `.env` 中填写真实值，并设置 `DEMO_MODE=false`：

```powershell
Copy-Item .env.example .env
```

| 配置项 | 用途 | 是否必须 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek 模型 API 密钥，只发送到后端 | 是 |
| `LLM_MODEL_ID`、`LLM_BASE_URL` | DeepSeek 模型名与兼容 API 地址 | 是（有默认值） |
| `AMAP_WEB_SERVICE_KEY` | 服务端高德地理编码、POI、距离及备用路径规划 | 是 |
| `BAIDU_MAP_AK` | 百度地图 Web API；地图跨城方式参考优先，市内失败时备用 | 否；缺失时仍可用高德 |
| `ROUTE_TOKEN_SECRET` | 按天接驳凭证签名；多进程部署时各进程必须相同 | 单进程本地运行可不填 |
| `RAILGO_ENABLED` | 是否查询 RailGo 的非商业铁路时刻数据 | 默认 `true`；商业用途须关闭 |
| `VITE_AMAP_JS_KEY`、`VITE_AMAP_SECURITY_JS_CODE` | 浏览器端高德 JS 地图 | 真实地图时需要 |

`VITE_` 前缀变量会被 Vite 打包到浏览器，因此**只能**放高德 JS 地图专用、受域名限制的 Key；不得填入 DeepSeek 或高德 Web 服务 Key。前端通过 `frontend/vite.config.ts` 从项目根目录读取 `.env`，但只暴露 `VITE_` 前缀。

DeepSeek API 与 ChatGPT Plus 是两套独立计费体系，需在 DeepSeek 开放平台创建并充值 API Key。真实模式需要 DeepSeek 与高德 Web 服务 Key。高德 Key 需开通 Web 服务路径规划权限；百度 AK 可选。未取得图片展示授权前，景点和酒店只显示本地占位，景点可跳转高德查看地点。

规划页用同一张路线卡和同一个城市搜索框选择出发地与可排序的 1–3 座旅游城市。AI 助手由工具栏图标打开侧栏；结果页按天切换卡片，展示相邻景点的交通建议。地图只标记地点和城市访问顺序，不绘制导航道路折线。窄屏下助手以底部抽屉显示，界面动画遵循系统的“减少动态效果”设置。

## 接口、MCP 与数据边界

- `POST /api/v1/trips/plan/stream`：接收一座独立出发城市、1–3 座按用户顺序排列的旅游城市与 1–14 天日期范围；出发日最多提前 15 天。SSE 按序推送 `attractions`、`weather`、`hotels`、`planning`、`transport`、`warning`、`complete` 或 `error`。生成阶段只查询跨城交通，市内接驳留到查看具体日期时查询。
- `POST /api/v1/cities/validate`：手工城市添加前的校验接口。演示模式使用内置中国大陆城市级名录；真实模式再通过 MCP 和高德地理编码确认，服务异常不会被误报为“不存在”。
- `POST /api/v1/weather/forecast`：按已验证的中国大陆城市返回 Open-Meteo 逐日预报。
- `POST /api/v1/transport/plan`：按两个中国大陆城市、日期和人数返回 RailGo 日期核验车次及地图交通方式参考；最多三条铁路班次建议，不返回原始铁路接口数据。
- `POST /api/v1/transport/local/day`：用规划结果内服务端签发的日程凭证，按需查询该天景点间交通；凭证有效期 24 小时，响应在服务端缓存 10 分钟。生成主行程时不批量查询市内接驳。
- `POST /api/v1/photos/resolve`：旧客户端兼容入口，仅验证已签发凭证并返回无图；新前端不调用。获得合规的国内图片展示授权后才会重新启用实景图片。
- `POST /api/v1/assistant/chat/stream`：无状态、流式的旅行建议对话；不会直接改写行程。
- `GET /api/v1/aviation/search`：查询本地 OpenFlights 国内机场/航司基础资料快照，不表示航班运营状态。
- `GET /api/v1/health`：返回演示/真实模式状态。
- `python -m mcp_servers.amap_server`、`python -m mcp_servers.baidu_server`、`python -m mcp_servers.openmeteo_server` 与 `python -m mcp_servers.railgo_server`：可作为 stdio FastMCP 服务独立运行；应用默认通过 `fastmcp.Client(server)` 在进程内连接，仍只经由工具接口获取外部数据。

模型只能选择服务端查询到的 POI ID；坐标、天气和酒店归属由服务端填充。模型输出不符合日期、城市顺序、已知 POI、自由活动比例或预算结构时会被拒绝，最多再尝试一次修复。前端默认只显示热门城市，其他中国大陆城市需搜索或手工校验后加入。具体铁路车次只来自 RailGo 日期核验结果，显示计划时刻和查询时间，不代表余票或可预订状态；地图数据不冒充具体班次。没有获许可的航班时刻来源时不提供航班号。

铁路时刻查询使用 RailGo 非商业接口；它要求公开展示时显著标注来源、禁止商业使用及原始 API 中转。公开服务若增加收费、广告或返佣，应先关闭 `RAILGO_ENABLED` 并取得相应授权。[RailGo 使用限制](https://api.railgo.dev/) 不直接抓取 12306、验证码页面或其他未确认许可的票务站点；预留的采集适配器只有确认具体页面的自动访问及展示授权后才能启用。[12306 服务条款](https://kyfw.12306.cn/otn/regist/rule)

地图跨城参考优先百度，失败时用高德；百度权限错误 `240` 在当前进程进入冷却，不重复请求。市内按天优先高德，失败时尝试百度；短途最多三段可补充高德骑行时长。公开接口仅返回建议摘要，不返回逐站步骤或导航折线。高德公交 `cost` 和百度 `price` 均仅为供应商参考费用；驾车 `tolls` 只代表道路通行费，**不是**含燃油、停车等开销的驾车总费用。RailGo 不提供票价时价格保持未知。预算总额仍为规划估算，供应商已报价的城际金额另列，不重复计入。

## 验证与诊断

以下命令均不调用付费 API；后端测试通过模拟 HTTP 和进程内 MCP 服务验证工作流：

```powershell
conda activate agent-trip-helper
cd backend
python -m pytest tests -q
python -m app.diagnose
python -m app.diagnose --no-env

cd ..\frontend
npm run test
npm run build
```

`python -m app.diagnose` 只显示版本、依赖是否存在和“是否已配置”布尔值，不输出 API Key、认证头或 `.env` 内容。诊断里 `hello-agents` 与 `openai` 为未安装是预期结果：项目不再依赖它们。

若要执行浏览器端到端测试，首次需安装 Playwright Chromium：

```powershell
cd frontend
npx playwright install chromium
$env:TRIP_TEST_PYTHON = "python"
npm run test:e2e
```

端到端测试以演示模式启动独立后端，并阻止外部网络请求。若当前 Conda 环境的 Python 不在 `PATH`，把 `TRIP_TEST_PYTHON` 改为该环境 `python.exe` 的完整路径。

## 常见问题

“未安装 hello-agents”曾是旧实现对任意 `ImportError` 的错误归因。实际安装的 `hello-agents 1.0.0` 没有旧代码导入的 `MCPTool`，因此反复安装同一版本无效。当前版本移除了 HelloAgents 强制依赖，使用 Python 异步编排、FastMCP 和 DeepSeek HTTP API；无需卸载旧包，重启后端并安装新的 `backend/requirements.txt` 即可。

若 DeepSeek 返回“行程未通过校验”，表示模型的 JSON 已返回、但日期、城市顺序、POI ID、字段类型或预算未满足服务端契约，并非 API Key 一定失效。后端现在会给模型一次包含具体原因的修正机会；再次失败时，页面和后端日志只显示脱敏的校验原因，不记录模型原文或密钥。可依据提示重试；若长行程持续失败，可先缩短天数并检查检索到的景点是否足够。不要为了消除该错误关闭 POI/日期校验。

固定的 FastMCP 版本导入 Authlib 旧接口时可能出现 `AuthlibDeprecationWarning`，它与 DeepSeek 行程校验无关。应用只在 FastMCP 导入时过滤两条已确认的 Authlib 弃用提示；其他警告仍保留。后续升级 FastMCP 大版本前应先运行 MCP 和规划回归测试。

真实联调需要你自己的 DeepSeek、高德凭据；RailGo 不需要 Key，但必须遵守非商业使用限制和限速。请勿把 `.env`、终端中包含密钥的 URL 或截图提交到仓库或粘贴到问题报告中。
