# 阿里云部署交接：简明 ETF 新版与 D0 网页拟单

## 接手方先看

- **目标**：在用户授权的阿里云轻量应用服务器上运行简明 ETF 新版。先上线首页、D0 模拟盘及私有拟单控制台。本次**不连接券商、不启用真实委托、不迁移真实账户**。
- **代码**：[114514Pro-dev/jianming-etf-open-source](https://github.com/114514Pro-dev/jianming-etf-open-source)。新版已通过 [PR #1](https://github.com/114514Pro-dev/jianming-etf-open-source/pull/1) 合入 `main`。此手册固定部署已验收的应用提交 `5bb7cca2a4e1c6e3097ff2b1bb4ef8b41a29701d`，避免因 `main` 后续变化部署到未核对代码。
- **用户提供的服务器状态**：Ubuntu 24.04，Python 3.12.3，可通过阿里云控制台进入 `root` 终端。上次检查 `/` 剩约 3.8 GiB，`/opt` 与 `/var/lib` 位于同一系统盘，当时 `8765` 无监听。接手时重新核实，**安装、口令设置、服务启动均尚未收到成功确认**。
- **访问设计**：应用只监听服务器 `127.0.0.1:8765`，用户走 SSH 本地端口转发。阿里云防火墙不开放 `8765`。没有域名或 HTTPS 时不要改成公网 HTTP。磁盘空间紧张，优先用 Python 虚拟环境，而不是安装 Docker 或执行系统升级。
- **凭证处理**：请用户自行在阿里云管理控制台或已获授权的终端操作。若此前有私钥上传到聊天，应先更换，验证新钥匙后撤掉旧公钥。**不要读取、索要或复制聊天附件里的私钥；不要在命令行参数、服务文件、工单或日志中写网站口令或证券密码。** 接手环境若禁止访问生产服务器，则记录阻塞，请用户在云控制台执行命令，不绕过限制。

## 1. 确认进度，不覆盖已有部署

下列服务器命令假设在 **Ubuntu 的 root 终端** 执行。先做只读检查：

```bash
whoami
python3 --version
df -h / /opt /var/lib
df -i /
ss -ltn 'sport = :8765'
ls -ld /opt/jianming-etf /var/lib/jianming-etf /etc/systemd/system/jianming-etf.service
systemctl status jianming-etf --no-pager
```

初次安装找不到目录或服务是正常的。若用户已经执行过旧说明，按实际状态续做：

| 看到的状态 | 下一步 |
| --- | --- |
| `/opt/jianming-etf` 不存在、端口未占用、无同名服务 | 走第 2 节首次安装。 |
| 项目已克隆到预期提交，但 `.venv` 缺失或依赖安装失败 | 跳过克隆，继续创建虚拟环境和安装依赖。先确认 `git -C /opt/jianming-etf rev-parse HEAD` 与预期相同。 |
| 已有 `auth.json`，尚未配置服务 | 不重置口令，进入第 3 节。 |
| 同名服务已存在，或 `8765` 已被占用 | 识别实际服务和数据目录，不直接覆盖、重启或终止未知服务。先确认要继续的是同一个实例。 |

已有实例如需更新，先备份运行数据并记录原版本，再安排切换。不要删除目录、清空数据库或重装操作系统来尝试解决问题。空间继续紧张时，先向用户确认清理范围，不擅自删文件。

## 2. 首次安装与网站口令

仅当确认是首次安装时复制这一段。若失败，**不要反复重跑整段**，按上方状态表从失败点继续。

```bash
(
  set -e
  APP=/opt/jianming-etf
  DATA=/var/lib/jianming-etf
  REV=5bb7cca2a4e1c6e3097ff2b1bb4ef8b41a29701d

  if [ -e "$APP" ] || [ -e /etc/systemd/system/jianming-etf.service ]; then
    echo '应用目录或服务已存在。请检查已有部署，不覆盖。' >&2
    exit 1
  fi

  apt-get update
  apt-get install -y --no-install-recommends git python3-venv curl ca-certificates
  id jianming-etf >/dev/null 2>&1 || useradd --system --user-group \
    --home-dir "$DATA" --create-home --shell /usr/sbin/nologin jianming-etf
  install -d -o jianming-etf -g jianming-etf -m 0750 "$APP" "$DATA"

  runuser -u jianming-etf -- git clone --single-branch --branch main \
    https://github.com/114514Pro-dev/jianming-etf-open-source.git "$APP"
  runuser -u jianming-etf -- git -C "$APP" checkout --detach "$REV"
  runuser -u jianming-etf -- python3 -m venv "$APP/.venv"
  runuser -u jianming-etf -- "$APP/.venv/bin/python" -m pip install \
    --no-cache-dir --require-hashes -r "$APP/production/requirements.lock"
  runuser -u jianming-etf -- git -C "$APP" log -1 --format='%h %s'
)
```

最后一行应以 `5bb7cca` 开头。**仅当** `/var/lib/jianming-etf/web/auth.json` 不存在时，在交互终端运行以下命令，由用户自行输入至少 12 字符的网站口令两次。终端不回显。不要使用证券密码：

```bash
(
  set -e
  cd /opt/jianming-etf
  if [ -e /var/lib/jianming-etf/web/auth.json ]; then
    echo '已有站点认证文件，保留现有口令。'
    exit 0
  fi
  runuser -u jianming-etf -- env SIMPLE_ETF_HOME=/var/lib/jianming-etf \
    /opt/jianming-etf/.venv/bin/python production/server.py --set-password
)
```

## 3. 安装并启动 systemd 服务

以下命令假设目标端口仍空闲、认证文件已存在，且尚未配置同名服务。启动实际用非 root 的 `jianming-etf` 用户。

```bash
(
  set -e
  UNIT=/etc/systemd/system/jianming-etf.service
  if [ -e "$UNIT" ]; then
    echo '服务文件已存在，不覆盖。' >&2
    exit 1
  fi
  test -s /var/lib/jianming-etf/web/auth.json
  tee "$UNIT" >/dev/null <<'EOF'
[Unit]
Description=Jianming ETF
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jianming-etf
Group=jianming-etf
WorkingDirectory=/opt/jianming-etf
Environment=SIMPLE_ETF_HOME=/var/lib/jianming-etf
Environment=ETF_WEB_AUTO_REFRESH=0
Environment=ETF_SECTOR_RESEARCH_AUTO_UPDATE=0
Environment=ETF_WEB_TRUSTED_HOSTS=127.0.0.1,localhost
Environment=ETF_WEB_SECURE_COOKIE=0
Environment=ETF_D0_WEB_PREVIEW=1
Environment=RELEASE_REVISION=5bb7cca
ExecStart=/opt/jianming-etf/.venv/bin/python -u production/server.py --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now jianming-etf
)
```

`ETF_WEB_SECURE_COOKIE=0` 仅适用于上述监听回环、用户通过 SSH 加密转发的配置。以后若提供域名入口，应单独配置 HTTPS 反向代理、限制访问并启用安全 Cookie，不要公开监听应用端口。自动刷新相关变量是**首次初始化默认值**；复用旧运行目录时，应在网页里核对已保存的设置。

## 4. 验收与用户访问

在服务器上等待首次启动（可能需几十秒），再执行：

```bash
systemctl is-active jianming-etf
ss -ltn 'sport = :8765'
curl -fsS http://127.0.0.1:8765/healthz && printf '\n'
curl -sS -o /dev/null -w '控制台 HTML: %{http_code}\n' http://127.0.0.1:8765/d0-control
curl -sS -o /dev/null -w '未登录控制台 API: %{http_code}\n' http://127.0.0.1:8765/api/d0-control/status
```

预期：服务 `active`；只监听 `127.0.0.1:8765`；健康检查是 `{"status":"ok","revision":"5bb7cca"}`；控制台 HTML 是 `200`，未登录 API 是 `401`。页面 HTML 可以打开，但登录前不应有账户或策略数据。失败时查看 `journalctl -u jianming-etf -n 60 --no-pager`；分享输出前先检查并删掉任何敏感信息。

用户在自己的电脑上，用**新私钥的本机路径**、实际 SSH 用户名和服务器地址执行以下命令：

```powershell
ssh -i 'C:\path\new-key.pem' -p 22 -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8765:127.0.0.1:8765 SSH_USER@SERVER_IP
```

保持 SSH 窗口打开。浏览器访问 [首页](http://127.0.0.1:8765/)，用自己的**网站口令**登录，再打开 [D0 拟单控制台](http://127.0.0.1:8765/d0-control)。如果用户电脑的 `8765` 已占用，只换 `-L` 的本地端口为 `8876`，然后在浏览器打开 `http://127.0.0.1:8876/`；服务器端口保持不变。

## 5. 交接给后续 AI 的业务边界

- 计划中的自动执行先只接原版 D0，F0、L0、F5 以后再接。账户规模不是固定本金。目标是以当时权益乘目标权重，再扣除已有持仓：例如权益 100 万时 50% 对应 50 万，权益变为 110 万时同一权重对应 55 万。先卖后买；需等实际可用资金，不把预计卖出款当成已到账。
- 当前网页预览以**人工核实的现金和持仓**计算，只显示拟单；没有自动下单、撤单、券商登录表单或实盘开启按钮。`ETF_D0_WEB_PREVIEW=1` 不会开启真实交易。
- 无新鲜行情、非交易时段或缺当天确认信号时，D0 页面提示等待属于正常现象，不代表部署失败。别为演示伪造报价或绕过日历；本版交易日历只覆盖到 2026-12-31。
- EMTL `0.3.1` 只有独立的只读探针，见 [`emtl-d0-preview.md`](emtl-d0-preview.md)。未来用户希望在私有网页主动开启自动模式，之后按 D0 买卖而不逐笔确认；**不能把这一意向当成当前版本已具备实盘能力**。实盘接入需单独验证券商字段、已有持仓归属、部分成交、去重、暂停和限额，且券商凭证只能进入私有执行器的密钥存储。
- 接手完成后回报：部署提交、服务状态、监听地址、健康检查、未登录 API 结果、网页是否完成手动登录验证，以及未通过的项目。不要回报口令、密钥、令牌或真实账户数据。
