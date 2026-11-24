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
