# AI 经纪人

面向娱播公会的主播自动巡检与预警项目。系统从公会后台读取正在直播的主播数据，根据统一规则筛选预警对象，录制 60 秒直播素材，调用火山方舟多模态模型进行五维分析，并把结构化结果写入本地 WPS 表格、飞书多维表工作流和企业微信群。

本项目与“直播数据导出”的业务和数据目录相互独立：不读取分钟趋势数据，也不参与历史场次汇总；两者只共用新心和中鼎的 Edge 登录态，避免同一后台重复登录。

## 一、业务目标

核心目标不是评价主播好坏，而是尽快发现影响直播间停留、互动和付费转化的可执行问题。

当前分析维度由 `analysis_config.json` 统一控制，默认包括：

- 运营维度
- 调试维度
- 妆造维度
- 才艺维度
- 声乐维度

预警规则同样只从 `analysis_config.json` 读取。修改规则、录制时长、AI 并发、提交间隔、输出渠道或分析维度时，不需要修改 Python 源码。

## 二、完整流程

```text
检查新心和中鼎共享 Edge
  -> 分别读取两个后台的跟播数据并合并
  -> 按开播时长、累计观看和音浪筛选
  -> 录制 60 秒视频、音频和截图
  -> 调用多模态 AI 分析
  -> 校验并保存结构化 JSON
  -> 写入当日本地 WPS 表格
  -> POST 到飞书多维表工作流
  -> 汇总新增预警主播并通知企业微信群
  -> 保存已分析状态，避免当天重复分析
```

更完整的业务过程、演进记录和项目心得见 [docs/AI经纪人项目完整流程.md](docs/AI经纪人项目完整流程.md)。

## 三、目录结构

```text
AI经纪人/
├─ ai_broker/                     Python 业务代码
│  ├─ main.py                     命令行入口
│  ├─ pipeline.py                 主流程编排
│  ├─ exporter.py                 从 Edge 后台导出实时主播数据
│  ├─ rules.py                    预警筛选规则
│  ├─ capture.py                  视频、音频和截图采集
│  ├─ ai_client.py                AI 请求、提示词、重试和结果解析
│  ├─ outputs.py                  WPS、飞书和企业微信输出
│  ├─ state.py                    当日已分析状态
│  ├─ paths.py                    数据目录管理
│  ├─ config.py                   配置读取
│  └─ utils.py                    通用函数
├─ scripts/ai_broker.ps1          Windows 运行器
├─ analysis_config.json           唯一业务配置入口
├─ START_MONITOR.cmd              日常双击启动入口
├─ requirements.txt               Python 依赖
├─ daily_data/                    历史数据和每日运行数据
├─ docs/                          流程文档和 HTML PPT 源文件
├─ AI经纪人PPT_离线演示包/         可复制到其他电脑的离线演示包
└─ README.md                      本说明
```

Edge 登录目录由同级的“直播数据导出”项目维护，AI 经纪人只通过调试端口连接，不创建自己的浏览器用户目录。

## 四、环境要求

- Windows 10/11
- Python 3.11 或更高版本
- Microsoft Edge
- 可用的抖音直播服务平台机构账号
- 可访问火山方舟接口的 `ARK_API_KEY`
- `ffmpeg` 由 `imageio-ffmpeg` 提供

安装依赖：

```powershell
cd "AI经纪人"
python -m pip install -r requirements.txt
python -m playwright install chromium
```

配置火山方舟密钥：

```powershell
[Environment]::SetEnvironmentVariable("ARK_API_KEY", "你的密钥", "User")
```

重新打开终端后生效。不要把密钥写进代码或提交到 Git。

## 五、首次运行

1. 双击 `../直播数据导出/START_EDGE_新心.cmd`，在打开的 Edge 中登录新心后台。
2. 双击 `../直播数据导出/START_EDGE_中鼎.cmd`，在打开的 Edge 中登录中鼎后台。
3. 保持两个 Edge 窗口开启。
4. 双击本项目的 `START_MONITOR.cmd`，程序会检查两个登录态并按配置周期自动运行。

日常运行只需要双击：

```text
START_MONITOR.cmd
```

关闭窗口或按 `Ctrl+C` 即停止监控。

## 六、常用命令

在 `AI经纪人` 目录执行。

完整运行一轮：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ai_broker.ps1 -Mode RunOnce
```

只预览一名预警主播，不调用 AI：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ai_broker.ps1 -Mode Preview
```

只导出实时主播 CSV：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ai_broker.ps1 -Mode Export
```

检查两个共享 Edge 是否可连接：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ai_broker.ps1 -Mode CheckEdges
```

