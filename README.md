# RAG 旅游规划助手

一个使用 **Gradio + 千问 + 网页检索** 的旅游行程助手。输入城市、出发日期、天数、全程人均预算和出行人群，程序自动搜索攻略、读取正文，再生成带参考来源的行程。

支持：

- 按日期识别季节、中国法定节假日和调休背景，结合情侣、亲子、老年慢游等需求规划路线。
- 优先检索小红书；不足时补充公开旅游攻略和 Trip.com 同城旅行帖，以至少 **3 篇不同正文** 为目标，最多整合 5 篇。
- 展示真实攻略标题和链接；去重后的正文才计入资料数量，仅标题记录单独标注。
- 程序统一计算预算，输出七部分方案：整体安排、每日详细日程、预算检查、旅行前准备、待核实清单、变化时的替代安排、旅行建议。
- 按钮下方实时显示进度条和百分比；模型生成期间明确标注为估算进度。

## 运行条件

推荐使用 **Windows + Conda + Python 3.12 + Microsoft Edge**。小红书浏览器抓取使用本机 Edge；其他网页资料通过 HTTP 请求获取。

仓库按维护者授权提供 `shared_access.json`，程序自动读取其中的小组共享模型 Key 和小红书会话，新安装无需另填凭据。该文件随公开仓库发布，任何访问者均可使用；共享额度可能用尽，会话可能过期或被平台限制。默认模型和地址见下文，不代表永久免费。

## 下载与安装

