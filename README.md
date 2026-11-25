# 简明ETF / Jianming ETF

简明ETF 是一套 A 股 ETF 行情、策略研究和模拟交易工具。项目包含 FastAPI 后端、浏览器前端、策略引擎、历史行情种子、研究报告和回归测试。

- 查看 ETF 行情、指标、策略信号和持仓依据。
- 比较策略历史净值、回撤、基准和年度表现。
- 用独立模拟账户跟踪 D0 和 D0I-BOND-WW 的调仓与模拟成交。
- 查阅个股、行业和境外 ETF 的研究资料。

## 本地运行

使用 Python 3.12。在仓库根目录执行以下命令。

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r production/requirements.lock
export ETF_WEB_AUTO_REFRESH=0
export ETF_SECTOR_RESEARCH_AUTO_UPDATE=0
python production/server.py --set-password
python production/server.py
```

在 Windows PowerShell 中使用以下命令。

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --require-hashes -r production/requirements.lock
$env:ETF_WEB_AUTO_REFRESH = '0'
$env:ETF_SECTOR_RESEARCH_AUTO_UPDATE = '0'
& .\.venv\Scripts\python.exe production/server.py --set-password
& .\.venv\Scripts\python.exe production/server.py
```

浏览器打开 `http://127.0.0.1:8765`，使用刚设置的口令登录。账户、设置和缓存默认写入 `runtime-data/`。可设置 `SIMPLE_ETF_HOME` 使用其他目录。上面的启动命令会关闭后台行情刷新，适合先用仓库自带数据体验。

如需微信提醒，可通过 `PUSHPLUS_TOKEN` 或 `PUSHPLUS_TOKEN_FILE` 提供自己的推送加令牌，然后在登录后的模拟账户页面发送测试消息并选择订阅。

## D0 EMTL 拟单与只读检查

[`scripts/emtl_d0.py`](scripts/emtl_d0.py) 可以读取现有 D0 模拟盘信号生成拟单，也可以单独通过 EMTL 只读检查账户连接；这两种模式都不会提交真实委托。见[使用与验收说明](docs/emtl-d0-preview.md)。

## 东方财富实盘接入

网站登录后可读取 `GET /api/live-trading/signal?strategy=D0` 或 `?strategy=D0I-BOND-WW`，获取最近一次已确认且仍适用的策略目标。响应包含信号编号、确认日、执行日、最早执行时间及沪深 ETF 目标权重。未验证或已过期的信号返回 `409`。

这是给券商侧执行程序使用的只读信号交接接口。实盘接入需确认账户已开通的东方财富量化终端或 EMT 接入方式。执行程序应按券商实际可用资金、可卖持仓和委托状态计算数量，并在仿真环境校验信号去重、委托回报和失败恢复。东方财富量化终端支持 [策略交易 SDK](https://emt.18.cn/api/quant-help/guide/559.html) 和 [文件单](https://emquant.18.cn/file-help/doc/file_order/scanner_v2.html)。

### D0 东财掘金联调

把 [D0 只读联调脚本](scripts/eastmoney_d0_preflight.py) 放入东财掘金的 Python 策略目录作为策略入口。使用终端配置的 Python 环境（官方 gm SDK 3.0.163 或以上），并在运行进程中配置以下环境变量。

| 变量 | 用途 |
| --- | --- |
| `JIANMING_SITE_URL` | 运行此版本的简明 ETF 网站根地址，使用 HTTPS 或本机回环 HTTP |
| `JIANMING_SITE_PASSWORD` | 简明 ETF 网站登录口令，通过本机环境注入 |
| `EASTMONEY_ACCOUNT_ID` | 终端所关联的交易账户 ID |

启动时，脚本读取网站确认的 D0 目标权重，再通过终端查询指定账户的可用资金、持仓和当前可用份额，结果输出到本地终端日志。脚本仅查询，券商账户数据留在终端侧。通过该联调验证后，还须确认目标账户确实拥有 ETF 程序化实盘权限，并完成仿真委托和回报核对。

## 测试与构建

```sh
python -m unittest discover -s tests -v
node scripts/check_d0_trade_logic.cjs
node scripts/check_d0_comparison_frontend.cjs
node scripts/check_account_reads.cjs
```

GitHub Actions 使用 `production/Dockerfile` 构建 Linux 镜像，并在无网络容器中运行 Python 回归测试。可用以下命令自行构建镜像。

```sh
docker build -t jianming-etf:local production
```

## 许可证与行情来源

简明ETF 自有源码采用 [MIT 许可证](LICENSE)。行情与研究数据保留来源记录，第三方数据和依赖适用各自的条款。行情种子包含来自交易所、指数机构和公开行情接口的历史数据，便于复现策略与测试。模拟委托不会提交给券商。

本衍生仓库为私有仓库，访问由仓库所有者邀请。三项独立新增的 D0 东方财富联调文件适用[单独使用许可](LICENSE-D0-ADDONS.md)，使用前须取得 114514Pro-dev 的明确授权。