按配置周期持续监控：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ai_broker.ps1 -Mode Monitor
```

## 七、配置说明

所有日常配置集中在 `analysis_config.json`。

### `data_root`

```json
"data_root": "daily_data"
```

每日素材、日志、AI JSON、状态和表格都保存在项目内的 `daily_data`。

### `ark`

配置模型、接口地址、温度、最大输出长度和推理强度。API 密钥优先从 `api_key_env` 指定的环境变量读取。

### `browsers`

每个键是写入结果的后台名称。新心连接 `http://127.0.0.1:9223`，中鼎连接 `http://127.0.0.1:9224`；`page_url` 是各后台的实时跟播页面。新增后台时只需增加同结构配置，并为它准备独立的已登录调试端口。

### `capture`

控制分析素材的录制秒数、抽帧频率、视频宽度、输出帧率、压缩质量和音频码率。

### `warning_rule`

- `min_live_seconds`：达到该开播时长后才参与预警判断。
- `max_total_users`：累计观看低于该值时命中。
- `max_income`：音浪低于该值时命中。

具体组合逻辑以 `ai_broker/rules.py` 为准。

### `runtime`

- `ai_concurrency`：AI 并发数，`all` 表示对本轮任务不额外设上限。
- `capture_concurrency`：录制并发数。
- `ai_submit_interval_seconds`：AI 请求提交间隔。
- `monitor_interval_minutes`：监控循环间隔。

### 输出配置

- `local_table`：本地 WPS/Excel 文件。
- `table_webhook`：飞书多维表工作流 webhook。
- `wechat_summary`：企业微信群机器人和表格链接。

建议生产环境只填写 `url_env`，把 webhook 放在用户环境变量中；配置文件中的明文 webhook 不应上传到公开仓库。

## 八、数据目录

```text
daily_data/YYYYMMDD/
├─ exports/              两个后台合并后的实时主播 CSV
├─ clips/                视频、音频和截图
├─ request_previews/     AI 请求预览
├─ ai_results/           结构化 AI JSON
├─ analysis_table/       当日 WPS/Excel 表格
├─ state/                当日已分析状态
└─ logs/                 运行日志
```

历史 `daily_data` 已完整保留。状态文件中的相对路径仍以本项目根目录为基准，移动整个 `AI经纪人` 文件夹不会破坏数据引用。

## 九、去重与失败处理

- 当日已成功分析的主播会按“后台 + 主播 ID + 直播间 ID”写入状态文件，同一天后续轮次不会重复处理，也不会把两个后台的同 ID 主播混为一人。
- 某个后台当前没有开播主播时记录为 0 条并继续处理另一个后台；连接、权限或接口错误仍会中止并写入日志。
- 录制、AI、飞书或企业微信失败会写入当日日志。
- AI 请求包含超时和重试逻辑。
- 本地 JSON 和表格先落盘，外部 webhook 失败不会删除本地结果。
- 需要重新分析当天主播时，使用 Python 入口的 `--rerun-today`，操作前应确认不会造成重复写表和重复通知。

## 十、常见问题

### 无法连接 Edge

先在“直播数据导出”项目分别启动新心和中鼎 Edge，再执行 `CheckEdges`。新心应能访问 `http://127.0.0.1:9223/json/version`，中鼎应能访问 `http://127.0.0.1:9224/json/version`。

### 后台要求重新登录

必须在“直播数据导出”项目启动的两个调试 Edge 中分别登录。普通 Edge 和 Chrome 的登录态不会自动共享。

### AI 超时或接口无返回

检查 `ARK_API_KEY`、账户余额、模型端点、网络代理和当日日志。不要把余额不足误判为代码故障。

### 飞书或企微没有收到数据

先检查本地 `ai_results` 和 `analysis_table` 是否生成，再检查 webhook 是否有效、字段类型是否匹配以及机器人是否仍在群内。飞书表中如需区分数据来源，应新增文本字段“后台”，并在工作流中映射 webhook 的同名值。

## 十一、维护原则

- 业务规则只改 `analysis_config.json`，避免在多个模块重复维护阈值。
- 新增分析维度时同步调整提示词、结构化 JSON 和表格字段。
- `daily_data`、密钥和 webhook 不提交到公开 Git；共享 Edge 用户目录由“直播数据导出”项目忽略。
- 修改公共流程后至少执行一次 `Preview` 和一次小规模 `RunOnce`。
- 本项目不引用 `../直播数据导出` 中的代码或业务数据，仅复用其已启动的 Edge 调试会话。