[下载 ZIP](https://github.com/Ganyangyu/rag-travel-planner/archive/refs/heads/main.zip)，解压后进入包含 `start.py` 的文件夹。也可以使用 Git 克隆仓库：

```powershell
git clone https://github.com/Ganyangyu/rag-travel-planner.git
cd rag-travel-planner
```

在 Anaconda Prompt 或已初始化 Conda 的终端执行：

```powershell
cd "你的项目目录"
conda env create -f environment.yml
conda activate rag-travel-planner
```

环境已经创建过时，激活环境并更新依赖：

```powershell
conda activate rag-travel-planner
python -m pip install -r requirements.txt
```

如果当前终端无法识别 `conda`，请使用 Anaconda Prompt，或完成 Conda 的终端初始化后重新打开终端。

## 共享配置与个人覆盖

默认直接使用 `shared_access.json` 中的共享配置，安装完成后可直接运行 `python start.py`。不要修改或分享维护者日常浏览器的完整配置目录。

需要使用个人账号时，在**启动助手的同一个 PowerShell 窗口**设置自己的 Key：

```powershell
$env:DASHSCOPE_APIKEY="填写你自己的 API Key"
```

优先级：`DASHSCOPE_APIKEY` → `DASHSCOPE_API_KEY` → `shared_access.json`。个人 Key 和 Cookie 应放在环境变量中，不要提交到仓库；仓库内的共享配置是维护者明确授权发布的演示凭据。

默认配置：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `QWEN_MODEL` | `qwen4-max` | 需确认平台支持该模型 |
| `QWEN_BASE_URL` | `https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1` | 示例兼容服务地址；请使用与 Key 对应的服务 |
| `QWEN_ENABLE_THINKING` | `false` | 设为 `true` 开启思考，通常会增加等待时间 |

需要改用其他千问兼容服务时：

```powershell
$env:QWEN_MODEL="你的模型名称"
$env:QWEN_BASE_URL="https://你的服务地址/compatible-mode/v1"
```

`.env.example` 是配置说明，**程序不会自动加载 `.env` 文件**。上述 PowerShell 环境变量只在当前窗口有效。Anaconda Prompt 使用 `set DASHSCOPE_APIKEY=你的Key`。

## 启动与使用

```powershell
python start.py
```

终端出现“RAG 助手已就绪”后，浏览器会自动打开页面。默认地址为 [http://127.0.0.1:7860](http://127.0.0.1:7860)。运行期间保持终端开启；停止时按 `Ctrl+C`。

填写出行信息并点击“生成行程”，无需提供攻略 URL。每次提交都会重新按当前条件检索。示例：

| 输入 | 示例 |
|---|---|
| 目的地 | 上海 |
| 出发日期 | `2026-12-01` |
| 天数 | 5 |
| 全程预算 | 1000 元/人 |
| 出行人群 | 老年人 |

进度百分比在右侧持续显示。模型没有提供目标输出长度，生成阶段根据已接收内容量估算，最终整理完成后才显示 100%。

端口被占用时，先关闭旧服务，或指定另一个端口：

```powershell
$env:GRADIO_SERVER_PORT="7861"
python start.py
```

## 小红书登录

首次启动会自动把共享 Cookie 导入专用 Edge 会话，无需单独提供帖子链接。已有个人登录会话会优先保留；如果已设置自己的 `XHS_COOKIE` 环境变量，则使用个人 Cookie。

共享会话失效或需要改用自己的账号时，先登录专用浏览器：

```powershell
python -m src.crawler --login
```

在打开的 Edge 窗口内扫码或手动登录，完成后回到终端按 Enter。程序会检查搜索和详情正文读取结果，然后保存专用会话。**不需要向任何人提供密码或 Cookie。**

会话位于 `%LOCALAPPDATA%/RAGTravelPlanner/xhs-browser`，在项目目录之外；它与日常 Edge 的个人配置独立。分享代码时不要分享这个目录。会话失效后重新运行登录命令即可。

登录成功也不保证网站允许当前网络访问。遇到验证码应在网页正常完成验证；遇到 `300012` 等网络限制时，程序记录具体阶段并继续使用备用来源。没有可读正文的条目不冒充成功抓取。

## 预算口径与资料边界

- **预算是全程人均上限**。1000 元、5 天表示全程 1000 元/人；日均 200 元仅用于描述消费水平，不限制某一天的消费。
- 住宿按房价 × 房间数 × 晚数核算；按车费用先计算团队金额再折算人均，按人费用按适用人数核算；预留金额只加入计划总额一次。
- 当前表单没有人数、房间数和抵离时间字段。未知时明确采用**单人单间条件情景**，不会从“情侣”“老年人”等标签推断人数或合住。确定实际人数、房型和接驳费用后应重新核算。
- 预算包含目的地内住宿、餐饮、门票和普通市内交通；默认不包含跨城往返交通、机场或车站至住宿的接驳。一天行程按零晚住宿计算。
- 网页经验不是实时价格保证；未确认的票价、优惠、开放时间、交通细节和天气列入待核实清单。季节按北半球月份划分，不等于天气预报；节假日超出日历库收录年份时标为待确认。
- 三篇是检索目标，受公开页面可用性影响。实际不足时如实说明，不用重复页面或只有标题的记录凑数；资料不足仍提供需核实的候选行程。

## 项目结构

```text
.
├── app.py                 # 页面、输入回调、实时进度和来源展示
├── start.py               # 直接启动入口
├── src/
│   ├── config.py          # 环境变量配置
│   ├── profile.py         # 日期、季节假期、用户画像和检索词
│   ├── crawler.py         # 搜索、网页正文读取、去重与备用来源
│   ├── planner.py         # 千问调用、结构化方案和七部分输出
│   └── budget.py          # 统一预算计算
├── test/                  # 离线回归测试与独立联网测试
├── environment.yml        # Conda 环境定义
├── requirements.txt       # Python 依赖
├── .env.example           # 个人环境变量配置示例
├── shared_access.json     # 维护者授权发布的小组共享配置
├── LICENSE                # MIT 许可证
├── README.md              # 使用说明
└── report.md              # 方法与实验报告
```

## 测试与排查

离线回归测试不会发送模型请求：

```powershell
python -m unittest discover -s test -p "test_*.py" -v
```

以下为独立联网测试，API 测试会使用账号额度：

```powershell
python test/test_qwen.py
python test/test_crawler.py --city "上海" --date "2026-12-01" --days 5 --budget 1000 --audience "老年人"
python -m src.crawler --diagnose
```

| 现象 | 处理方法 |
|---|---|
| `No module named gradio` 等 | 确认已激活 `rag-travel-planner`，再运行依赖安装命令；VS Code 也要选择这个环境的解释器 |
| 模型请求失败或方案未完成 | 查看终端，检查 Key、服务地址、模型权限、账号额度和网络；接口与 Key 必须匹配 |
| 小红书没有正文 | 先运行登录命令，再用 `--diagnose` 区分加载、明确空结果、登录、验证和访问限制 |
| 长时间停在生成阶段 | 深度思考可能更慢；检查终端连接状态，模型进度是估算值而非剩余时间预测 |
| 浏览器未自动打开 | 保持终端服务运行，手动打开终端打印的本地地址 |

抓取能力依赖第三方网页当前结构和访问状态。使用抓取内容前应确认平台条款及内容授权；本项目仅保存必要的正文用于当前行程整合，不承诺所有城市、平台或网络环境均可访问。

## 许可证

项目代码采用 MIT 许可证。第三方攻略、笔记内容和服务访问权限不由本项目许可证授予。共享配置可能由维护者更新或撤销，不能保证长期可用。
