'use strict';
// Account benchmark labels use separate text nodes so dates and amounts stay intact.
// Reviewed UI wording. Keys remain the canonical Chinese source strings.
window.ETF_EN = Object.fromEntries(`
账户更新暂未完成	Account update is temporarily unavailable
账户暂未能读取	Account is temporarily unavailable
已保留上次读取的账户记录，日期以账户标题为准。	Previously loaded account records are retained. Check the date in the account heading.
正在重新读取账户…	Reloading account…
稍后将自动重试，也可查看后台任务进度。	A retry is scheduled. You can also check background task progress.
自动重试已暂停，可稍后手动重试。	Automatic retries have paused. You can retry manually later.
重试读取	Retry loading
查看任务进度	View task progress
报价采集失败，连续报价计数已清除；等待故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。	Quote collection failed and the consecutive-quote count was cleared. Wait for two new, fresh, valid quotes after the failure, with increasing cumulative volume and turnover, before quote-driven whole-order simulation estimates can continue.
报价采集状态无效，等待核对与恢复；恢复后须重新取得故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。	The quote collection state is invalid. Wait for verification and recovery, then obtain two new, fresh, valid quotes after the failure, with increasing cumulative volume and turnover, before quote-driven whole-order simulation estimates can continue.
当前报价的行情源时间或接收时间不晚于采集故障时点，不能用于恢复；等待故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。	The quote's source time or receipt time is at or before the collection failure, so it cannot establish recovery. Wait for two new, fresh, valid quotes after the failure, with increasing cumulative volume and turnover, before quote-driven whole-order simulation estimates can continue.
采集故障会清除连续报价计数。恢复后须重新取得同标的、同来源的两份新鲜有效报价：行情源时间和接收时间均须晚于故障时点并递增，累计成交量和成交额均须推进，委托提交后的时间要求与连续竞价窗口仍适用。历史报价或过去已通过的活动门槛不能证明当前已恢复；满足条件仅允许报价驱动的整单模拟估计，不代表真实成交、可成交数量或券商执行。	A collection failure clears the consecutive-quote count. Recovery requires two new, fresh, valid quotes for the same security from the same source: source and receipt times must both be after the failure and increase, and cumulative volume and turnover must both advance. Post-submission timing and continuous-auction windows still apply. Historical quotes or a previously passed activity gate do not prove current recovery. These conditions only permit quote-driven whole-order simulation estimates; they do not establish actual executions, available fill quantities, or broker execution.
简明 ETF · 模拟交易	Simple ETF · Paper Trading
简明 ETF	Simple ETF
模拟交易工作台	Paper trading workspace
网站已更新。完成当前填写后，刷新即可使用新版。	A new version is available. Finish your current entry, then refresh.
刷新到新版	Load new version
用同一份数据，认真检验每一种想法	Test every idea against the same data
看清策略，	Understand the strategy.
再做下一步。	Then take the next step.
原有 21 种策略，新增纳指与恒生海外专区。查看市场、比较历史表现，在模拟账本里留下每一次判断。	Explore 21 domestic strategies and the Nasdaq / Hang Seng markets. Review prices, compare historical performance and track decisions in paper accounts.
真实行情时刻	Actual quote timestamps
独立模拟账本	Separate paper ledgers
完整导出与恢复	Full export and restore
示意曲线 · 不代表策略实际收益	Illustration only · Not actual strategy performance
欢迎回来	Welcome back
进入你的工作台	Sign in to your workspace
输入访问密码，继续查看你的模拟记录。	Enter your access password to view your paper trading records.
访问密码	Access password
输入访问密码	Enter access password
登录工作台	Sign in
仅用于模拟交易。后台可按已确认周期自动记账，不连接实盘。	Paper trading only. The server can update accounts using confirmed periods. No live brokerage connection.
工作台	Workspace
策略研究	Strategy research
市场与公司	Markets and companies
主导航	Main navigation
市场总览	Market overview
海外专区	Overseas markets
策略信号	Strategy signals
模拟账户	Paper accounts
策略比较	Compare strategies
任务记录	Activity log
仅模拟 · 无实盘下单	Simulation only · No live orders
境内策略 + 纳指 / 恒生专区	Domestic strategies + Nasdaq / Hang Seng
退出登录	Sign out
正在连接	Connecting
退出	Sign out
关闭错误提示	Dismiss error
行情有时间，判断有依据。	Every quote has a timestamp. Every decision has a reason.
报价、已确认 K 线与账户进度分别显示，避免把历史状态当成今天。	Quotes, confirmed bars and account progress are shown separately so older data is clearly identified.
服务器后台运行	Server automation
关闭网页，也继续跟踪	Keep tracking after you close the page
正在读取状态	Loading status
行情与策略参考自动更新	Automatically update prices and strategy references
正在读取更新频率…	Loading update frequency…
全部账户自动模拟	Automatic simulation for all accounts
按原策略已确认周期推进，可逐账户暂停	Advance on each strategy's confirmed periods; pause individual accounts as needed
正在读取更新设置…	Loading update settings…
正在读取后台状态…	Loading server status…
两个开关独立：暂停行情更新后仍可按已有确认行情模拟；暂停自动模拟后仍可更新行情与参考。间隔是正常运行目标；长区间模拟或比较时可能延后，报价也可能有来源延迟。	These switches are independent. Simulations can use existing confirmed data while market updates are paused; prices and references can update while simulation is paused. Intervals are targets and may be delayed by long jobs or data providers.
查看后台运行结果	View automation details
市场快照	Market snapshot
关注的 ETF	Tracked ETFs
来源报价 · 非成交价	Provider quotes · Not execution prices
策略参考	Strategy reference
这笔预算，策略怎样分配？	How would this strategy allocate your budget?
策略组	Strategy group
参考策略	Reference strategy
独立参考本金 / 元	Reference capital / CNY
计算参考	Calculate reference
参考配置按独立预算计算，不是某个模拟账户的持仓。仅使用来源中已有的报价或已确认 K 线。后台参考与当前策略、本金一致时会自动跟随更新。	Reference allocations use a separate budget, not a paper account's holdings. They use available quotes or confirmed bars. Results update automatically when the server reference matches the selected strategy and capital.
选择一个策略，查看它的配置与判断依据。	Select a strategy to view its allocation and reasoning.
需要留下一段连续的模拟记录？	Want a continuous paper trading record?
去建立模拟账户	Create a paper account
导出历史日线	Export daily history
导出已采集报价	Export collected quotes
下载完整备份	Download full backup
阅读策略研究报告 ↗	Read original research report (Chinese) ↗
查看完整行情资料	View original market data
纳指与恒生，有自己的观察窗口。	A dedicated view of Nasdaq and Hang Seng ETFs.
境内人民币 ETF · 三个市场独立分析、独立模拟。	Mainland-listed RMB ETFs · Separate analysis and simulation for three markets.
刷新海外行情	Refresh overseas data
正在读取海外市场…	Loading overseas markets…
海外市场	Overseas market
策略与模拟	Strategies and simulation
独立账本	Separate ledger
参考本金 / 元	Reference capital / CNY
策略参考和模拟账户在收盘资料确认后更新；小时策略按真实小时顺序重放。报价刷新不会直接产生模拟成交。新账户需要选择自己的起点，随后可由后台持续推进。	Strategy references and accounts update after closing data is confirmed. Hourly strategies replay actual bars in sequence. Refreshing quotes does not itself create fills. Choose a start date for each account; the server can then advance it automatically.
新建本市场模拟账户	Create account for this market
查看本市场账户	View this market's accounts
选择区间重新比较	Compare another date range
此前独立研究 · 冻结结果	Previous independent research · Frozen results
21 种策略，先看适用范围	21 strategies: understand their scope
完整研究报告 ↗	Original research report (Chinese) ↗
研究情景	Research scenario
基准费用	Base costs
佣金与滑点加倍	Double commission and slippage
信号延迟一周期	Signals delayed by one period
多资产策略包含黄金、银行或国债收益；可点“曲线与贡献”检查来源，不能当成纯目标 ETF 择时成绩。	Multi-asset strategies include gold, bank or Treasury returns. Use “Chart and attribution” to review contributions; these are not pure target-ETF timing results.
这些是境内人民币跨境 ETF，按境内交易时间报价。海外休市、汇率、申赎限制和溢价可能影响价格；研究未加入完整历史溢价过滤、排队成交或大额冲击，也没有真正未见样本外验证。	These cross-border ETFs trade in RMB during mainland market hours. Overseas holidays, FX, creation/redemption limits and premiums can affect prices. The research does not fully model historical premium filters, execution queues or large-order impact, and has no genuinely unseen out-of-sample validation.
每个模型，现在想做什么。	What each model intends to do now.
境内 21 种策略 + 纳指、恒生指数、恒生科技各 21 种。不需要先建账户。	21 domestic models plus 21 each for Nasdaq-100, Hang Seng Index and Hang Seng TECH. No account required.
读取最新结果	Load latest results
每张卡片显示最近确认日的买卖或未操作状态，并保留最近一次模拟成交。“待买入／待卖出”表示下一步意向，尚未成交；点开依据可查看成交明细和原因。	Each card shows trades or no action on the latest confirmed date, plus the most recent simulated fills. “Pending buy/sell” means an intention that has not executed. Open the details for fills and reasons.
后台按各策略的已确认周期更新；关闭网页仍继续计算。	The server updates each strategy on its confirmed periods, even after you close this page.
正在读取模型状态…	Loading model status…
模型信号数量	Model signal counts
市场与策略组	Market and strategy group
全部市场 · 84 个模型	All markets · 84 models
当前意向	Current intention
全部意向	All intentions
包含买入	Includes buys
包含卖出	Includes sells
调仓	Rebalance
继续持有	Continue holding
保持空仓	Stay in cash
等待确认或更新	Awaiting confirmation or update
搜索模型	Search models
如 Supertrend、D7、纳指	e.g. Supertrend, D7, Nasdaq
清除全部筛选	Clear all filters
每种想法，都有自己的账本。	A separate ledger for every idea.
各市场、各策略组账户分别保存。自动模拟按原策略确认周期记账，切换页面不会触发交易。	Accounts are stored separately by market and strategy group. Automation follows each strategy's confirmed periods. Changing pages does not trigger trades.
已删除账户	Deleted accounts
导入备份	Import backup
新建账户	New account
账户组	Account group
后台已有新的账户进度，正在保留你的输入；离开输入框后会更新显示。	New account data is available. Your entries are preserved; the view will update when you leave the input.
保留输入并更新	Update and keep entries
我的账户	My accounts
重新读取账户	Reload accounts
从一个模拟账户开始	Start with a paper account
选择已有账户，或新建账户开始记录。	Select an existing account or create one to start tracking.
同一区间，比较不同选择。	Compare choices over the same period.
每次只比较同一组策略，结果保留对应区间、本金与执行口径。	Compare one strategy group at a time, with its date range, capital and execution rules recorded.
开始日期	Start date
结束日期	End date
本金 / 元	Capital / CNY
运行比较	Run comparison
先给比较设一个范围	Choose a comparison period
计算在后台进行，可以离开此页，再从任务记录查看结果。	Calculations run on the server. You can leave this page and find results in the activity log.
每一次运行，都可以回看。	Review every run.
后台任务每 5 秒更新。停止在安全步骤生效，已保存的记录会保留。	Job status updates every 5 seconds. Stop requests take effect at a safe step and keep saved records.
更新状态	Refresh status
简明 ETF · 研究与模拟	Simple ETF · Research and simulation
历史表现不代表未来收益	Past performance does not predict future returns
独立记账	Separate accounting
新建模拟账户	Create paper account
关闭新建账户	Close account form
账户名称	Account name
起始日期	Start date
固定策略	Fixed strategy
初始本金 / 元	Initial capital / CNY
关闭	Close
收起并查看任务	Minimize and view job
建立账户	Create account
任务详情	Job details
关闭详情	Close details
正在连接模拟交易工作台…	Connecting to your paper trading workspace…
删除账户	Delete account
恢复已删除账户	Restore deleted account
接续模拟	Continue simulation
接入最新日线	Attach latest daily data
更换后续策略	Change future strategy
刷新行情	Refresh market data
更新来源报价	Update provider quotes
检查自动模拟账户	Check automatic simulations
自动接续模拟	Advance automatic simulation
计算参考配置	Calculate reference allocation
导出账户	Export account
恢复账户	Restore account
排队中	Queued
正在运行	Running
已完成	Completed
未完成	Incomplete
已停止	Stopped
运行已中断	Interrupted
纳指100 · 21策略，人民币跨境ETF；收盘确认后推进，期末市值结算。	Nasdaq-100 · 21 strategies for RMB cross-border ETFs. Advance after close confirmation; mark holdings to market at period end.
恒生指数 · 21策略；多资产与纯ETF择时需区分，独立记账。	Hang Seng Index · 21 strategies with separate ledgers. Distinguish multi-asset returns from pure ETF timing.
恒生科技 · 21策略；小时数据共同区间从2023年起，独立记账。	Hang Seng TECH · 21 strategies with separate ledgers; the shared hourly history begins in 2023.
四资产 9 策略 · D/F 支持 2013 起，L 系列最早 2017-08-03。此处账户与其他两组分别保存。	Four assets, 9 strategies. D/F history starts in 2013; L starts no earlier than 2017-08-03. Accounts are stored separately from the other groups.
创业板 5 策略 · 使用真实完整 60 分钟 K 线。每个账户固定一种策略，独立保存。	5 ChiNext strategies using actual complete 60-minute bars. Each account has one fixed strategy and its own ledger.
七组合 · 从 2023-01-03 起模拟。A 类各份本金独立复利；B 类按日终信号、次日开盘切换。	Seven portfolios, simulated from 2023-01-03. Type A sleeves compound independently; Type B switches at the next open after end-of-day signals.
不足一年	Less than one year
尚无记录	No record yet
已连接 · 模拟交易	Connected · Paper trading
连接暂不可用	Connection unavailable
下载文件	Download file
完整业务备份用于恢复整套应用资料；它不是“导入账户”使用的单账户备份。	A full backup restores all application data. It is not the single-account file used by “Import backup”.
主文件为这次操作的完整导出；账户备份可在对应账户组导入，CSV和报告用于查看。	The main file contains the complete export. Import an account backup into its matching group; CSV files and reports are for review.
下载完整业务备份	Download complete data backup
下载主文件	Download main file
附加文件	Additional file
正在读取策略研究摘要…	Loading research summary…
等待报价	Waiting for quotes
来源仍为此前交易日报价	Provider quote is still from an earlier trading day
参考尚未跟上最新确认日，请重新计算。	The reference has not reached the latest confirmed date. Recalculate it.
为这个市场计算一份参考	Calculate a reference for this market
选择策略与独立预算。计算成功后，后台会在新的收盘资料确认后更新。	Choose a strategy and separate budget. After the initial calculation, the server updates it when new closing data is confirmed.
策略 / 资产范围	Strategy / asset scope
本表年化最高	Highest CAGR in this table
本表回撤最低	Lowest drawdown in this table
年化收益	Annualized return
最大回撤	Maximum drawdown
累计收益	Total return
佣金 / 元	Commission / CNY
查看与模拟	Review and simulate
曲线与贡献	Chart and attribution
正在读取这条策略的曲线…	Loading strategy chart…
贡献资产	Contributing asset
收益贡献 / 元	Return contribution / CNY
此择时策略仅交易目标ETF与现金。	This timing strategy holds only the target ETF or cash.
收益为研究区间历史结果，不代表未来；黄金、银行等贡献不属于目标ETF收益。	Returns cover the historical research period and do not predict the future. Gold and bank contributions are not target-ETF returns.
建模拟账户	Create paper account
连接中断 · 正在等待恢复	Disconnected · Waiting to reconnect
暂时连接不到服务，请检查网络与服务是否运行。任务提交若未收到确认，可先到任务记录核对。	The service is unavailable. Check the network and server. If a submission was not acknowledged, check the activity log before retrying.
策略信号总览	Strategy signals overview
暂时没有可用的策略目录。	The strategy catalog is temporarily unavailable.
每个模拟账户独立保存。	Each paper account is stored separately.
期末按持仓市值评价，不强制清仓。	Value holdings at market prices at period end; no forced liquidation.
历史比较采用本组期末清算口径；持续账户不强制清仓。	Historical comparisons use this group's terminal liquidation convention. Ongoing accounts do not force liquidation.
已确认收盘日线	Confirmed daily close
公共行情库	Shared market data
完整 60 分钟柱	Complete 60-minute bars
未完成柱不计入	Incomplete bars excluded
最近报价采集	Latest quote collection
报价源时间见下表	Provider timestamps shown below
策略与市场	Strategies and markets
境内21种 · 海外3市场各21种	21 domestic · 21 in each of 3 overseas markets
还没有有效报价	No valid quotes yet
点击刷新行情获取最新可用资料。来源失败时不补造价格。	Refresh market data to retrieve the latest available records. Missing provider prices are not fabricated.
来源时间未提供	Provider timestamp unavailable
现价	Last price
较昨收	Change vs prior close
当日开盘	Day open
未开盘	Not open yet
当日高 / 低	Day high / low
来源报价时间	Provider timestamp
五策略 · 已确认信号	Five strategies · Confirmed signals
只接受完整 K 线	Complete bars only
策略	Strategy
周期	Period
已确认信号	Confirmed signal
信号柱截至	Signal bar as of
状态	Status
已就绪	Ready
等待预热	Warming up
依据	Reasoning
查看	View
按后台计划	Per server schedule
午间休市	Lunch break
收盘核对	Closing data check
休市	Market closed
休市或收盘核对期间可能沿用最近报价；以每只 ETF 的来源时间为准。	The most recent quotes may remain during breaks and close checks. Use each ETF's provider timestamp.
下方显示来源实际报价时间；交易期间也可能有延迟，不等同于实时成交。	Actual provider timestamps are shown below. Quotes can be delayed during trading and are not execution prices.
后台状态	Server status
后台等待下一轮	Waiting for the next cycle
等待安排	Awaiting schedule
即将检查	Checking soon
行情与参考自动更新已暂停，仍可手动刷新	Automatic prices and references are paused; manual refresh is available
后台状态暂不可用 · 将重试	Server status unavailable · Retrying
正在读取自动状态	Loading automation status
此账户已暂停	This account is paused
等待全局自动模拟开启	Waiting for global automatic simulation
自动模拟已开启 · 已跟上确认数据	Automatic simulation on · Up to date with confirmed data
自动模拟已开启	Automatic simulation on
正在读取后台模拟设置…	Loading simulation settings…
后台自动模拟已开启：未暂停的账户按各自策略已确认周期持续推进，关闭网页仍运行。	Automatic simulation is on. Unpaused accounts advance using their strategy's confirmed periods, even when this page is closed.
全局自动模拟已暂停：可以手动接续，行情和参考更新由另一个开关控制。	Global automatic simulation is paused. Manual continuation remains available. Prices and references have a separate switch.
此账户已允许自动模拟；是否运行由全局开关控制。	Automatic simulation is allowed for this account; the global switch controls whether it runs.
此账户已暂停自动模拟，仍可手动接续。	Automatic simulation is paused for this account. You can still continue manually.
当前参考正在跟随后台结果；来源与判断时间见下方。	This reference follows the server results. Source and decision timestamps are shown below.
后台参考已更新。当前输入保持不变；点击“计算参考”查看所选策略和预算的结果。	The server reference has updated. Your entries are unchanged; select “Calculate reference” for your chosen strategy and budget.
暂无可用账户	No available accounts
可在“已删除账户”恢复，或新建账户。	Restore a deleted account or create a new one.
盘中临时参考（最多5分钟重算）	Provisional intraday reference (recalculated up to every 5 minutes)
确认收盘参考	Confirmed close reference
完整周期参考	Complete-period reference
当前没有可用参考	No reference available
缺少有效行情，请检查来源日期后重试。	Valid market data is missing. Check its date and retry.
查看完整策略依据	View original strategy data
当前结果未提供配置比例，完整依据见上方详情。	This result does not provide allocation weights. See the full details above.
还没有这一组的模拟账户	No paper accounts in this group
点击“新建账户”开始，或导入这个模块的完整备份。	Choose “New account” or import a matching account backup.
查看异常文件	View unreadable files
账户读取异常 · 原文件保留	Account read error · Original files retained
其他正常账户仍可使用。可用有效备份恢复为独立副本。	Other accounts remain available. A valid backup can be restored as a separate copy.
账户将移入“已删除账户”，停止后续自动模拟。历史和成交记录保留，可随时恢复。正在执行的任务会先完成。	The account will move to “Deleted accounts” and stop future automation. History and fills are retained for restoration. Any running job will finish first.
确认删除	Confirm deletion
取消	Cancel
正在读取…	Loading…
这里的账户不会继续模拟。恢复后保留全部历史，并沿用原有自动模拟设置。	These accounts do not advance. Restoring an account retains all history and its previous automation setting.
没有已删除账户	No deleted accounts
这个账户组的已删除账户会显示在这里。	Deleted accounts from this group appear here.
暂无账户	No accounts
正在读取账户及完整记录…	Loading account and full history…
账户未能读取	Unable to load account
导出完整账户	Export complete account
账户总资产 / 元	Account equity / CNY
按账户历史区间复利折算	Compounded over the account's historical period
可用现金 / 元	Available cash / CNY
交易记录	Trade records
当日操作与原因	Daily actions and reasons
允许此账户自动模拟	Allow automatic simulation for this account
暂停只影响此账户的后续自动推进，已保存记录保留；仍可手动接续。	Pausing affects future automation for this account only. Saved records remain, and manual continuation is available.
手动模拟至	Manually simulate through
账户模拟终点	Account simulation end
使用最新数据	Use latest data
手动接续和后台自动推进均按策略原规则产生模拟记录；重复同一终点不会重复交易。	Manual and automatic runs both follow the original strategy rules. Repeating the same end point does not duplicate trades.
接入最新已确认日线	Attach latest confirmed daily data
账户资产曲线	Account equity curve
持仓	Positions
成交与记录	Fills and events
策略依据	Strategy reasoning
已发生的持仓、成交和曲线保留，新策略只影响后续判断。	Existing positions, fills and equity history are retained. The new strategy affects future decisions only.
后续策略	Future strategy
查看完整账户资料	View original account data
当前没有持仓	No current positions
资金以现金状态保留，下一步依据见“策略依据”。	Capital remains in cash. See “Strategy reasoning” for the next step.
资产	Asset
持有份数	Units held
评价价格	Valuation price
持仓市值 / 元	Market value / CNY
买入	Buy
卖出	Sell
记录	Record
截至账户确认时点，今日暂无模拟成交。	No simulated fills today as of the account's confirmed time.
今天尚未记录模拟成交。	No simulated fills recorded today.
账户资产	Account assets
成交原因：	Fill reason: 
原记录未保存更细的成交原因；不以当前信号反推当时原因。	The original record has no more detailed reason. Current signals are not used to invent a historical explanation.
查看成交详情	View fill details
模拟成交与依据	Simulated fill and reasoning
今日模拟成交	Today's simulated fills
当前	Current
最近确认	Latest confirmation
暂无判断	No decision yet
该账户没有保存更细的策略解释。	No more detailed strategy explanation is saved for this account.
查看具体指标依据	View original indicator evidence
后续计划不会自动成交，仍可手动接续。	Future plans will not execute automatically. Manual continuation remains available.
后台只有在已确认行情及执行条件满足后才记入模拟成交。	The server records simulated fills only when data is confirmed and execution conditions are met.
最近一次成交（非今日）	Most recent fills (not today)
发生时间	Event time
记录类型	Record type
买卖方向	Side
份数	Units
成交价 / 元	Fill price / CNY
资金变化 / 元	Cash change / CNY
信号日 / 时刻	Signal date / time
对应完整 K 线	Corresponding complete bar
组合分项	Portfolio sleeve
触发依据	Trigger reasoning
这条记录未提供文字依据。	This record has no written explanation.
“—”表示本条记录未提供该字段。资金变化和信号时间仅展示保存值，不用成交价或其他时间推算。	“—” means the field was not recorded. Cash changes and signal times are saved values, not estimates from prices or other timestamps.
查看原始返回记录	View original returned record
还没有成交与事件	No fills or events yet
接续模拟后，完整交易与触发依据会保留在这里。	Continue the simulation to record fills and trigger reasons here.
方向	Side
类型	Type
成交价	Fill price
佣金	Commission
上一页	Previous
下一页	Next
当前策略依据	Current strategy reasoning
目标仓位	Target allocation
待执行信号	Pending signal
当前没有新的执行依据。	No new execution signal is available.
尚无资产曲线	No equity curve yet
接续模拟后显示每日或逐柱资产。	Continue the simulation to see daily or per-bar equity.
距高点回撤	Drawdown from peak
已有建户任务在进行，先查看当前任务；本次选择尚未替换。	An account creation job is already running. Review it first; the current selection has not replaced it.
这项策略当前不在可建户目录中，请更新策略目录后重试。	This strategy is not available for new accounts. Refresh the catalog and retry.
全局自动模拟开启时，新账户会自动追赶已有确认行情；可在账户详情暂停。	With global automation on, new accounts catch up to confirmed data. You can pause them in account details.
已提交后台	Submitted to server
正在提交…	Submitting…
查看建户进度	View creation progress
继续编辑建户	Continue account setup
后台处理中	Processing on server
正在等待服务确认，请勿重复提交。收到任务编号后可以收起窗口。	Waiting for acknowledgement. Do not submit again. You can minimize once a job ID is received.
还没有这一组的比较结果	No comparison results for this group
设置区间和本金后运行比较。完成的任务也可在“任务记录”中回看。	Set dates and capital, then run a comparison. Completed results remain in the activity log.
本次历史比较	Historical comparison
导出结果	Export results
没有返回可用结果	No usable results returned
请检查区间与策略的历史起点。	Check the selected period and each strategy's available history.
完整返回信息	Original returned data
本次年化最高	Highest CAGR in this comparison
本次回撤最低	Lowest drawdown in this comparison
用此策略建账户	Create account with this strategy
此策略当前不在可建户目录中	This strategy is not available for new accounts
累计佣金 / 元	Total commission / CNY
交易统计	Trade statistics
交易数（见完整口径）	Trade count (see methodology)
查看策略曲线	View strategy curve
曲线类型	Chart type
资产曲线	Equity curve
标签仅适用于本次同区间、同本金的组内比较；不足一年不显示年化。基准不参与策略标签排名。不同账户组的结算口径不能直接混排。	Labels apply only within this comparison using the same dates and capital. Annualization is hidden below one year. Benchmarks are excluded from labels. Groups with different settlement conventions cannot be ranked together directly.
本次比较未全部完成，只保留已完整跑完区间的策略，不生成本次排名。	The comparison is incomplete. Only strategies that finished the full period are retained; no ranking is produced.
此区间没有足够历史数据	Insufficient history for this period
完整结果与执行口径	Original results and execution methodology
同一操作已经在后台进行，可到任务记录查看。	This operation is already running. See the activity log.
服务没有返回任务编号，请到任务记录核对后再提交。	No job ID was returned. Check the activity log before submitting again.
任务	Job
连接暂不可用 · 将重试	Connection unavailable · Retrying
已停止，已完成记录保留。	Stopped. Completed records are retained.
服务重启或任务被中断，请核对账户后再接续。	The service restarted or the job was interrupted. Review the account before continuing.
任务未能完成。	The job could not finish.
参考未能生成	Reference could not be calculated
输入与后台结果一致时，将自动跟随更新。	Results update automatically when your entries match the server reference.
参考已完成；输入已变化，可在任务记录查看刚才的结果。	Reference complete. Your entries have changed; view the previous result in the activity log.
文件已准备好	File ready
暂时没有运行记录	No activity yet
创建账户、刷新行情或比较策略后，任务会在这里显示。	Account creation, market refresh and comparison jobs appear here.
后台任务	Server job
停止	Stop
已请求停止，将在安全步骤结束；自动任务对应的开关或账户暂停状态会同步更新。	Stop requested. The job will end at a safe step; the related automation switch or account pause state will update too.
查看详情	View details
待买入	Pending buy
待卖出	Pending sell
待调仓	Pending rebalance
等待确认	Awaiting confirmation
后台等待新的确认行情	Waiting for newly confirmed market data
行情自动更新已暂停	Automatic market updates paused
最新状态读取失败，当前内容可能过期：	Unable to load current status; displayed data may be old: 
最新动态 · 模型模拟成交	Latest activity · Model simulated fills
成交动态尚未生成，等待该模型计算完成。	Fill activity is not ready. Waiting for the model calculation.
以下是旧快照的成交记录，最新动态待更新。	These fills belong to an older snapshot. Current activity is pending an update.
仍持有：	Still holding: 
最近一次模拟成交	Most recent simulated fills
从参考组合起点至上述确认日，尚无模拟成交。	No simulated fills from the reference start through this confirmed date.
非该确认日成交	Occurred before this confirmed date
成交时间	Execution time
操作	Action
成交金额 / 元	Trade amount / CNY
执行原因	Execution reason
该确认日全部成交明细	All fills on the confirmed date
最近一次成交明细	Details of the most recent fills
成交价含原策略滑点，成交金额不含佣金。	Fill prices include the strategy's slippage. Trade amounts exclude commission.
此模型正在更新，下方旧信号只供回看；不能视为当前指令。	This model is updating. The previous signals below are historical references, not current instructions.
下方为旧信号依据。	Historical signal reasoning is shown below.
为什么这样操作	Why this action?
各资产的下一步意向	Next intended action by asset
策略规则	Strategy rules
什么时候执行	When does it execute?
最后确认的指标周期：	Last confirmed indicator period: 
银行 / 黄金日线参考截至：	Bank / gold daily reference as of: 
参考仓位与目标配置	Reference positions and target allocation
参考持仓 / 份	Reference holdings / units
条件目标比例	Conditional target weight
模型意向与实际账户成交分别记录。	Model intentions and account fills are recorded separately.
详情保留本次打开时的信号快照；关闭后重新打开可查看新的结果。	Details show the snapshot from when you opened this dialog. Close and reopen for updated results.
查看完整模型依据	View original model evidence
没有符合筛选的模型	No matching models
可切换市场、意向或清空搜索。	Change the market or intention, or clear the search.
下一步意向（尚未成交）：	Next intention (not executed): 
该组计算暂未完成，后台会重试。	This group has not finished. The server will retry.
旧结果，等待新快照计算。	Previous result; waiting for the new snapshot.
请填写账户名称、不少于1,000元的有效本金，并选择起始日期。	Enter an account name, valid capital of at least CNY 1,000, and a start date.
该确认日已发生模拟成交，买卖明细见下方。	Simulated trades occurred on this confirmed date. See fills below.
该确认日没有模拟成交；已有新的买卖意向，等待下一可执行时点。	No fills on this confirmed date. New buy/sell intentions are waiting for the next executable time.
该确认日没有模拟成交，等待完整信号或可执行条件。	No fills on this confirmed date. Waiting for a complete signal or execution conditions.
该确认日未操作，继续持有现有参考仓位。	No action on this confirmed date. Continue holding the reference positions.
该确认日未操作，保持空仓。	No action on this confirmed date. Remain in cash.
独立模型参考组合的原引擎模拟成交；与个人账户成交分别记录。	Simulated fills from the independent reference model's original engine, recorded separately from personal accounts.
全部模型用2023-01-03起、初始10万元的独立只读参考组合跟踪持有期；不读取或改动你的账户。不同建户日期、本金和持仓可能产生不同操作。只用已确认K线；成交动态是上述模型已发生的模拟记录，待买入/待卖出是尚未成交的下一步意向。	All models use independent read-only reference portfolios starting on 2023-01-03 with CNY 100,000. They do not read or change your accounts. Different start dates, capital or holdings can produce different actions. Only confirmed bars are used. Activity shows completed model simulations; pending buys/sells are unexecuted intentions.
已确认目标与参考仓位需要调整；方向按当前收盘价格估算。	The confirmed target requires a change to the reference holdings. Direction is estimated using current closing prices.
确认后在下一可执行交易日开盘模拟；实际份数取决于当时价格、整手、费用与可用资金。	Simulate at the next eligible trading-day open after confirmation. Actual units depend on prices, lot sizes, costs and available cash.
已产生目标，但当前估算没有可成交份数；等待可执行价格或满足整手、资金条件。	A target exists, but estimated executable units are zero. Await an executable price or sufficient cash / lot size.
全部参考持仓为零，且当前没有待执行买入目标，因此保留现金。	All reference positions are zero and no buy target is pending, so capital remains in cash.
指标尚未完成预热，等待完整数据。	Indicators are still warming up. Await complete data.
当前时刻没有新完成的策略周期，旧信号不会重复触发入场。	No new strategy period has closed. An old signal does not trigger another entry.
参考仓位仍有持仓，退出指令已确认，等待下一可执行时点；尚未视为卖出。	The reference still holds units. An exit is confirmed but awaits execution; it is not yet a sale.
参考仓位为空，新入场条件已确认，等待下一根真实完整K线开盘模拟买入。	The reference is in cash. Entry is confirmed; await the next actual complete bar's open for a simulated buy.
参考仓位仍在持有，没有待执行卖出指令。	The reference remains invested with no pending exit.
参考仓位为空，本次没有新的可执行入场条件，因此保留现金。	The reference is in cash with no new executable entry, so cash is retained.
下一根真实完整K线开盘模拟；	Simulate at the next actual complete bar's open; 
买入当日不可卖，退出指令保留至满足T+1。	units cannot be sold on the purchase date; retain the exit until T+1 eligibility.
目标ETF按原跨境ETF引擎的T+0规则执行。	apply the original cross-border ETF engine's T+0 rules to the target ETF.
该份独立本金的已确认信号与当前持仓不同。	This independent sleeve's confirmed signal differs from its current position.
各份本金独立：有信号的一份调整，其他份额继续原状态；不跨子组合搬动资金。	Each sleeve has independent capital. Adjust only the sleeve with a signal; other sleeves retain their state. No capital transfers between sleeves.
与上一交易日的模型目标相同，按原规则继续持有；不会因价格自然漂移而每日调仓。	The target is unchanged from the prior trading day. Keep holdings under the original rules; price drift alone does not cause daily rebalancing.
与上一交易日的模型目标不同，等待下一交易日开盘调仓。	The target differs from the prior trading day. Rebalance at the next trading-day open.
组合目标变化，按新比例调整；方向为收盘估算，执行时按开盘价格、整手及资金确定。	The portfolio target changed. Adjust to the new weights; direction is estimated at the close, with execution based on opening prices, lot sizes and cash.
各资产均未产生待执行买入意向，参考本金保持现金，等待相应条件成立。	No asset has a pending buy intention. Keep the reference capital in cash until conditions are met.
防御条件变化	Defensive conditions changed
入场信号	Entry signal
退出信号	Exit signal
按已确认的策略目标模拟执行。	Simulated execution based on the confirmed strategy target.
目标未改变，继续持有	Target unchanged; continue holding
未确认多头	Bullish state not confirmed
多头有效	Bullish state confirmed
未达到完整多头确认	Full bullish confirmation not reached
未达到多头确认	Bullish confirmation not reached
等待银行低位金叉	Waiting for a low-level bullish bank crossover
黄金未通过趋势确认，防守预算留现金	Gold trend is unconfirmed; keep the defensive budget in cash
只读参考账户已经持有创业板ETF，尚无待执行退出指令，参考目标继续持有。	The reference already holds the ChiNext ETF with no pending exit; continue holding.
只读参考账户已持有目标ETF，尚无待执行退出指令，参考目标继续持有。	The reference already holds the target ETF with no pending exit; continue holding.
四资产原9策略	Original 9 · Four assets
创业板5策略	5 ChiNext strategies
七组合	Seven portfolios
纳指100 · 海外	Nasdaq-100 · Overseas
恒生指数 · 海外	Hang Seng Index · Overseas
恒生科技 · 海外	Hang Seng TECH · Overseas
纳指100	Nasdaq-100
恒生指数	Hang Seng Index
恒生科技	Hang Seng TECH
创业板	ChiNext
银行	Bank
黄金	Gold
国债	Treasury
现金	Cash
动态强弱	Dynamic strength
5%偏离调仓	5% drift rebalancing
周线调仓	Weekly rebalancing
每日调仓	Daily rebalancing
分阶段配置	Staged allocation
四态融合	Four-state blend
股票底仓	Equity floor
均线突破量能组合	MA / breakout / volume ensemble
周线·SKDJ＋TRIX持有20日	Weekly SKDJ + TRIX · Hold 20 trading days
唐奇安突破	Donchian breakout
50根均线择时	50-bar moving-average timing
三指标＋黄金各半	Three-indicator model / gold 50:50
三指标50/银行25/黄金25	Three-indicator 50 / bank 25 / gold 25
三资产MA200过滤	Three-asset MA200 filter
创业板→黄金周线/现金	ChiNext → weekly gold / cash
创业板→黄金持有	ChiNext → hold gold
创业板→银行/黄金	ChiNext → bank / gold
目标ETF	Target ETF
目标 ETF	Target ETF
60分钟	60 min
周线固定持有20日	Weekly · Hold 20 trading days
股票底仓0%	Equity floor 0%
股票底仓10%	Equity floor 10%
股票底仓20%	Equity floor 20%
年化收益最高	Highest annualized return
回撤最低	Lowest drawdown
最高年化	Highest CAGR
最低回撤	Lowest drawdown
买入持有基准	Buy-and-hold benchmark
买入持有	Buy and hold
等待行情更新	Waiting for market data
交易时段	Trading session
盘前	Pre-open
自动模拟账户已跟上行情	Automatic accounts are up to date
完成往返交易	Completed round trips
已完成往返交易数	Completed round trips
成交笔数	Fill count
策略成交	Strategy fill
账户创建	Account created
自动模拟	Automatic simulation
已买入	Bought
已卖出	Sold
来源报价：	Provider quote: 
最近确认日	Latest confirmed date
信号截至	Signal as of
计算于	Calculated at
截至	As of
北京时间	China Standard Time
成交金额	Trade amount
最新日线	Latest daily bars
股数	Shares
份数	Units
人民币场内 ETF	Mainland-listed RMB ETF
来源报价	Provider quote
已确认历史	Confirmed history
服务器采集	Server collection
本次更新失败：	Update failed: 
使用市场总览的后台开关；境内交易时段约30秒检查报价，网页约5秒同步。	Use the automation switches on Market overview. During mainland trading hours, quotes are checked about every 30 seconds and the page syncs about every 5 seconds.
冻结研究：	Frozen research: 
统一本金10万元、期末市值结算。	CNY 100,000 initial capital; holdings valued at period end.
同口径目标ETF买入持有：年化	Comparable target-ETF buy-and-hold: CAGR
标签只在本市场、本表情景内比较。	Labels compare only this market and scenario.
参考计算：	Reference calculated: 
使用报价截至：	Quotes used as of: 
本次参考本金	Reference capital
配置不会改变模拟账户	Allocations do not change paper accounts
最近自动周期：	Latest automatic cycle: 
最近策略参考：	Latest strategy reference: 
后台最近提示：	Latest server message: 
目标间隔：报价	Target interval: quotes
确认行情	Confirmed market data
后台正在	Server: 
最近核对	Last checked
个账户	accounts
报价检查	Quote check
确认行情核对	Confirmed data check
等待当前任务完成后采集	Collect after the current job finishes
等待当前任务完成后核对	Check after the current job finishes
个模型已完成现有快照	models have completed the current snapshot
个模型行情待补齐	models await market data
正在计算	Calculating
快照检查	Snapshot checked
显示	Showing
个模型 · 买入、卖出数量包含同时买卖的调仓模型	models · Buy and sell counts include models that rebalance in both directions
仍可手动接续。	Manual continuation is still available.
份	units
元/份	CNY/unit
元	CNY
分钟	minutes
秒	seconds
日线	Daily
小时线	Hourly
` .trim().split('\n').map(line => {const i=line.indexOf('\t');return [line.slice(0,i),line.slice(i+1)];}));

Object.assign(window.ETF_EN,Object.fromEntries(`
采集	Collect
核对	Check
恒生ETF	Hang Seng ETF
恒生科技ETF	Hang Seng TECH ETF
纳指100ETF	Nasdaq-100 ETF
创业板ETF	ChiNext ETF
银行ETF	Bank ETF
黄金ETF	Gold ETF
买	Buy
卖	Sell
策略比较结果.json	Strategy comparison.json
查看本次完整结果	View original job result
任务尚未产生完成结果。	The job has no completed result yet.
此窗口会随任务记录自动更新；关闭窗口后任务仍在后台运行。	This dialog follows job updates. Closing it does not stop the server job.
正在读取任务详情…	Loading job details…
已开启行情与策略参考自动更新。	Automatic prices and strategy references enabled.
已暂停行情与参考自动更新；自动模拟开关保持原设置。	Automatic market and reference updates paused. Simulation settings are unchanged.
已开启全部未暂停账户的后台自动模拟。	Automatic simulation enabled for all unpaused accounts.
已暂停全局自动模拟；行情与参考仍按各自开关运行。	Global automatic simulation paused. Market and reference updates follow their own switch.
参考策略已切换	Reference strategy changed
点击计算参考，获取这个策略对应的配置。	Select “Calculate reference” to see this strategy's allocation.
参考本金已修改	Reference capital changed
点击计算参考，以当前预算重新计算配置。	Select “Calculate reference” to recalculate using this budget.
请输入不少于1,000元的有效本金。	Enter valid capital of at least CNY 1,000.
正在计算参考	Calculating reference
使用已知行情计算，在任务记录中可查看进度。	Calculating from available market data. See the activity log for progress.
结束日期需要晚于开始日期。	The end date must be after the start date.
备份超过25 MiB，请选择较小的完整备份或使用本机程序恢复。	The backup exceeds 25 MiB. Choose a smaller complete backup or restore it with the desktop app.
本金	Capital
服务返回了无法读取的内容	The service returned unreadable content
请求未完成	Request incomplete
来源	Source
每	Every
等待当前任务完成后	After the current job finishes: 
等待核验：	Awaiting validation: 
已跳过	Skipped
个无法读取的账户，原文件保留。	unreadable accounts; original files retained.
删除于	Deleted at
账户截至	Account as of
累计佣金	Total commission
账户行情至	Account market data through
后台自动运行也会核对可接入的已确认日线。	Server automation also checks for newly confirmed daily data.
今日已记录	Recorded today:
笔模拟成交：买入	fills; buys:
笔，卖出	, sells:
笔。	fills.
账户确认至	Account confirmed through
此后操作等待后续完整数据。	Subsequent actions await more complete data.
晚于今天；下方判断属于该历史模拟终点，不能作为今天的判断。	later than today. The decision below applies to that simulation end point, not today.
账户仅确认至	Account only confirmed through
尚未覆盖今天，不能据此认定今天应买卖或继续持有。	today is not covered. This cannot determine whether to buy, sell or hold today.
依据的信号时点：	Signal timestamp used: 
查看今日全部	View all today's
笔成交	fills
判断：	Decision: 
依据截至	Evidence as of
确认信号的参考目标：	Reference target from confirmed signals: 
参考目标尚不等于成交仓位。	A reference target is not an executed position.
后续执行：	Next execution: 
共	Total
条记录 · 最新在前 · 每页	records · Newest first · Per page:
条。完整内容随账户备份导出。	records. The account backup exports the full history.
页	page
曲线	curve
至	to
期末距高点	Terminal drawdown
期末	Period end
万	×10,000
个实际记录点	actual data points
已按所选策略预填	Prefilled strategy
与本金；请自行选择账户起点。历史排名不是自动推荐。	and capital. Choose your own account start date. Historical ranks are not automatic recommendations.
收起或关闭窗口不会停止任务；如需停止，请到任务记录。	Minimizing or closing this window does not stop the job. Use the activity log to stop it.
项结果	results
未纳入：	Excluded: 
已提交，可在后台继续运行。	Submitted; the job continues on the server.
条件目标现金比例：	Conditional target cash weight: 
目标配置须满足策略确认与执行条件；是否已安排买卖，以“下一步意向”为准。份数表示模型参考持仓。	Target weights require confirmation and execution conditions. See “Next intention” for pending orders. Units represent model reference holdings.
任务已接收，读取结果暂未完成：	Job accepted; loading the result is incomplete: 
可收起查看任务，系统会继续核对。	You can minimize and review the job; the system will keep checking.
查看操作依据	View actions and reasons
在已通过趋势确认的资产中，按动量与波动率分配仓位。偏离目标超过5个百分点才调仓；趋势失效按日退出。	Allocate among trend-confirmed assets using momentum and volatility. Rebalance only beyond a 5 percentage-point target deviation; exit failed trends based on daily checks.
与动态强弱使用相同选股和配比；周线确认后检查5个百分点偏离，趋势失效仍按日退出。	Use the same asset selection and weights as Dynamic Strength. Check the 5 percentage-point deviation after weekly confirmation; failed trends still exit on daily checks.
每日检查目标偏离并调仓，跟随更紧，交易频率与费用可能更高。	Check target deviation and rebalance daily. Closer tracking may increase trade frequency and costs.
分阶段配置；股票均转弱时保留合计10%的股票预算，其余根据黄金、国债趋势分配，条件不符留现金。	Staged allocation: retain a 10% equity budget when both equity assets weaken. Allocate the rest using gold and Treasury trends; retain cash where conditions fail.
分阶段配置；股票均转弱时保留合计20%的股票预算。相比0%底仓，仍承担股票继续下跌的风险。	Staged allocation: retain a 20% equity budget when both equity assets weaken. Compared with a 0% floor, this retains exposure to further equity losses.
四态融合；双空时保留合计10%的股票底仓，剩余黄金或现金。短周信号使用保守确认规则。	Four-state blend: retain a 10% equity floor when both equity signals are bearish, with the rest in gold or cash. Short trading weeks use conservative confirmation rules.
四态融合；双空时保留合计20%的股票底仓，剩余黄金或现金。短周信号使用保守确认规则。	Four-state blend: retain a 20% equity floor when both equity signals are bearish, with the rest in gold or cash. Short trading weeks use conservative confirmation rules.
SMA20/60＋唐奇安20/10＋OBV/SMA20；至少2票持有。三种模型中至少两种为多头时入场，否则退出；使用真实60分钟K线。	SMA20/60 + Donchian20/10 + OBV/SMA20. Enter when at least two of the three models are bullish; otherwise exit. Uses actual 60-minute bars.
SKDJ(3,5)＋TRIX(4,8)；固定20个交易日。已完成周K线的K>D且TRIX>信号线时入场；买入算第1日，第21交易日开盘退出。原参数曾历史选优。	SKDJ(3,5) + TRIX(4,8); hold for 20 trading days. Enter when a completed weekly bar has K>D and TRIX above its signal line. Purchase is day 1; exit at day 21's open. Parameters were historically optimized.
前20根最高价入场；前10根最低价退出。收盘突破此前20根最高价买入，跌破此前10根最低价退出，通道不含当前K线。	Enter above the previous 20-bar high; exit below the previous 10-bar low, evaluated at the close. The current bar is excluded from the channel.
Wilder ATR10，倍数3。超级趋势由空转多入场，由多转空退出；始终以完整60分钟K线计算。	Wilder ATR10, multiplier 3. Enter when Supertrend flips from bearish to bullish, exit on the reverse. Always use complete 60-minute bars.
SMA50（50根60分钟K线）。收盘高于50根均线持有，否则现金；不是50日或50周均线。	SMA50 uses fifty 60-minute bars. Hold when the close is above this average; otherwise stay in cash. This is not a 50-day or 50-week average.
目标ETF使用均线、突破、量能三模型投票；目标ETF与黄金各用初始本金50%。各份资金独立复利。	The target ETF uses a moving-average / breakout / volume vote. Split initial capital equally between the target ETF and gold. Each sleeve compounds independently.
目标ETF使用均线、突破、量能三模型投票；目标ETF用50%，银行和黄金各用25%。各份资金独立复利。	The target ETF uses a moving-average / breakout / volume vote. Allocate 50% of initial capital to the target ETF, 25% to banks and 25% to gold. Sleeves compound independently.
目标ETF使用Supertrend；目标ETF用50%，银行和黄金各用25%。各份资金独立复利。	Use Supertrend for the target ETF. Allocate 50% of initial capital to the target ETF, 25% to banks and 25% to gold. Sleeves compound independently.
三份资金各占1/3，分别按目标ETF、银行、黄金的200日均线过滤；未通过的份额保留现金。	Split capital into thirds. Apply a 200-day moving-average filter separately to the target ETF, banks and gold. A sleeve stays in cash when its filter fails.
15点确认信号，目标组合变化时在下一交易日实际开盘调仓；目标不变时持仓自然漂移。	Confirm signals at 15:00. When target weights change, rebalance at the next trading-day open; otherwise allow positions to drift with prices.
目标ETF多头时配置目标ETF，否则按黄金周线信号选择黄金或现金。	Hold the target ETF when bullish; otherwise choose gold or cash using gold's weekly signal.
目标ETF多头时配置目标ETF，否则配置黄金。	Hold the target ETF when bullish; otherwise hold gold.
目标ETF多头时配置目标ETF，否则银行、黄金各分配一半预算，再由各自信号决定持仓或现金。	Hold the target ETF when bullish. Otherwise split the budget equally between bank and gold sleeves, with each signal determining investment or cash.
已生成下一可执行日开盘目标	A target is set for the next eligible trading-day open
动态多头资格未通过，目标0%	Dynamic bullish qualification failed; target 0%
动态多头资格通过	Dynamic bullish qualification passed
原指标：	Original indicators: 
含息指标价	Distribution-adjusted indicator price: 
有效评分	Effective score: 
多头资格失效，退出：	Bullish qualification failed; exit: 
组合目标改变	Portfolio target changed
熊市减至防守仓位	Reduce to a defensive allocation in a bearish state
牛市信号进攻	Increase risk exposure on a bullish signal
维持防御配置	Maintain defensive allocation
持满20日退出	Exit after holding 20 trading days
持有期满	Holding period completed
三信号投票	Three-signal vote
超级趋势	Supertrend
投票择时	Voting-based timing
独立本金	Independent capital
日线组合	Daily portfolio
独立资金：模型要求现金。	 sleeve: the model requires cash.
独立资金：模型允许持有。	 sleeve: the model permits investment.
的200日均线过滤：未通过，对应资金保留现金。	 200-day MA filter failed; this sleeve remains in cash.
的200日均线过滤：通过，目标配置1/3。	 200-day MA filter passed; target weight is one third.
组合信号：多头。	 ensemble signal: bullish.
组合信号：非多头。	 ensemble signal: not bullish.
TRIX：非多头。	 TRIX: not bullish.
TRIX：多头。	 TRIX: bullish.
周线突破：非多头。	 weekly breakout: not bullish.
周线突破：多头。	 weekly breakout: bullish.
指标预热尚未完成，不能把缺失指标当作买卖信号。	Indicator warm-up is incomplete. Missing indicators are not buy/sell signals.
当前账户时刻没有新完成的周K线；上一次周线条件不会在每根小时线重复开仓。	No new weekly bar has closed at this account time. A prior weekly condition does not reopen positions on every hourly bar.
已有退出指令。	An exit instruction is pending.
持有期已满。	The holding period is complete.
退出条件已触发，未成交的卖出指令会继续保留。	Exit conditions triggered. Retain the sell instruction until execution.
账户当前没有持仓，本次确认满足入场条件；尚未记为成交。	The account is in cash and entry conditions are now confirmed. No fill is recorded yet.
账户仍有持仓，没有待执行卖出指令。	The account has positions with no pending sell instruction.
账户当前没有持仓，也没有待执行买入指令。	The account has no positions and no pending buy instruction.
等待模拟卖出	Waiting for simulated sell
等待模拟买入	Waiting for simulated buy
保持现金，等待入场	Hold cash; await entry
等待下一次完整周期确认。	Await the next complete period's confirmation.
创业板ETF买入当日不可卖出；只用真实完整K线开盘记账。	ChiNext ETF units cannot be sold on the purchase date. Record fills only at actual complete-bar opens.
最近确认的策略判断	Latest confirmed strategy decision
这份历史结果未保存更细的触发条件；这里只展示已保存的参考目标和成交原因，不补造指标判断。	This historical result has no detailed trigger conditions. Only saved targets and fill reasons are shown; indicator decisions are not invented.
下一执行时点前，参考目标不代表已成交。	Before execution, a reference target is not a completed fill.
按账户已选策略的原规则判断。	Apply the original rules of the account's selected strategy.
均线	Moving average
年化	CAGR
已到本市场最新确认日	At this market's latest confirmed date
` .trim().split('\n').map(line => {const i=line.indexOf('\t');return [line.slice(0,i),line.slice(i+1)];})));

window.ETF_EN_PATTERNS=[
  [/最大仓位偏离([\d.]+)%，未超过([\d.]+)%阈值，继续持有/g,'Maximum allocation drift $1%; within the $2% threshold. Continue holding.'],
  [/最大仓位偏离([\d.]+)%，超过([\d.]+)%调仓阈值/g,'Maximum allocation drift $1%; above the $2% rebalancing threshold'],
  [/(创业板|纳指100|恒生指数|恒生科技)采用原50周趋势与SKDJ\/TRIX，银行采用原SKDJ规则；黄金和国债通过各自趋势门槛。股票均转弱时股票清仓。/g,'$1 uses the original 50-week trend and SKDJ/TRIX rules; banks use the original SKDJ rules. Gold and Treasuries use their own trend filters. Exit equity positions when both equity assets weaken.'],
  [/(创业板|纳指100|恒生指数|恒生科技)与银行双多时60\/40，单多时100%配置该股票ETF；双空时退出股票，黄金满足条件才接替，否则现金。/g,'Allocate $1 / banks 60:40 when both are bullish, or 100% to the sole bullish equity ETF. When neither is bullish, leave equities and use gold only if qualified; otherwise cash.'],
  [/独立本金各自复利；(创业板|纳指100|恒生指数|恒生科技)在下一60分钟开盘执行，银行\/黄金在下一交易日开盘执行；不在子账户间再平衡。/g,'Sleeves compound independently. $1 executes at the next 60-minute open; banks / gold at the next trading-day open. No rebalancing between subaccounts.'],
  [/最近确认周期：入场条件(已触发|触发|未触发)[；，]退出条件(已触发|触发|未触发)。/g,(_,entry,exit)=>'Latest confirmed period: entry '+(entry==='未触发'?'not triggered':'triggered')+'; exit '+(exit==='未触发'?'not triggered':'triggered')+'.'],
  [/目标ETF在 ([\d: -]+)：入场条件(触发|未触发)，退出条件(触发|未触发)(，已有待卖出指令)?。/g,(_,time,entry,exit,pending)=>'Target ETF at '+time+': entry '+(entry==='未触发'?'not triggered':'triggered')+'; exit '+(exit==='未触发'?'not triggered':'triggered')+(pending?'; sell instruction pending':'')+'.'],
  [/参考仓位已持有 (\d+) 个交易日；按原规则固定持有20个交易日，期满后下一交易日开盘退出。/g,'Reference held for $1 trading days. Hold for a fixed 20 trading days; exit at the next trading-day open after completion.'],
  [/只读参考账户仍在固定持有期，当前为第(\d+)个交易日；即使最新周线指标转弱，也不提前退出。第20日15:00形成退出指令，第21交易日开盘执行。/g,'The reference is on trading day $1 of its fixed holding period. Weak weekly indicators do not cause an early exit. Generate the exit at 15:00 on day 20 and execute at day 21\'s open.'],
  [/(纳指100|恒生指数|恒生科技|创业板)ETF已按现金、费用与整手限制调整数量/g,'$1 ETF units adjusted for available cash, costs and lot sizes'],
  [/当前已持有 (\d+) 个交易日；第20日收盘确认期满后，下一交易日开盘退出。/g,'Held for $1 trading days. Confirm completion at day 20\'s close, then exit at the next trading-day open.'],
  [/(\d+)日年化波动([\d.]+)%/g,'$1-day annualized volatility $2%'],
  [/(\d+)日均线([\d.]+)/g,'$1-day MA $2'],
  [/(\d+)日涨幅([+\-\d.]+)%/g,'$1-day return $2%'],
  [/(\d+)日([+\-\d.]+)%/g,'$1-day return $2%'],
  [/（(\d+)笔合计）/g,' ($1 fills combined)'],
  [/今日已记录 (\d+) 笔模拟成交：买入 (\d+) 笔，卖出 (\d+) 笔。/g,'Recorded $1 simulated fills today: $2 buys and $3 sells.'],
  [/Supertrend 模型处于多头状态；买入要求本根出现由空转多，已有多头状态不等于重新触发买入。/g,'Supertrend is bullish. A buy requires a new bearish-to-bullish flip on this bar; an existing bullish state is not a new entry.'],
  [/Supertrend 模型处于现金状态；买入要求本根出现由空转多，已有多头状态不等于重新触发买入。/g,'Supertrend is in cash. A buy requires a new bearish-to-bullish flip on this bar; an existing bullish state is not a new entry.']
];

Object.assign(window.ETF_EN,Object.fromEntries(`
三种模型中至少两种为多头时入场，否则退出；使用真实60分钟K线。	Enter when at least two of three models are bullish; otherwise exit. Uses actual 60-minute bars.
SMA20/60＋唐奇安20/10＋OBV/SMA20；至少2票持有	SMA20/60 + Donchian20/10 + OBV/SMA20; hold with at least 2 votes
已完成周K线的K>D且TRIX>信号线时入场；买入算第1日，第21交易日开盘退出。原参数曾历史选优。	Enter on a completed weekly bar with K>D and TRIX above its signal line. Purchase is day 1; exit at day 21's open. Parameters were historically optimized.
SKDJ(3,5)＋TRIX(4,8)；固定20个交易日	SKDJ(3,5) + TRIX(4,8); fixed 20 trading days
收盘突破此前20根最高价买入，跌破此前10根最低价退出，通道不含当前K线。	Buy when the close exceeds the prior 20-bar high; exit below the prior 10-bar low. Exclude the current bar from the channel.
前20根最高价入场；前10根最低价退出	Enter at the previous 20-bar high; exit at the previous 10-bar low
超级趋势由空转多入场，由多转空退出；始终以完整60分钟K线计算。	Enter when Supertrend turns bullish; exit when it turns bearish. Use complete 60-minute bars.
Wilder ATR10，倍数3	Wilder ATR10, multiplier 3
收盘高于50根均线持有，否则现金；不是50日或50周均线。	Hold above the 50-bar moving average; otherwise cash. This is not a 50-day or 50-week average.
SMA50（50根60分钟K线）	SMA50 (fifty 60-minute bars)
较高收益·两份独立本金	Higher return · Two independent sleeves
收益与回撤折中·三份本金	Return / drawdown balance · Three sleeves
较低回撤·三份本金	Lower drawdown · Three sleeves
本组回撤最低·均线过滤	Lowest group drawdown · MA filter
本组年化最高·高回撤	Highest group CAGR · High drawdown
黄金持有对照·高回撤	Gold holding comparison · High drawdown
银行黄金切换·高回撤	Bank / gold switching · High drawdown
50%创业板三指标＋50%黄金周线突破	50% ChiNext three-indicator model + 50% gold weekly breakout
50%创业板三指标＋25%银行TRIX＋25%黄金周线突破	50% ChiNext three-indicator model + 25% bank TRIX + 25% gold weekly breakout
50%创业板Supertrend＋25%银行TRIX＋25%黄金周线突破	50% ChiNext Supertrend + 25% bank TRIX + 25% gold weekly breakout
三资产各自MA200，各占1/3预算	Three assets, each with its own MA200 filter and one-third budget
创业板退出后按黄金周线突破持有黄金或现金	After exiting ChiNext, use gold's weekly breakout to choose gold or cash
创业板退出后转黄金持有	After exiting ChiNext, hold gold
创业板退出后转银行TRIX与黄金周线突破	After exiting ChiNext, use bank TRIX and gold weekly breakout
人民币场内跨境ETF；收盘确认后推进模拟，小时策略仍按真实小时顺序重放。费用万三/最低5元，滑点万二，期末按市值计价。	Mainland-listed RMB cross-border ETFs. Advance after close confirmation; hourly strategies replay actual bars in order. Commission 0.03%, minimum CNY 5; slippage 0.02%; mark to market at period end.
研究回撤最低	Lowest research drawdown
研究年化最高	Highest research CAGR
尚无完整比较，暂不标注排名；在“策略对比”页运行比较后自动显示。	No complete comparison yet. Rankings appear after a completed run on the comparison page.
收盘产生信号 → 下一可执行日开盘模拟；佣金万三、每笔最低5元，单边滑点万二；买入100份整数倍。	Close signal → next eligible trading-day open. Commission 0.03%, minimum CNY 5 per fill; one-way slippage 0.02%; buys in lots of 100 units.
三类账户独立记账；启用自动模拟后，只在确认数据到达时按各账户原规则推进。	Three account types keep separate ledgers. Automatic runs advance only on confirmed data using each account's original rules.
原9比较期末按市值结算；五策略和七组合比较按原研究口径期末清算，不能直接混排。	Original 9 comparisons mark to market at period end. The 5-strategy and 7-portfolio groups use their research liquidation convention. Do not rank these groups together directly.
尚未采集当天报价，请刷新；已确认的历史行情仍可用于研究。	No quotes collected today. Refresh to retrieve them; confirmed history is still available for research.
市场数据与账户模拟日期是两回事；参考配置不直接成交，自动模拟只使用已确认数据。	Market dates and account simulation dates differ. Reference allocations do not execute directly; automatic simulation uses confirmed data only.
这是指标模型状态，实际账户还需检查持仓、待执行指令及T+1。	This is an indicator state. Accounts must also check positions, pending instructions and T+1 eligibility.
周线	Weekly
模型保持多头	Model remains bullish
仅在新完成周K线时判断入场；已持仓账户按20交易日时钟退出。	Assess entry only on a newly completed weekly bar. Invested accounts follow the 20-trading-day holding clock.
模型保持现金	Model stays in cash
60分钟行情为新浪口径；与腾讯日线个别价格及成交量存在差别，保留原数据。	60-minute bars use Sina data. Some prices and volumes differ from Tencent daily data; original data is preserved.
等待当天报价	Waiting for today's quotes
国泰纳指100 ETF	Guotai Nasdaq-100 ETF
华夏恒生ETF	ChinaAMC Hang Seng ETF
华夏恒生科技ETF	ChinaAMC Hang Seng TECH ETF
多资产策略包含黄金、银行或国债贡献，不能视为纯目标ETF择时收益。	Multi-asset strategies include gold, bank or Treasury contributions, not pure target-ETF timing returns.
境内人民币ETF按境内交易时段报价；不等于美股或港股本地ETF，海外休市、汇率和溢价可能影响价格。	Mainland RMB ETFs quote during mainland trading hours. They are not US- or Hong Kong-listed local ETFs. Holidays, FX and premiums can affect prices.
原研究不是未见样本外验证。历史溢价/NAV时间资料不完整，未模拟溢价过滤、排队与大额冲击。	The original research is not unseen out-of-sample validation. Historical premium / NAV timing data is incomplete; premium filters, queues and large-order impact are not modeled.
行情尚未跟上应确认周期	Market data has not reached the required confirmed period
保留旧依据，等待后台补齐。	Keep the historical reasoning while the server catches up.
交易日历需更新	Trading calendar needs updating
交易中	Market open
部分报价来自历史日期；来源时间如实保留，不冒充今天。	Some quotes are from earlier dates. Their original timestamps are retained and are not presented as today's quotes.
账户名称应为1至80个字符。	Account name must contain 1–80 characters.
本金请输入有效数字。	Enter a valid numeric capital amount.
本金须为1,000至100亿元之间的有限数字。	Capital must be a finite number between CNY 1,000 and CNY 10 billion.
日期应为YYYY-MM-DD。	Use the date format YYYY-MM-DD.
所选区间没有共同完整交易日。	No common complete trading day exists in the selected period.
未知成本情景。	Unknown cost scenario.
账户日期已变化，请刷新页面后再操作。	The account date has changed. Refresh before continuing.
账户校验不符，停止接续。	Account integrity check failed. Continuation stopped.
历史账户前缀不一致，拒绝改写既有成交。	Historical account records differ. Existing fills will not be overwritten.
密码错误	Incorrect password
访问密码错误	Incorrect access password
登录失败	Sign-in failed
需要登录	Sign-in required
已完成往返交易数	Completed round trips
` .trim().split('\n').map(line=>{const i=line.indexOf('\t');return[line.slice(0,i),line.slice(i+1)];})));

Object.assign(window.ETF_EN,Object.fromEntries(`
等待执行	Waiting to run
最近确认判断	Latest confirmed decision
按信号建仓 / 加仓	Enter / add based on signal
减仓 / 退出	Reduce / exit
调整仓位	Rebalance positions
等待可执行报价	Waiting for an executable quote
保持现金	Remain in cash
所有趋势条件失效时退出至现金。	Exit to cash when all trend conditions fail.
每次收盘重新确认；已确认的方案遇停牌顺延至可执行日。	Reconfirm at each close. Confirmed plans affected by a suspension wait for an eligible execution day.
已生成目标，等待下一可执行交易日开盘；成交份数届时按资金、价格和费用计算。	A target is ready for the next eligible trading-day open. Units will be calculated using available capital, prices and costs at execution.
没有待执行目标；等待原策略的下一次确认。	No target is pending. Wait for the strategy's next confirmation.
没有可用的已确认策略周期。	No confirmed strategy period is available.
等待原策略确认调仓条件。	Wait for the original strategy to confirm rebalancing conditions.
等待首次确认	Waiting for initial confirmation
等待完整信号	Waiting for a complete signal
账户尚未推进到完整K线。	The account has not advanced to a complete bar.
暂未生成	Not generated yet
暂无待执行指令。	No pending instruction.
现金等待；使用完整周期信号，下一根真实完整K线开盘执行。	Wait in cash. Use completed-period signals and execute at the next actual complete bar's open.
固定持有20个交易日后按原执行时点退出。	Hold for 20 trading days, then exit at the original execution time.
买入算第1日，第21交易日开盘退出。	Purchase is day 1; exit at day 21's open.
各份资金独立复利。	Each sleeve compounds independently.
目标ETF使用	The target ETF uses 
均线、突破、量能三模型投票	three-model voting across moving averages, breakouts and volume
目标ETF与黄金各用初始本金50%。	The target ETF and gold each receive 50% of initial capital.
目标ETF用50%，银行和黄金各用25%。	The target ETF receives 50%; bank and gold receive 25% each.
目标ETF组合信号	Target ETF combined signal
等待已完成周线确认；风险失效退出仍按日检查	Wait for a completed weekly confirmation; check risk exits daily
5年国债ETF	5-year Treasury ETF
统一本金10万元、期末市值结算。	Common CNY 100,000 capital; marked to market at period end.
模型允许持有	Model allows holding
模型要求现金	Model requires cash
非多头	Not bullish
多头	Bullish
黄金周线突破	Gold weekly breakout
`.trim().split('\n').map(line=>{const i=line.indexOf('\t');return[line.slice(0,i),line.slice(i+1)];})));
window.ETF_EN_PATTERNS.push(
 [/股票均转弱时仍保留([\d.]+)%股票预算。/g,'Keep a $1% equity budget when both equity trends weaken.'],
 [/最近确认周期：入场条件(已触发|未触发)，退出条件(已触发|未触发)。/g,(_,entry,exit)=>'Latest confirmed period: entry '+(entry==='已触发'?'triggered':'not triggered')+'; exit '+(exit==='已触发'?'triggered':'not triggered')+'.'],
 [/账户资产曲线，(.+?)至(.+?)，期末([\d,.]+)元/g,'Account equity curve, $1 to $2; ending equity CNY $3'],
 [/资产曲线，(.+?)至(.+?)，期末([\d,.]+)元/g,'Equity curve, $1 to $2; ending equity CNY $3'],
 [/([\d.]+)笔合计/g,'$1 fills combined'],
 [/的200日均线过滤：(通过，目标配置1\/3|未通过，对应资金保留现金)。/g,(_,value)=>': 200-day MA filter '+(value.startsWith('通过')?'passed; target weight 1/3.':'failed; keep this sleeve in cash.')]
);
Object.assign(window.ETF_EN,{"最新动态":"Latest activity"});

Object.assign(window.ETF_EN,{
"原9配置":"Original 9 allocation strategies",
"5个目标ETF择时":"Five target-ETF timing models",
"7个组合":"Seven portfolios",
"独立资金组合":"Independent-capital portfolios"
});
Object.assign(window.ETF_EN,{"SKDJ(3,5)＋TRIX(4,8)；固定20个交易日。已完成周K线的K>D且TRIX>信号线时入场；固定持有20个交易日后按原执行时点退出。原参数曾历史选优。":"SKDJ(3,5) + TRIX(4,8); fixed 20 trading days. Enter on a completed weekly bar when K>D and TRIX exceeds its signal line. Hold for 20 trading days, then exit at the original execution time. Parameters were historically optimized."});

Object.assign(window.ETF_EN,{
"新行情修订了账户配套历史；原账户和待执行目标保持不变。":"New market data revises the account's underlying history. The existing account and pending targets are preserved.",
"尚无晚于账户日期的已确认完整数据。":"No complete confirmed data is available after the account date."
});

// Company research UI. Company names and original financial evidence remain verbatim.
Object.assign(window.ETF_EN,{
"AI 已阅读，保留判断":"AI reviewed; no conclusion",
"已有报告基于较早数据，请重新补齐分析。":"This report uses older data. Update the financials and analysis.",
"估值已按最新市场快照更新；已有 AI 解读仍保留生成时的依据。":"Valuation reflects the latest market snapshot. Existing AI commentary retains the evidence used when it was generated.",
"估值已按最新市场快照更新；财务分析仍保留生成时的依据。":"Valuation reflects the latest market snapshot. Financial analysis retains the evidence used when it was generated.",
"可进行财务初筛":"Financially screenable",
"暂未参与通用评分":"Not generally scored",
"缺资料、专项行业或重大事项待核查":"Missing data, specialist sectors or material issues",
"已取得估值行情":"Valuation data obtained",
"缺行情时不判断价格":"No price assessment without market data",
"财务初筛分":"Financial screening score",
"财务初筛分优先":"Financial score first",
"市盈率 PE 升序":"P/E: low to high",
"缺资料与专项行业暂不参与通用评分":"Missing data and specialist sectors are not generally scored",
"0 表示暂停 AI 调用，仍可扫描和补齐财务数据。":"0 pauses AI calls. Financial data can still be scanned and updated.",
"先前设置已保存，新的修改尚未保存。":"Previous settings saved. Your newer changes are still unsaved.",
"暂不评分":"Not scored",
"待补齐的核查项目":"Items requiring evidence",
"初筛分怎样得出":"How the screening score is calculated",
"按公开规则计算，缺项不填零、不重新分配权重。分数用于安排财务研究顺序。":"Calculated using disclosed rules. Missing items are not set to zero and weights are not redistributed. Scores prioritize financial research.",
"缺资料，本项不计分":"Insufficient data; this item is not scored",
"合并净利润":"Consolidated net profit",
"● 合并净利润":"● Consolidated net profit",
"本次研究的边界":"Limits of this research",
"AI 已阅读 · 证据不足，保留判断":"AI reviewed · insufficient evidence; no conclusion",
"补齐历年财务与证据":"Update financials and evidence",
"当前可补齐财务资料；连接 AI 服务后才生成 AI 报告。":"Financial evidence can be updated now. AI reports require a connected provider.",
"当前 AI 调用额度已用完或设为 0，仍可更新财务资料。":"The AI allowance is exhausted or set to 0. Financial evidence can still be updated.",
"事实":"Fact",
"推断":"Inference",
"反面证据":"Counterevidence",
"资料缺口":"Missing evidence",
"生意模式":"Business model",
"竞争优势":"Competitive advantages",
"财务质量":"Financial quality",
"公司治理":"Governance",
"研究观点":"Research observation",
"待核查":"Needs review",
"AI选公司":"AI research",
"让机器读财报，把依据留下。":"Let machines read. Keep the evidence.",
"扫描全 A 股，按行业筛查，再深入研究候选公司。公司质量、财务风险与价格分别判断。":"Scan the A-share universe, screen within sectors, then research candidates. Assess quality, financial risk and valuation separately.",
"↻ 扫描全市场":"↻ Scan all A shares",
"从公司出发，先看证据。":"Start with the business and its evidence.",
"自动整理财务趋势、同行比较和风险。候选是继续研究的起点，不是买入指令。港股研究后续扩展。":"Automatically review financial trends, peers and risks. Candidates are a starting point for research, not buy instructions. Hong Kong coverage will follow.",
"全市场覆盖状态":"Market coverage",
"A 股公司总数":"A-share universe",
"公司名单已核验":"Company list verified",
"名单覆盖尚未确认":"Universe not yet verified",
"已取得财务资料":"Financial data obtained",
"不等于已完成判断":"Data is not a completed assessment",
"可进行质量判断":"Assessable companies",
"关键资料达到要求":"Required data available",
"缺少关键资料":"Missing essential data",
"保留为空，不自动加分":"Left blank; no automatic score",
"待深入研究候选":"Research candidates",
"按当前规则筛选":"Based on the current screen",
"待核验":"Unverified",
"研究进度":"Research progress",
"正在读取全市场资料状态…":"Loading market coverage…",
"扫描进度":"Scan progress",
"停止本次扫描":"Stop this scan",
"等待扫描":"Waiting for a scan",
"部分完成":"Partly complete",
"先扫描并核验 A 股公司名单，再按可取得的财务资料筛查。":"First verify the A-share universe, then screen the financial data available.",
"正在更新公司财务资料…":"Updating company financials…",
"已有结果会保留，扫描只更新公司研究资料。":"Existing results are retained. The scan updates company research only.",
"AI 服务已连接；深入报告将保留依据和未解决问题。":"AI is connected. Research reports retain evidence and unresolved questions.",
"AI 尚未配置：目前只有财务规则筛查，不是 AI 深入报告。":"AI is not configured. Current results are rule-based financial screening, not AI research.",
"自动研究设置":"Research settings",
"每天自动扫描":"Scan automatically each day",
"关闭网页后，服务器仍按计划更新。":"Scheduled updates continue after you close the page.",
"每日 AI 报告上限":"Daily AI report limit",
"每日 AI 调用上限":"Daily AI request limit",
"每天自动扫描并研究候选":"Scan and research candidates daily",
"每日扫描财务资料；AI 已配置且有剩余调用次数时，自动深读候选。关闭网页后仍继续。":"Scan financial data daily. Research candidates automatically when AI is configured and requests remain. This continues after the page is closed.",
"0 表示暂停自动和手动 AI 调用，仍可扫描和补齐财务数据。已发出的请求失败也计次；次数不等于人民币费用上限。":"0 pauses both automatic and manual AI requests. Financial data can still be scanned and enriched. Failed requests count once sent; this is not a monetary spending limit.",
"关闭自动研究只停止继续安排任务；已提交的任务可单独停止。手动深读也受每日调用上限约束。":"Turning off automatic research stops scheduling new tasks. Submitted tasks can be stopped individually. Manual AI research uses the same daily request limit.",
"AI 服务已配置；是否成功生成报告，以实际研究结果为准。":"AI settings are saved. Successful report generation must be confirmed in the research results.",
"每日 AI 调用上限必须是 0 到 50 的整数。":"The daily AI request limit must be a whole number from 0 to 50.",
"当前 AI 调用次数已用完或设为 0；点击只会补齐财务资料，不会发出新的 AI 请求。":"The daily AI request limit has been reached or is set to 0. This action enriches financial data without sending new AI requests.",
"0 表示暂停自动 AI 报告，仍可扫描财务数据。":"0 pauses automatic AI reports. Financial data can still be scanned.",
"AI 服务连接":"AI connection",
"连接后才会生成真正的 AI 深入报告。密钥仅提交到当前服务器，保存后不会回显；留空保留原密钥。":"AI research requires a connection. Your key is sent only to this server and never returned after saving. Leave blank to keep the existing key.",
"服务类型":"Provider",
"兼容服务":"Compatible provider",
"其他已支持的兼容配置":"Other supported compatible configuration",
"连接后才会生成真正的 AI 深入报告。DeepSeek 需要自己的 API 密钥，OpenAI 密钥不能通用；如账户余额不足，需先充值。密钥仅提交到当前服务器，保存后不会回显。同一服务留空保留密钥；更换服务地址会清除旧密钥。":"AI research requires a connection. DeepSeek needs its own API key; an OpenAI key cannot be used. Top up your DeepSeek account if its balance is insufficient. Your key is sent only to this server and never returned after saving. Leave blank to keep a key for the same provider; changing the service address clears the old key.",
"服务地址已更换。保存后会清除原服务密钥；请填写新服务的 API 密钥。":"The service address has changed. Saving will clear the previous provider's key; enter an API key for the new provider.",
"服务地址已更换，尚未提交的密钥已清空。请填写新服务的 API 密钥。":"The service address has changed and the unsaved key has been cleared. Enter an API key for the new provider.",
"填写新服务的 API 密钥":"Enter an API key for the new provider",
"模型名称":"Model name",
"填写服务支持的模型":"Enter a model supported by your provider",
"服务地址":"Service URL",
"API 密钥":"API key",
"留空保留已保存的密钥":"Leave blank to keep the saved key",
"密钥已保存。留空会继续使用原密钥。":"A key is saved. Leave blank to keep using it.",
"尚未保存 API 密钥。":"No API key has been saved.",
"保存研究设置":"Save research settings",
"研究设置已保存。":"Research settings saved.",
"设置已修改，保存后生效。":"Settings changed. Save to apply them.",
"每日 AI 报告上限必须是 0 到 50 的整数。":"The daily AI report limit must be a whole number from 0 to 50.",
"服务地址需要使用 HTTPS，且不能包含用户名或密码。":"Use an HTTPS URL without a username or password.",
"公司观察清单":"Company watchlist",
"读取最新结果 ↻":"Refresh results ↻",
"搜索公司":"Search companies",
"公司名称或证券代码":"Company name or ticker",
"行业":"Sector",
"全部行业":"All sectors",
"排序":"Sort",
"质量评分优先":"Quality score first",
"财务风险优先":"Financial risk first",
"估值由低到高":"Valuation: low to high",
"证券代码":"Ticker",
"只看候选公司":"Candidates only",
"缺少关键资料的公司不计质量分":"No quality score without essential data",
"当前筛选没有结果":"No companies match these filters",
"研究清单正在建立":"Building the research watchlist",
"可以调整行业、关键词，或取消“只看候选公司”。":"Try another sector or keyword, or turn off Candidates only.",
"点击“扫描全市场”开始，真实资料取得后会出现在这里。资料不足不会生成好公司结论。":"Start with Scan all A shares. Results appear as real data arrives. Missing data never produces a positive company assessment.",
"显示更多公司":"Show more companies",
"资料待补齐":"Data incomplete",
"研究候选":"Research candidate",
"继续观察":"Keep observing",
"质量评分":"Quality score",
"财务风险":"Financial risk",
"估值":"Valuation",
"较低":"Lower",
"中等":"Medium",
"较高":"Higher",
"高风险":"High risk",
"待核实":"Needs verification",
"行业待确认":"Sector unverified",
"尚未取得足够资料形成判断。":"Insufficient data for an assessment.",
"已有 AI 深入报告":"AI report available",
"财务规则筛查":"Financial rule screen",
"查看依据 →":"View evidence →",
"全市场扫描已提交，关闭网页后仍可继续。":"Market scan submitted. It can continue after you close the page.",
"停止请求已提交，已取得的资料会保留。":"Stop requested. Data already obtained will be retained.",
"公司研究":"Company research",
"关闭公司研究":"Close company research",
"正在读取公司资料":"Loading company research",
"财务、风险与来源会在这里分别显示。":"Financials, risks and sources are shown separately.",
"暂时无法读取":"Unable to load right now",
"重新读取":"Try again",
"资料不足":"Insufficient data",
"估值判断":"Valuation assessment",
"这家公司值得继续研究吗？":"Does this company merit further research?",
"当前资料还不足以形成结论。":"Current evidence is insufficient for a conclusion.",
"缺失数据不计分，也不会自动视为低风险。":"Missing data receives no score and is not treated as low risk.",
"入选依据以当前资料与筛查规则为准。":"Selection reflects current data and screening rules.",
"风险与尚未解决的问题":"Risks and unresolved questions",
"尚未形成完整风险清单，不代表没有风险。":"The risk review is incomplete; this does not mean there are no risks.",
"价格与公司质量分开看":"Assess price separately from quality",
"暂未形成估值判断。低估值本身不能证明公司便宜。":"No valuation conclusion yet. A low multiple alone does not establish a bargain.",
"市盈率 PE":"Price / earnings",
"市净率 PB":"Price / book",
"不适用 / 缺数据":"Not applicable / unavailable",
"财务趋势":"Financial trends",
"尚未取得可比较的历史财务数据。":"Comparable historical financials are not yet available.",
"金额单位：人民币元，表内自动换算为万或亿。年度与中期报告需分别比较，不把半年数字当成全年。":"Amounts are in CNY, displayed in ten-thousands (万) or hundred-millions (亿). Compare annual and interim reports separately; half-year figures are not full-year results.",
"报告期":"Reporting period",
"营业收入":"Revenue",
"归母净利润":"Profit attributable to owners",
"经营现金流":"Operating cash flow",
"资产负债率":"Liabilities / assets",
"近年年度净利润与经营现金流趋势，详细数值见下表":"Annual net profit and operating cash flow trends; exact values appear in the table below",
"● 归母净利润":"● Net profit",
"● 经营现金流":"● Operating cash flow",
"同行对照":"Peer comparison",
"尚未取得同口径同行数据，暂不做行业排名。":"Comparable peer data is not yet available. No sector ranking is shown.",
"仅比较同口径资料；报告期不同的公司需要进一步核实。":"Compare like-for-like data. Companies with different reporting periods require further review.",
"公司":"Company",
"AI 深入研究":"AI research",
"AI 挑选的原文证据 / 待核查问题":"AI-selected source excerpts / Questions to verify",
"AI 只挑选原文证据并整理待核查问题；不构成完整公司结论，也不是买入建议。":"AI only selects source excerpts and organizes questions to verify. This is not a complete assessment of the company or a buy recommendation.",
"AI 证据整理 · 非完整公司结论":"AI evidence selection · Not a complete company assessment",
"这是部分证据整理：部分条目未通过校验，或本次只读取了财报节选。":"This is a partial evidence selection: some items failed validation or only financial-report excerpts were read.",
"未采用的模型内容不会作为结论发布，也不在这里展示。":"Rejected model content is not published as a conclusion or displayed here.",
"这是旧模式的 AI 输出，尚未通过当前证据整理校验。请重新整理证据。":"This output is from the previous AI mode and has not passed current evidence-selection checks. Run evidence selection again.",
"证据整理的标记或内容不完整，暂不展示。":"Evidence-selection metadata or content is incomplete and cannot be displayed yet.",
"AI 尚未配置。上方为财务规则筛查，尚无 AI 证据整理。":"AI is not configured. The results above are financial-rule screening, without AI evidence selection.",
"AI 尚未配置：目前只有财务规则筛查，尚无 AI 证据整理。":"AI is not configured: only financial-rule screening is available, without AI evidence selection.",
"AI 服务已配置；证据整理是否完成，以实际任务结果为准。":"AI settings are saved. Check task results to confirm whether evidence selection completed.",
"可以让 AI 从已取得的资料中挑选原文证据，并列出还需核查的问题。":"AI can select source excerpts from the available materials and list questions that still need verification.",
"当前可补齐财务资料；配置 AI 后才可整理原文证据和待核查问题。":"Financial data can be enriched now. Configure AI to select source excerpts and organize questions to verify.",
"已有 AI 证据整理":"AI evidence selection available",
"历史 AI 结果待复核":"Previous AI results need review",
"更新 AI 证据整理":"Update AI evidence selection",
"整理这家公司的财报证据":"Organize this company's financial evidence",
"原文摘录":"Source excerpt",
"风险原文":"Source excerpt on risks",
"待核查推断":"Inference to verify",
"估值已按最新市场快照更新；已有 AI 证据整理仍保留生成时的依据。":"Valuation reflects the latest market snapshot. Existing AI evidence selections retain the evidence used when they were generated.",
"每日扫描财务资料；AI 已配置且有剩余调用次数时，自动整理候选证据。关闭网页后仍继续。":"Scan financial data daily. Select evidence for candidates when AI is configured and requests remain. This continues after the page is closed.",
"关闭自动研究只停止继续安排任务；已提交的任务可单独停止。手动整理证据也受每日调用上限约束。":"Turning off automatic research stops scheduling new tasks. Submitted tasks can be stopped individually. Manual evidence selection uses the same daily request limit.",
"配置后可使用 AI 证据整理，展示原文与待核查问题，不形成完整公司结论。DeepSeek 需要自己的 API 密钥，OpenAI 密钥不能通用；如账户余额不足，需先充值。密钥仅提交到当前服务器，保存后不会回显。同一服务留空保留密钥；更换服务地址会清除旧密钥。":"Configure AI to select source excerpts and questions to verify, not a complete company assessment. DeepSeek needs its own API key; an OpenAI key cannot be used. Top up your DeepSeek account if its balance is insufficient. Your key is sent only to this server and never returned after saving. Leave blank to keep a key for the same provider; changing the service address clears the old key.",
"程序按财务规则初筛，AI 挑选原文证据与待核查问题。当前模式不形成完整公司结论；候选不是买入指令。港股研究后续扩展。":"The app screens financial data using rules; AI selects source excerpts and questions to verify. This mode does not produce a complete company assessment, and candidates are not buy instructions. Hong Kong company research is planned for later.",
"AI 生成 · 需结合原文核验":"AI generated · verify against original sources",
"AI 尚未配置。上方为财务规则筛查，尚未生成 AI 深入报告。":"AI is not configured. The information above is rule-based screening; no AI research report has been generated.",
"可以让 AI 阅读已取得的资料，进一步分析竞争优势、反面证据与不确定性。":"Ask AI to review the available evidence, competitive advantages, counterevidence and uncertainties.",
"查看财务规则报告":"View the financial rule report",
"正在准备研究资料…":"Preparing research evidence…",
"停止本次研究":"Stop this research",
"更新公司研究":"Update company research",
"深入分析这家公司":"Research this company",
"在“自动研究设置”中连接 AI 服务后可用。":"Connect an AI provider in Research settings to enable this.",
"证据与资料来源":"Evidence and sources",
"当前尚无可核验的来源链接；结论需要补齐原始资料。":"No verifiable source links yet. Original evidence is still required.",
"查看原始资料":"View original evidence",
"资料来源":"Source",
"筛查帮助缩小研究范围，仍需核对行业差异、原始公告与估值假设。历史数据和 AI 结论都不保证未来收益。":"Screening narrows the research field. Sector differences, original filings and valuation assumptions still need verification. Historical data and AI conclusions do not guarantee future returns."
});
window.ETF_EN_PATTERNS.push(
  [/已保留 ([\d,.]+) 项 · 未采用 ([\d,.]+) 项/g,'Retained $1 items · Rejected $2 items'],
  [/资料覆盖 ([\d,.]+) \/ ([\d,.]+)/g,'Evidence coverage $1 / $2'],
  [/已覆盖 ([\d,.]+) \/ ([\d,.]+) 权重；缺项不重新分配权重。/g,'Covered weight: $1 / $2. Missing weights are not redistributed.'],
  [/今日 AI 调用 ([\d,.]+) \/ ([\d,.]+)/g,'AI calls today: $1 / $2'],
  [/本项 ([\d,.]+) \/ ([\d,.]+) 分/g,'Item score: $1 / $2'],
  [/本次 AI 使用 ([\d,.]+) 页节选；不代表精读全部财报。/g,'AI used excerpts from $1 pages; it did not read every page of all reports.'],
  [/当前符合条件：([\d,.]+) 家/g,'Matching companies: $1'],
  [/显示更多公司（已显示 ([\d,.]+) \/ ([\d,.]+)）/g,'Show more companies ($1 / $2 displayed)'],
  [/资料日期：/g,'Data date: '],
  [/本次已处理 /g,'Processed in this scan: '],
  [/报告期：/g,'Reporting period: '],
  [/获取日：/g,'Retrieved: '],
  [/价格日期：/g,'Price date: ']
);
// Phase 1: multi-year financial quality, separate from six-factor screening.
Object.assign(window.ETF_EN, {
"多年财务质量":"Multi-year financial quality",
"程序按年度财务数据计算；与六项初筛并列，不是完整公司判断，也不消耗 AI 调用。":"Calculated from annual financial data alongside the six-factor screen. This is not a complete company assessment and uses no AI calls.",
"多年分析版本待更新，请补齐资料后重新查看。":"The multi-year analysis version needs updating. Enrich the financial data and reopen this report.",
"此报告尚无多年财务分析，请补齐历年财务资料。":"This report has no multi-year financial analysis yet. Enrich the historical financial data.",
"以下是旧报告中的多年分析，尚未按最新资料重新核验。":"This multi-year analysis is from a cached report and has not been checked against the latest data.",
"完整年度覆盖":"Complete core annual coverage",
"完整年度仅指收入、合并利润、归母、扣非归母、经营现金与 ROE 核心字段齐全；其他字段仍可能缺失。":"A complete core year contains revenue, consolidated profit, attributable and adjusted attributable profit, operating cash flow and ROE. Other fields may still be missing.",
"已取得年度数与完整年度数分别统计":"Available years and complete years are counted separately",
"连续完整年度":"Consecutive core-complete years",
"至少连续 3 年才形成多年观察":"At least 3 consecutive complete years are required",
"官方逐值核验":"Values checked against official filings",
"有 PDF 链接不等于数字已核对":"A PDF link does not mean its numbers have been checked",
"公告日期已取得；不等于已完成严格历史时点验证。":"Publication dates are available; this does not establish strict point-in-time validation.",
"部分公告日期待核验，不能声称通过严格历史时点验证。":"Some publication dates remain unverified. Strict point-in-time validation cannot be claimed.",
"最近 3 个完整年度窗口":"Latest 3-year annual window",
"最近 5 个完整年度窗口":"Latest 5-year annual window",
"该窗口尚无可用分析。":"Analysis is not yet available for this window.",
"窗口不完整，不以其他年份或部分合计冒充完整窗口。":"This window is incomplete. Other years or partial totals do not fill the gap.",
"有条件的财务观察":"Conditional financial observation",
"专项行业待研究":"Sector-specific research required",
"数据存在冲突":"Conflicting data",
"数值可用":"Value available",
"部分资料":"Partial data",
"缺失":"Missing",
"数值为零":"Zero value",
"数值为负":"Negative value",
"公告日期待核验":"Publication date unverified",
"会计口径不兼容":"Incompatible accounting basis",
"数值无效":"Invalid value",
"支持":"Supporting evidence",
"支持与关注并存":"Mixed evidence",
"关注":"Concerns",
"不足与适用限制":"Gaps and applicability",
"状态待确认":"Status unconfirmed",
"供应商数据，未逐值官方核验":"Vendor data; individual values not checked against official filings",
"已做官方逐值核验":"Values checked against official filings",
"未逐值核验":"Individual values not verified",
"核验状态待确认":"Verification status unconfirmed",
"当前没有可核验数值":"No verifiable value is currently available",
"原始数值（未缩写）":"Unabridged value",
"倍":"times",
"小数比例":"decimal ratio",
"年":"years",
"人民币元":"CNY",
"单位待核对":"unit unverified",
"上年同期金额":"Prior comparable amount",
"本期金额":"Current-period amount",
"金额变化":"Change in amount",
"首尾金额变化（人民币元）":"Change across window (CNY)",
"营业收入可比同比":"Comparable revenue change",
"合并净利润可比同比":"Comparable consolidated profit change",
"归母净利润可比同比":"Comparable attributable profit change",
"扣非归母净利润可比同比":"Comparable adjusted attributable profit change",
"经营现金流可比同比":"Comparable operating cash flow change",
"合并经营现金流可比同比":"Comparable consolidated operating cash flow change",
"尚无可跳转的数值来源。":"No linked numeric source is available yet.",
"数值来源与期间":"Numeric sources and periods",
" · 来源链接待补齐":" · Source link unavailable",
"缺失或不可比项目":"Missing or incomparable items",
"支持依据":"Supporting basis",
"反面证据与限制":"Counterevidence and limitations",
"本次没有形成此类观察，不代表已经排除相应问题。":"No observation in this category was established. Related issues have not been ruled out.",
"最近 3 年":"Latest 3 years",
"最近 5 年":"Latest 5 years",
"逐年财务数值与核验依据":"Annual financial values and verification",
"金额为人民币元，按万或亿显示；简化自由现金流＝经营现金流－购建长期资产支付现金，并非股东收益。":"Amounts are in CNY, displayed in 10,000 or 100 million units. Simplified free cash flow is operating cash flow minus cash paid for long-term assets, not owner earnings.",
"存在重述或版本变化，请先查看冲突说明。":"A restatement or version change exists. Review the conflict details first.",
"查看各数值的定义、期间与来源":"View each value's definition, periods and sources",
"最新可比期间（与年度分开）":"Latest comparable period, separate from annual results",
"只比较同季累计期间，不乘倍数年化，不替代年度质量。":"Compare the same cumulative interim period only. Do not multiply to annualize or replace annual quality analysis.",
"尚无同季可比指标。":"No comparable same-period metrics are available yet.",
"多年分析的适用边界":"Scope of multi-year analysis",
"未纳入计算的期间":"Periods excluded from calculations",
"年度存在缺口，趋势图不跨缺年连线；请逐年查看实际数值。":"Annual data has gaps. The chart does not connect across missing years; review the reported values year by year.",
"购建长期资产支付现金":"Cash paid for long-term assets",
"应收账款":"Accounts receivable",
"存货":"Inventory",
"简化自由现金流":"Simplified free cash flow",
"累计营业收入":"Cumulative revenue",
"累计合并净利润":"Cumulative consolidated net profit",
"累计归母净利润":"Cumulative profit attributable to owners",
"累计扣非归母净利润":"Cumulative adjusted profit attributable to owners",
"累计经营现金流":"Cumulative operating cash flow",
"累计购建长期资产支付现金":"Cumulative cash paid for long-term assets",
"累计简化自由现金流":"Cumulative simplified free cash flow",
"累计经营现金流／合并净利润":"Cumulative operating cash flow / consolidated net profit",
"累计扣非归母／归母净利润":"Cumulative adjusted / attributable profit",
"合并净利润为正年度数":"Years with positive consolidated profit",
"经营现金流为正年度数":"Years with positive operating cash flow",
"年度 ROE 均值":"Average annual ROE",
"营业收入年复合增长":"Revenue CAGR",
"合并净利润年复合增长":"Consolidated profit CAGR",
"营业收入首尾变化":"Revenue change across window",
"合并净利润首尾变化":"Consolidated profit change across window",
"应收账款首尾变化":"Receivables change across window",
"存货首尾变化":"Inventory change across window",
"应收增速相对收入":"Receivables growth relative to revenue",
"存货增速相对收入":"Inventory growth relative to revenue"
});
Object.assign(window.ETF_EN, {
"供应商标准化值；尚未完成官方正文逐值核验。":"Standardized vendor value; not individually verified against official filing text.",
"供应商金额，未完成官方逐值核验。":"Vendor amount; not individually verified against official filings.",
"该固定年度无可用记录，不用更旧年度补足。":"No usable record for this fixed year. Older years are not substituted.",
"同报告期版本数值或口径冲突，原始值保留待核对，本项不参与计算。":"Versions of this period conflict in value or basis. Original values are retained for review; this item is excluded from calculations.",
"来源未提供该项。":"The source does not provide this field.",
"来源不是有限有效数值，不当作零。":"The source does not contain a finite valid number; it is not treated as zero.",
"购建长期资产现金支出为负，符号定义待核对，不计算简化现金差额。":"Cash paid for long-term assets is negative. Its sign convention needs review; simplified cash flow is not calculated.",
"经营现金流减购建长期资产支付现金；未区分维持与扩张资本开支，不等于股东可分配现金。":"Operating cash flow minus cash paid for long-term assets. Maintenance and expansion spending are not separated; this is not distributable owner cash.",
"按固定年度窗口相加；任何一年该项缺失则不报告累计。":"Sum the fixed annual window. If this field is missing in any year, no cumulative value is reported.",
"未区分维持性与扩张性开支。":"Maintenance and expansion spending are not separated.",
"同窗累计合并经营现金流除以累计合并净利润；不使用归母利润替代，分母非正时不适用。单年亏损仍须独立核查。":"Cumulative consolidated operating cash flow divided by consolidated net profit in the same window. Attributable profit is not substituted. A non-positive denominator is not applicable; individual loss years still need review.",
"扣非归母与归母利润配对；累计分母非正不适用；一次性损失也可能使比率超过1。":"Adjusted attributable profit is paired with attributable profit. A non-positive cumulative denominator is not applicable; one-off losses can also cause ratios above one.",
"严格大于零才计入；零、负和缺失分别处理，不能用已知年数冒充完整窗口。":"Count only values strictly above zero. Zero, negative and missing values are distinct; known years do not replace a complete window.",
"严格大于零才计入。":"Count only values strictly above zero.",
"各年度披露ROE的简单平均；不是累计投入资本回报，不对季报乘倍数。":"Simple average of disclosed annual ROE, not cumulative return on invested capital. Quarterly figures are not multiplied.",
"首末年度相对变化；基期非正不报告百分比；期末资产与累计收入的比较仅提示核查方向。":"Relative change from the first to last year. No percentage is reported for a non-positive base. Comparing period-end assets with cumulative revenue only suggests questions for review.",
"首末年资产增幅减同期收入增幅；正值提示资金占用可能增快，未证实回款或减值风险。基期非正不比较。":"Asset growth minus revenue growth across the window. A positive value suggests faster capital absorption, not proven collection or impairment risk. Non-positive bases are not compared.",
"本期累计值与上年同一截止期间比较，不乘倍数年化。":"Compare the current cumulative period with the same prior-year cutoff. No multiplication to annualize.",
"上年同期为零或负，百分比不适用；单列金额差，不能称为正常增速。":"The prior-year period is zero or negative. Percentage growth is not applicable; the amount difference is shown separately and is not normal growth.",
"仅同季累计同比，不乘2或4年化；季节性与基期异常仍需核对，不用中期结果替代全年判断。":"Compare the same cumulative period only; do not multiply by two or four. Seasonality and unusual bases need review; interim results do not replace annual assessment.",
"盈利与现金持续性":"Persistence of earnings and cash flow",
"累计利润现金覆盖":"Cumulative profit cash coverage",
"扣非与归母盈利差异":"Adjusted versus attributable profit",
"收入增长与资本回报":"Revenue growth and capital returns",
"应收与存货对收入的变化":"Receivables and inventory relative to revenue",
"累计利润非正，比率不适用。":"Cumulative profit is non-positive; the ratio is not applicable.",
"累计归母利润非正，比率不适用。":"Cumulative attributable profit is non-positive; the ratio is not applicable.",
"收入存在非正年度，CAGR不适用。":"Revenue is non-positive in at least one year; CAGR is not applicable.",
"连续正数不证明未来盈利稳定；须核对价格周期、客户集中与一次性事项。":"Consecutive positive years do not prove future stability. Price cycles, customer concentration and one-off events need review.",
"累计值可能掩盖单年现金流背离；应收账款、存货、票据及保理口径仍需正文核查。":"Cumulative values can hide annual cash-flow divergence. Receivables, inventory, bills and factoring definitions still need review in the filing.",
"高比率也可能来自一次性损失，不能等同主业增长；需逐项核对非经常损益。":"A high ratio can also reflect one-off losses. It is not core business growth; non-recurring items need individual review.",
"未做行业或周期校正，ROE可能受杠杆、回购及权益缩小影响；不等于ROIC或竞争优势。":"No sector or cycle adjustment. ROE may reflect leverage, buybacks or a smaller equity base; it is not ROIC or proof of competitive advantage.",
"资产时点余额与累计收入变化只用于筛查；账龄、坏账、存货跌价与收入确认尚未核实。":"Comparing point-in-time assets with cumulative revenue is screening only. Aging, bad debts, inventory impairment and revenue recognition remain unverified.",
"保留固定年度数字及缺口。":"Fixed annual values and gaps are retained.",
"普通工业企业的现金含量与增长阈值不用于该类公司；专项行业模型尚未完成。":"General industrial-company cash and growth thresholds do not apply to this sector. Its specialist model is not complete.",
"不能选更早年度补足，也不能从已知年度推断缺失年度。":"Do not substitute earlier years or infer missing years from available data.",
"固定年度存在冲突，暂不形成多年判断":"Fixed annual data contains conflicts; no multi-year conclusion is formed",
"最近连续完整年度不足3年，暂不形成多年判断":"Fewer than three consecutive core-complete years; no multi-year conclusion is formed",
"较稳，仍需核验":"relatively stable, requiring verification",
"混合，仍有核查事项":"mixed, with unresolved checks",
"偏弱或存在背离":"weak or divergent",
"银行：多年数字可查，专项评价待完成":"Bank: annual values are available; specialist assessment is pending"
});
window.ETF_EN_PATTERNS.push(
  [/近([35])年财务表现(.+)（供应商数据条件下）/g,'Financial pattern over $1 years: $2 (conditional on vendor data)'],
  [/最近([35])年核心数据未齐/g,'Core data for the latest $1 years is incomplete'],
  [/固定窗口有([\d]+)\/([35])个核心字段齐全年份。/g,'The fixed window contains $1 / $2 core-complete years.'],
  [/合并净利润为正([\d]+)\/([35])年，经营现金流为正([\d]+)\/([35])年。/g,'Positive consolidated profit: $1 / $2 years; positive operating cash flow: $3 / $4 years.'],
  [/累计经营现金流／合并净利润为([\d.]+)。/g,'Cumulative operating cash flow / consolidated profit: $1.'],
  [/累计扣非归母／归母净利润为([\d.]+)。/g,'Cumulative adjusted / attributable profit: $1.'],
  [/收入复合年增长([-\d.]+%)；年度披露ROE算术平均([-\d.]+%)。/g,'Revenue CAGR: $1; arithmetic average of disclosed annual ROE: $2.'],
  [/首末完整年度相隔([24])年；存在非正基数或跨亏损年度时不报告CAGR。/g,'The first and last annual periods are $1 years apart. CAGR is not reported for non-positive values or loss years.'],
  [/按研究截止([^；]+)固定最近已结束自然年度([\d]{4})；缺年不向旧年回退。/g,'At research cutoff $1, the latest ended calendar year is $2. Missing years are not replaced with older ones.'],
  [/已取得 ([\d,.]+) 个年度 · 研究截止 (.+)/g,'Available annual periods: $1 · Research cutoff: $2'],
  [/完整 ([\d,.]+) \/ ([35]) 年 · 已取得 ([\d,.]+) 年/g,'Complete: $1 / $2 years · Available: $3 years'],
  [/缺失年度：([^；]+)；不向较早年度回退补足。/g,'Missing years: $1. Earlier years are not substituted.'],
  [/公告日期：/g,'Published: ']
);
window.ETF_EN_PATTERNS.push(
  [/接口 (\/api\/[^?\s]+) 响应不是有效的 JSON（(\d+)）。请刷新后重试；若刚提交任务，先在任务记录核对。/g,'API $1 returned invalid JSON (HTTP $2). Refresh and retry. If you just submitted a task, check task history first.'],
  [/接口 (\/api\/[^?\s]+) 响应正文未能读取（(\d+)）。请刷新后重试；若刚提交任务，先在任务记录核对。/g,'The response body from API $1 could not be read (HTTP $2). Refresh and retry. If you just submitted a task, check task history first.']
);
// Standalone abbreviated amounts from financial cards. Shift decimal digits as
// strings so currency conversion adds neither floating-point error nor rounding.
window.ETF_EN_PATTERNS.unshift([
  /^(\s*)([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s+(万|亿)(\s*)$/g,
  (_match,leading,amount,unit,trailing)=>{
    const [integer,fraction='']=amount.replace(/,/g,'').replace(/^[+-]/,'').split('.');
    const places=unit==='亿'?8:4,digits=fraction.padEnd(places,'0');
    const whole=(integer+digits.slice(0,places)).replace(/^0+(?=\d)/,'');
    const remainder=digits.slice(places).replace(/0+$/,'');
    const sign=amount.startsWith('-')&&/[1-9]/.test(whole+remainder)?'-':amount.startsWith('+')?'+':'';
    return leading+'CNY '+sign+whole.replace(/\B(?=(\d{3})+(?!\d))/g,',')+(remainder?'.'+remainder:'')+trailing;
  }
]);

'use strict';
// Debt and governance UI dictionary; raw source excerpts remain untranslated.
Object.assign(window.ETF_EN, {
  '债务、流动性与治理核查':'Debt, liquidity and governance checks',
  '查看审计原文与页码':'View audit excerpt and page references',
  '待核查':'Needs review',
  '口径未完整核查':'Scope not fully reviewed',
  '计量口径不一致':'Measurement basis mismatch',
  '本地来源恢复存在缺口，未联网补齐或填零':'Some saved sources could not be recovered; no download or zero substitution was made',
  '原报告保留来源冲突，尚未逐项核清；新增债务资料不能清除该风险。':'The saved report contains unresolved source conflicts. New debt data does not clear this risk.',
  '费用化利息为零，覆盖倍数不适用':'Expensed interest is zero; the coverage multiple is inapplicable',
  '到期债务为零，覆盖倍数不适用':'Debt due is zero; the coverage multiple is inapplicable',
  '分别核对负债期限、现金限制、审计期间和治理披露；不形成完整公司结论或买入建议。':'Review debt maturity, cash restrictions, audit periods and governance disclosures separately. This is not a complete company assessment or a buy recommendation.',
  '当前报告尚无债务与治理核查资料。':'This report has no debt and governance data yet.',
  '债务与治理数据版本待更新，暂不展示旧结构。':'The debt and governance data version needs updating. The old structure is withheld.',
  '资料主体与当前公司不一致，已停止展示。':'The evidence belongs to a different company and has been withheld.',
  '合成验收样本，不是真实公司事实。':'Synthetic test fixture, not facts about a real company.',
  '这是旧报告中的债务与治理资料，尚未按最新数据重新核验。':'This debt and governance data comes from a cached report and has not been checked against the latest data.',
  '财务报告期':'Financial reporting period',
  '研究截止':'Research cutoff',
  '本公司需要行业或盈利阶段专项判断，一般企业债务与覆盖指标不适用。':'This company needs sector- or earnings-stage-specific analysis. General-company debt and coverage metrics do not apply.',
  '有数据或有 PDF 不等于数值语义已核验。':'Available data or a PDF does not establish the meaning or accuracy of its numbers.',
  '债务与到期结构':'Debt and maturity structure',
  '现金限制与流动性':'Cash restrictions and liquidity',
  '上游已提供该项完整口径声明，仍需核对原文。':'The upstream data declares complete coverage for this scope. The filing still needs verification.',
  '完整口径尚未确认；只展示已取得数据与缺口。':'Complete scope is unconfirmed. Only available data and gaps are shown.',
  '尚无可用指标。':'No usable metrics are available.',
  '已取得的原始财务字段':'Available original financial fields',
  '已提供数值':'Value provided',
  '明确为零':'Explicit reported zero',
  '数值为空':'Null value',
  '未提供':'Not provided',
  '数值无效':'Invalid value',
  '数据冲突':'Data conflict',
  '报告期不一致':'Reporting period mismatch',
  '币种待核验':'Currency unverified',
  '单位待核验':'Unit unverified',
  '报表范围不一致':'Reporting scope mismatch',
  '公告日期待核验':'Publication date unverified',
  '晚于研究截止':'After research cutoff',
  '仅算术可计算':'Arithmetic calculation only',
  '资料不足':'Insufficient evidence',
  '尚未核查':'Not reviewed',
  '定位到候选原文':'Candidate excerpt located',
  '待人工核查':'Human review required',
  '状态待核验':'Status unverified',
  '尚无可跳转来源，数值出处仍需补齐。':'No source link is available. Numeric provenance still needs completion.',
  '来源报告期':'Source reporting period',
  '披露日期':'Disclosure date',
  '原文片段只完成文本匹配，主体、金额、范围和上下文仍需核查。':'The excerpt has only been matched to source text. Its entity, amounts, scope and context still require review.',
  '尚未取得这一项的原文；不能据此认定没有风险。':'No excerpt is available for this item. This does not establish an absence of risk.',
  '已识别有息债务部分合计':'Subtotal of identified interest-bearing debt',
  '有息债务总额（含租赁）':'Total interest-bearing debt, including leases',
  '未来12个月到期有息债务账面额':'Book value of interest-bearing debt due within 12 months',
  '利润对费用化融资利息的覆盖':'Profit coverage of expensed financing interest',
  '货币资金扣已披露受限部分':'Cash less disclosed restrictions',
  '经期限核查现金减有息债务':'Maturity-reviewed cash less interest-bearing debt',
  '经期限核查现金/12个月到期有息债务':'Maturity-reviewed cash / interest-bearing debt due within 12 months',
  '财务核查项目':'Financial check',
  '部分合计不是债务总额，未识别的债务仍可能存在。':'A subtotal is not total debt. Unidentified debt may still exist.',
  '扣除已披露受限部分后，仍不能当作随时可用现金。':'Cash after disclosed restrictions is still not necessarily immediately available.',
  '查看公式、组件和数值来源':'View formula, components and numeric sources',
  '计算报告期':'Calculation period',
  '只核对算术关系，尚未独立验证来源语义。':'Arithmetic relationships only; source meaning has not been independently verified.',
  '公式':'Formula',
  '派生指标，依据见对应卡片；不重复累计其组件。':'Derived metric; see its own card. Its components are not added again.',
  '这是负值，不能当作缺失或零。':'This is a negative value, not missing data or zero.',
  '按报告期查看审计与审阅':'Audit and review status by reporting period',
  '财务报表审计、审阅与内部控制意见分别理解；年度意见不沿用到中期。':'Financial statement audits, reviews and internal-control opinions are distinct. Annual opinions are not carried into interim periods.',
  '当前报告期':'Current reporting period',
  '最近年度报告':'Latest annual report',
  '历史报告期':'Historical reporting period',
  '历史审计期间记录':'Historical audit period records',
  '尚未取得该期审计信息，不能沿用其他期间的意见。':'No audit information is available for this period. Opinions from other periods are not substituted.',
  '财务报表审计：无保留意见':'Financial statements: unqualified audit opinion',
  '财务报表审计：保留意见':'Financial statements: qualified audit opinion',
  '财务报表审计：否定意见':'Financial statements: adverse audit opinion',
  '财务报表审计：无法表示意见':'Financial statements: disclaimer of audit opinion',
  '财务报表审计：无保留意见附强调事项':'Financial statements: unqualified opinion with emphasis of matter',
  '财务报表审计：无保留意见附持续经营重大不确定性':'Financial statements: unqualified opinion with material going-concern uncertainty',
  '本期未经审计':'Current period unaudited',
  '本期已审阅，未经审计':'Current period reviewed, not audited',
  '同报告期审计信息冲突':'Conflicting audit information for the same period',
  '审计表述尚未分类，需核查':'Audit wording is unclassified and needs review',
  '尚未取得该期审计信息':'No audit information for this period',
  '审计状态待核验':'Audit status unverified',
  '未经审计表示保证范围，不等于负面审计意见或发现造假。':'Unaudited describes the assurance scope; it is not an adverse opinion or a fraud finding.',
  '审阅与审计提供的保证程度不同，不将审阅意见称为年度审计意见。':'Reviews and audits provide different assurance levels. A review is not an annual audit opinion.',
  '供应商原始审计表述':'Original supplier audit wording',
  '供应商结构化记录，需核对原始财务报表审计报告。':'Structured supplier record; verify against the original financial statement audit report.',
  '同日冲突表述':'Conflicting wording with the same disclosure date',
  '治理披露与尚未核查事项':'Governance disclosures and unresolved checks',
  '这里只整理定期报告披露；监管机关和交易所的独立公告尚未核查。':'Only periodic-report disclosures are organized here. Independent regulator and exchange announcements have not been reviewed.',
  '没有检索结果或没有定位到原文，都不能认定无风险。':'No search results or no located excerpt does not establish an absence of risk.',
  '优先核查与资料缺口':'Priority checks and evidence gaps',
  '尚未形成优先核查清单，不代表低风险或已排除风险。':'No priority-check list has been established. This does not mean low or cleared risk.',
  '不是有息债务总额；未识别的其他有息负债仍可能存在。综合到期项未经拆分不加入。':'This is not total interest-bearing debt; unidentified obligations may exist. The comprehensive current-portion item is not added without classification.',
  '根据上游声明的完整口径计算，不代表本函数完成原文审计。':'Calculated from the complete scope declared upstream, not an audit of the original filing.',
  '账面金额，不是含未来利息的合同现金支付额。':'Book value, not contractual cash payments including future interest.',
  '简化会计口径，不含未进入本期损益的资本化借款利息；不是现金偿债覆盖。':'Simplified accounting measure excluding borrowing costs capitalized outside current profit. This is not cash debt-service coverage.',
  '仍可能包含不能及时动用的定期存款；不是可用现金。':'May still include term deposits unavailable when needed. This is not usable cash.',
  '只在债务与现金两个完整性契约都满足时计算。':'Calculated only when both debt and cash completeness conditions are met.',
  '分母明确为0时比例不适用；未预测经营现金流，不是未来违约概率。':'A zero denominator makes this ratio inapplicable. Operating cash flow is not forecast; this is not a default probability.',
  '所列互斥组件相加':'Sum the listed mutually exclusive components',
  '所有完整性契约组件相加':'Sum all components required by the declared complete scope',
  '货币资金-受限货币资金':'Cash - restricted cash',
  '12个月可动用现金-完整有息债务总额':'Cash usable within 12 months - complete interest-bearing debt',
  '12个月可动用现金/12个月到期有息债务账面额':'Cash usable within 12 months / book debt due within 12 months',
  '(合并利润总额+费用化融资利息支出)/费用化融资利息支出':'(Consolidated profit before tax + expensed financing interest) / expensed financing interest',
  '短借+短债+到期非流动有息部分+其他流动有息债务':'Short borrowings + short bonds + current noncurrent interest debt + other current interest debt',
  '短期借款':'Short-term borrowings',
  '长期借款（非流动部分）':'Long-term borrowings, noncurrent portion',
  '应付债券（非流动部分）':'Bonds payable, noncurrent portion',
  '短期应付债券':'Short-term bonds payable',
  '一年内到期的非流动负债（综合项）':'Current portion of noncurrent liabilities, comprehensive item',
  '一年内到期非流动负债中的有息部分':'Interest-bearing portion of current noncurrent liabilities',
  '租赁负债（非流动部分）':'Lease liabilities, noncurrent portion',
  '其他非流动有息债务':'Other noncurrent interest-bearing debt',
  '其他流动有息债务':'Other current interest-bearing debt',
  '受限货币资金':'Restricted cash',
  '经期限核查的未来12个月可动用现金':'Maturity-reviewed cash usable within 12 months',
  '费用化融资利息支出':'Expensed financing interest',
  '财务费用中的利息收入':'Interest income within finance costs',
  '财务费用净额（含汇兑等）':'Net finance costs, including FX effects',
  '合并利润总额':'Consolidated profit before tax',
  '定期报告中的监管披露':'Regulatory disclosures in periodic reports',
  '审计与审阅':'Audit and review',
  '债务期限':'Debt maturity',
  '利息口径':'Interest definition',
  '关联交易与资金占用':'Related-party transactions and fund occupation',
  '担保':'Guarantees',
  '尚未检索监管机关及交易所独立公告':'Independent regulator and exchange announcements have not been searched',
  '需分别核对担保余额、对象、违规性与业务担保范围':'Review guarantee balances, beneficiaries, possible violations and business-guarantee scope separately',
  '货币资金':'Cash and bank balances',
  '公告日期':'Announcement date',
  '受限现金':'Restricted cash',
  ' · 来源链接待补齐':' · Source link unavailable',
  '标准审计意见不等于无风险；审阅、未经审计及财务/内部控制意见分别理解。原文关键词不能自动判为非标。':'An unqualified audit opinion does not establish an absence of risk. Reviews, unaudited statements and financial/internal-control opinions are distinct. Keywords alone do not establish a modified opinion.',
  '已定位原文，需核查主体、期间、适用范围和上下文；未把关键词命中当作风险事实。':'An excerpt has been located. Its entity, period, scope and context need review; a keyword match is not a risk finding.',
  '财报没有披露不代表没有风险；合计完整性依赖上游明确提供并核对的口径。':'An absence of disclosure does not establish an absence of risk. Completeness of totals depends on an explicitly supplied and verified upstream scope.',
  '原文匹配只证明片段来自输入资料，没有自动核验金额语义、主体、币种或表格列。':'Text matching only establishes that an excerpt occurs in the supplied material. Amount meanings, entity, currency and table columns have not been automatically verified.',
  '监管机关与交易所独立事实尚未检索，不能据此清除治理风险。':'Independent regulator and exchange records have not been searched; governance risk cannot be cleared on this basis.',
  '本模块是研究核查，不构成公司完整结论或买入建议。':'This module supports research checks. It is not a complete company assessment or a buy recommendation.',
  '本期利润对费用化融资利息的简化覆盖低于1；需核查现金、资本化利息和到期安排。':'Simplified profit coverage of expensed financing interest is below 1 for this period. Review cash, capitalized interest and maturities.',
  '有息债务的全部类别、期限与重复项尚未完整核查':'Interest-bearing debt categories, maturities and overlapping items have not been fully reviewed',
  '受限资金、定期存款与可动用期限尚未完整核查':'Restricted funds, term deposits and availability dates have not been fully reviewed',
  '该行业、盈利阶段或行业资料状态需要专项判断；一般企业债务合成与覆盖指标暂不计算。':'The sector, earnings stage or available sector data requires specialist analysis. General-company debt and coverage metrics are withheld.'
});
window.ETF_EN_PATTERNS.push(
  [/已提供数值 ([\d—]+) \/ ([\d—]+) 项/g,'Numeric fields provided: $1 / $2'],
  [/ · PDF 第 ([\d]+) 页/g,' · PDF page $1'],
  [/(\d{4}-\d{2}-\d{2})审计信息存在需优先核查的意见或冲突；核对原始审计报告。/g,'Audit information for $1 includes an opinion or conflict requiring priority review. Check the original audit report.']
);

// BEGIN_BUSINESS_CAPITAL_UI
'use strict';
// Merge after locale-en.js and before i18n.js. Raw inputs and quotations are skipped.
Object.assign(window.ETF_EN, {
  '生意与资本使用观察':'Business and capital-use observations',
  '展示固定3年、5年的经营与资金使用事实，以及待核查证据；不形成护城河、资本配置评分或买卖建议。':'Review fixed three- and five-year operating and capital-use observations and evidence requiring review. No moat score, capital-allocation rating or trading recommendation is provided.',
  '当前报告尚无生意与资本使用资料。':'This report has no business or capital-use data yet.',
  '生意与资本数据版本待更新，暂不展示旧结构。':'The business and capital data version needs updating. The old structure is withheld.',
  '资料主体与当前公司不一致，已停止展示。':'The evidence belongs to a different company and has been withheld.',
  '合成验收样本，不是真实公司事实。':'Synthetic test fixture, not facts about a real company.',
  '这是旧报告中的经营与资本资料，尚未按最新数据重新核验。':'This business and capital data comes from a cached report and has not been checked against the latest data.',
  '研究截止':'Research cutoff','固定年度末年':'Last year in the fixed annual window',
  '来源和元数据匹配不等于官方逐值验证；本模块尚未完成官方逐值核验。':'Source and metadata matching is not official numeric verification. This module has not completed official numeric verification.',
  '竞争优势：证据不足，尚未形成判断。':'Competitive advantage: insufficient evidence for a conclusion.',
  '资本配置质量：证据不足，尚未形成判断。':'Capital-allocation quality: insufficient evidence for a conclusion.',
  '本公司需要行业专项分析，普通企业效率指标不适用。':'This company needs sector-specific analysis. General-company efficiency metrics do not apply.',
  '已从通过文件哈希检查的本地缓存整理，尚未完成原文数字核验。':'Compiled from local cache files that passed hash checks. Filing numbers have not been verified.',
  '本地缓存恢复不完整或不可用，缺失资料不自动补零。':'Local cache recovery is partial or unavailable. Missing data is not replaced by zero.',
  '最近3个固定年度':'Latest three fixed annual periods','最近5个固定年度':'Latest five fixed annual periods',
  '缺年保留缺口，不用更早年度补位，也不把季报年化。':'Missing years remain gaps. Earlier years are not substituted and quarterly data is not annualized.',
  '固定窗口期次不完整或不一致，暂不显示窗口数值。':'The fixed-window periods are incomplete or inconsistent. Window values are withheld.',
  '毛利率极差只描述区间波动，支出规模不等于投资回报。':'The gross-margin range describes variation only. Spending volume is not an investment return.',
  '逐年经营观察与原始财务输入':'Annual business observations and original financial inputs',
  '已取得的原始财务字段':'Available original financial fields','原始财务字段':'Original financial field',
  '被后续版本替代的来源（不计入本次值）':'Sources superseded by later disclosures (excluded from this value)',
  '股本、分红、融资与并购事件':'Share capital, dividends, financing and acquisition events',
  '区分方案、完成日期和现金口径；不从股本金额变化推断融资，也不把混合派息项当普通股分红。':'Separate proposals, completion dates and cash definitions. Share-capital amounts do not establish financing, and mixed distribution items are not ordinary-share dividends.',
  '尚无可用结构化事件；财报字段变化不能自动补成资本事件。':'No usable structured events are available. Changes in financial fields cannot be converted into capital events.',
  '尚待补齐的证据与范围':'Evidence and scope still requiring completion',
  '缺少资料不能给高分；企业自述、独立材料和反证仍需分别核查。':'Missing evidence cannot justify a high score. Issuer claims, independent material and counterevidence each require review.',
  '固定年度数字的公告筛选不代表已完成严格历史时点验证。':'Filtering annual figures by disclosure date does not establish certified point-in-time validity.',
  '未纳入本次计算的记录':'Records excluded from this calculation','未纳入原因':'Exclusion reason','缺口标识':'Gap identifier',
  '另有资料缺口，需要补齐来源后核查。':'Additional data gaps require sources and review.',
  '已提供数值':'Value provided','明确为零':'Explicit reported zero','数值为空':'Null value','未提供':'Not provided',
  '数值无效':'Invalid value','来源口径待核查':'Source basis requires review','数据冲突':'Data conflict',
  '仅算术可计算':'Arithmetic calculation only','资料不足':'Insufficient evidence','需要专项行业判断':'Sector-specific assessment required',
  '分母非正，不计算':'Nonpositive denominator; no calculation','负支出待核查':'Negative expenditure requires review',
  '计算结果无效':'Invalid calculation result','待核查材料':'Material requiring review','未纳入有效材料':'Excluded from usable material',
  '已披露事件，语义待核查':'Reported event; meaning unverified','事件口径待核查':'Event basis requires review',
  '重复事件待核查':'Duplicate event requires review','状态待核查':'Status requires review','单位待核查':'Unit requires review',
  '报告毛利率':'Reported gross margin','费用化研发/营业收入':'Expensed R&D / revenue','购建现金/经营现金流':'Cash capital expenditure / operating cash flow',
  '经营现金减购建现金':'Operating cash flow less cash capital expenditure','年度毛利率极差':'Annual gross-margin range',
  '窗口费用化研发合计':'Window sum of expensed R&D','窗口购建现金合计':'Window sum of cash capital expenditure',
  '窗口归母净利润合计':'Window sum of profit attributable to owners','财务观察':'Financial observation',
  '查看公式与原始输入':'View formula and original inputs','仅复算财务关系，不代表来源数字已核验。':'Arithmetic financial relationships only; source numbers have not been verified.',
  '覆盖期次':'Covered periods','原字段':'Original field','原始输入':'Original input','原单位':'Original unit',
  '金额换算倍率':'Amount conversion factor','单位来源规则':'Unit source rule','币种':'Currency','报表范围':'Reporting scope',
  '报告期':'Reporting period','公告日期':'Publication date','原文页码':'Source page','来源报告期':'Source reporting period',
  '查看来源':'Open source','来源链接尚待补齐。':'A source link is still required.','查看待核查原因':'View issues requiring review',
  '竞争证据：自述、独立材料与反证':'Competitive evidence: issuer claims, independent material and counterevidence',
  '毛利率、研发费用和EPS不能自动证明护城河；独立来源标签本身也未获外部核验。':'Gross margin, R&D expense and EPS do not prove a moat. Independent-source labels have not themselves been externally verified.',
  '反证按材料立场分类，可能同时出现在来源组；重复显示不增加证据强度。':'Counterevidence describes a material perspective and may also appear in its source group. Repeated display does not strengthen the evidence.',
  '企业自述':'Issuer claims','独立来源待核查材料':'Independent-source material requiring review','反证与质疑材料':'Counterevidence and challenges',
  '尚无符合本组条件的材料，不能据此给高分或排除风险。':'No material meets this group’s requirements yet. This cannot justify a high score or rule out risk.',
  '待归类与未纳入的材料':'Unclassified and excluded material','待核查证据主题':'Evidence topic requiring review','原始主题标签':'Original topic label',
  '竞争地位材料':'Competitive-position material','客户留存材料':'Customer-retention material','竞争地位关键词候选':'Competitive-position keyword candidate',
  '资本使用关键词候选':'Capital-use keyword candidate','主题待归类':'Topic unclassified',
  '材料报告期':'Material reporting period','材料公告日期':'Material publication date',
  '原文尚未自动匹配来源，主体、上下文和数值语义仍待核查。':'The excerpt has not been automatically matched to its source. Its entity, context and numeric meaning still require review.',
  '展开原文（保留原语言）':'Expand excerpt (original language preserved)','尚无可审阅原文。':'No reviewable excerpt is available.',
  '送股':'Bonus share issue','资本公积转增':'Capitalization share issue','拆股':'Share split','并股':'Share consolidation',
  '股份注销':'Share cancellation','现金发行融资':'Cash equity financing','股份回购':'Share repurchase','普通股现金分红':'Ordinary-share cash dividend','并购':'Acquisition',
  '资本事件待归类':'Capital event unclassified','方案提出，尚未实现':'Proposed; not realized','已批准，尚未实现':'Approved; not realized',
  '已披露完成':'Reported as completed','完成状态待核查':'Completion status requires review','事件阶段待核查':'Event stage requires review',
  '非现金股本事件，不认定为融资':'Non-cash share-capital event; not financing','披露融资现金，仍需核对口径':'Reported financing cash; basis still requires review',
  '披露普通股现金支付':'Reported ordinary-share cash payment','并购现金与对价按披露口径分别展示':'Acquisition cash and consideration retain their separate disclosed definitions',
  '披露回购，不代表已注销':'Reported repurchase; cancellation is not established','方案或授权，不记为实际现金支付':'Proposal or authorization; not an actual cash payment',
  '资料存在缺口，不确认事件金额':'Evidence gaps prevent confirmation of the event amount','事件类型待核查':'Event type requires review',
  '股数增加不等于现金融资，未评估稀释或每股价值影响。':'An increase in shares is not cash financing. Dilution and per-share value effects have not been assessed.',
  '披露发生日期':'Reported event date','方案所列日期（未确认发生）':'Proposed date (occurrence unconfirmed)',
  '经济归属年度':'Economic annual period','方案对应年度':'Proposal fiscal year',
  '这是报告期后的事件，不回填为报告期内已实现。':'This event is subsequent to the reporting period and is not backfilled as realized within it.',
  '未计入当前固定年度窗口。':'Not included in the current fixed annual window.',
  '该事件为非现金股本变化，不适用现金支付金额。':'This is a non-cash share-capital event; a cash payment amount does not apply.',
  '披露现金口径':'Disclosed cash definition','没有可确认的现金口径':'No cash definition has been established',
  '普通股股东实际现金分红':'Actual cash dividend paid to ordinary shareholders','发行募集现金净额':'Net equity issuance cash proceeds',
  '发行募集现金总额':'Gross equity issuance cash proceeds','实际回购支付现金':'Cash paid for share repurchases',
  '取得子公司等支付现金净额':'Net cash paid to acquire subsidiaries and businesses','收购总对价':'Total acquisition consideration',
  '净现金支付与总对价不能合并；金额不代表收购成功。':'Net cash paid and total consideration cannot be combined. Neither amount establishes acquisition success.',
  '查看股数、原文和口径':'View share counts, excerpt and basis','披露事件前股数':'Reported shares before the event',
  '披露事件后股数':'Reported shares after the event','披露股数差额':'Reported change in share count',
  '人民币元':'CNY','人民币元/股':'CNY/share','港元':'HKD','美元':'USD','欧元':'EUR','英镑':'GBP','日元':'JPY','个百分点':'percentage points','股':'shares',
  '缺少已核验的独立竞争证据，不能判断护城河。':'Verified independent competitive evidence is missing; no moat assessment can be made.',
  '研发费用不是研发总投入，缺少资本化流量和成果归因。':'R&D expense is not total R&D investment. Capitalized flows and outcome attribution are missing.',
  '购建现金未区分维持与扩张，缺少投产和回报归因。':'Cash capital expenditure does not distinguish maintenance from expansion. Commissioning and return attribution are missing.',
  '股利、利润和利息混合现金项不能用于普通股分红率。':'Mixed cash payments of dividends, profits and interest cannot establish an ordinary-share payout ratio.',
  '库存股和合并吸收投资不能替代实际回购、注销及发行。':'Treasury-stock balances and consolidated investment receipts cannot replace actual repurchase, cancellation and issuance records.',
  '拆并股、送转及追溯口径未核实，不计算跨年EPS增速。':'Splits, consolidations, bonus issues and retrospective bases are unverified. Cross-year EPS growth is not calculated.',
  '收购现金不能证明整合成功，仍缺后续利润与承诺兑现证据。':'Acquisition cash does not prove integration success. Subsequent profit and commitment fulfilment evidence is missing.',
  '客户和供应商集中度、留存及表格语境仍需正文核查。':'Customer and supplier concentration, retention and table context still require filing review.',
  '营业收入':'Revenue','营业成本':'Operating cost','当期费用化研发费用':'Current-period expensed R&D','归母净利润':'Profit attributable to owners',
  '报告基本每股收益':'Reported basic EPS','报告稀释每股收益':'Reported diluted EPS',
  '股本账面金额（不是股数）':'Book amount of share capital (not a share count)',
  '库存股账面金额（不是本期回购金额）':'Treasury-stock book balance (not cash repurchases in this period)',
  '开发支出期末余额（不是本期资本化投入）':'Closing development expenditure balance (not current-period capitalized investment)',
  '经营现金流量净额':'Net operating cash flow','购建长期资产支付现金':'Cash paid to acquire or construct long-term assets',
  '分配股利、利润或偿付利息支付现金（合计）':'Cash paid for dividends, profits or interest (combined)',
  '吸收投资收到现金（含合并范围）':'Cash investment receipts (including consolidated entities)',
  '取得子公司及其他营业单位支付现金净额':'Net cash paid to acquire subsidiaries and other businesses',
  '投资支付现金（不自动归类为收购）':'Cash paid for investments (not automatically classified as acquisitions)',
  '购买子公司权益支付现金（筹资项目）':'Cash paid to purchase subsidiary equity (financing item)'
});
// END_BUSINESS_CAPITAL_UI

// BEGIN_INDUSTRY_UI
'use strict';
// Load after locale-en.js and before i18n.js. Original labels and IDs stay verbatim.
Object.assign(window.ETF_EN, {
  '行业与方法适用性':'Industry and method applicability',
  '先确认行业和盈利口径，再说明哪些方法可用；本模块不形成行业评级或买卖建议。':'Industry and earnings determine which methods apply. This module provides no industry rating or trading recommendation.',
  '普通非金融':'General nonfinancial company','银行':'Bank','保险':'Insurer','证券公司':'Securities firm','房地产开发':'Property developer','周期行业候选':'Potential cyclical business','金融业务类型待核实':'Financial business type unresolved','行业待核实':'Industry unresolved',
  '合并及归母利润均为正':'Consolidated and parent-attributable profit are both positive','至少一项利润非正（含零）':'At least one profit measure is nonpositive, including zero','盈利状态待核实':'Earnings status unresolved',
  '普通六指标初筛':'General six-factor screen','多年经营观察':'Multi-year operating observations','债务与流动性':'Debt and liquidity','利润与现金关系':'Profit and cash relationship','毛利率观察':'Gross margin observations','资本使用':'Capital use','治理核查':'Governance review','估值方法':'Valuation methods','市盈率':'Price/earnings ratio',
  '有条件适用':'Conditionally applicable','普通方法不适用':'General method not applicable','保留原始趋势':'Raw trends only','需要专项行业方法':'Sector-specific method required','仅作背景观察':'Context only','须结合具体证据':'Specific evidence required','缺少专项字段':'Specialist field missing','来源口径缺失':'Source basis missing','未提供数值':'Value not provided','披露值为空':'Disclosed value is null','数值无效':'Invalid value','口径不可用':'Unusable reporting basis','业务类型待确认':'Business subtype required','分部口径待确认':'Segment basis required','已提供数值':'Reported value','明确为零':'Explicit zero',
  '不良贷款率':'Nonperforming loan ratio','拨备覆盖率':'Provision coverage ratio','资本充足率':'Capital adequacy ratio','核心一级资本充足率':'Common equity tier 1 ratio','净息差':'Net interest margin','核心偿付能力充足率':'Core solvency ratio','综合偿付能力充足率':'Comprehensive solvency ratio','新业务价值增速':'New business value growth','综合成本率':'Combined ratio','投资收益率':'Investment yield','净资本':'Net capital','风险覆盖率':'Risk coverage ratio','流动性覆盖率':'Liquidity coverage ratio','净稳定资金率':'Net stable funding ratio',
  '受限货币资金':'Restricted cash','合同负债（不能替代债务或收入）':'Contract liabilities (not a substitute for debt or revenue)','存货减值（余额或计提须区分）':'Inventory impairment (balance and period charge must be distinguished)','销售回款（不能替代收入）':'Sales cash collections (not a substitute for revenue)','项目担保披露额':'Disclosed project guarantees','产能利用率':'Capacity utilization','产品单位售价':'Unit selling price','产品单位现金成本':'Unit cash cost','已区分的维持性资本开支':'Separately identified maintenance capital expenditure',
  '查看供应来源':'View supplier source','来源链接待补齐。':'Source link is missing.','来源编号':'Source ID','原文件 SHA256':'Original file SHA256','供应商原字段':'Original supplier field','供应商原标签':'Original supplier label','供应商观测时间':'Supplier observation time','字段公告日期':'Field publication date','字段报告期':'Field reporting period','查看原始缺口代码':'View original gap codes',
  '行业适用性待核查':'Industry applicability unresolved','普通初筛方法可用':'General screening method available','暂不进入普通排名':'Excluded from general ranking','尚无行业适用性资料。':'No industry applicability data yet.','行业资料版本待更新。':'Industry data version needs updating.','行业资料主体不匹配。':'Industry data belongs to another issuer.',
  '这是旧报告的只读行业视图，保留原研究截止。':'This read-only view preserves the cached report’s original research cutoff.','研究截止':'Research cutoff','财务报告期':'Financial reporting period',
  '行业采用供应商当前观测；采集时间不是行业分类公告日期。':'Industry uses the supplier’s current observation. Retrieval time is not the classification publication date.',
  '分类及财务日期按研究截止检查，仍不能证明严格历史时点可得。':'Classification and financial dates are checked against the cutoff, but strict historical availability is not established.',
  '严格历史 PIT：未验证，不能用于宣称无前视偏差的历史回测。':'Strict historical PIT is unverified. These data cannot support a claim of a backtest free from look-ahead bias.',
  '来源匹配与文件哈希检查不等于官方逐值核验；本模块官方逐值核验为零。':'Source matching and file hash checks are not official numeric verification. This module has zero officially verified numbers.',
  '行业来源与时间':'Industry sources and dates','尚无可用于行业判断的来源，未知行业不回退到普通企业。':'No usable classification source is available. An unknown industry does not default to a general company.',
  '盈利字段、期间与来源':'Earnings fields, periods and sources','合并净利润':'Consolidated net profit','归母净利润':'Parent-attributable net profit','可用利润原值':'Usable original profit value','人民币元；报告期累计，不做年化。':'CNY units; cumulative for the reporting period, without annualization.','金额单位需按来源核实；不做年化。':'Check currency units against the source; no annualization.','方法待归类':'Method unclassified','状态待核查':'Status unresolved',
  '专项字段与缺口':'Specialist fields and gaps','专项字段不代表监管达标或风险已排除；实体、期间与口径必须匹配。':'Specialist fields do not establish regulatory compliance or exclude risk. Entity, period and basis must match.','专项观察':'Specialist observation','披露原值':'Reported original value','原单位':'Original unit','币种':'Currency','主体与报表范围':'Entity and reporting scope','比例保留小数原值，未转换为百分数。':'Ratios retain their original decimal values; they are not converted to percentages.',
  '来源恢复与适用边界':'Source recovery and limitations','本地来源已恢复，数值语义仍待核验。':'Local sources were recovered; numeric semantics remain unverified.','本地来源存在缺口，缺失值不补零。':'Local sources have gaps. Missing values are not replaced with zero.','来源缺口':'Source gap',
  '当前普通初筛覆盖':'Current general-screen coverage','行业覆盖统计尚不可用，不能把缺项当零。':'Industry coverage statistics are unavailable. Missing counts are not zero.','当前公司数':'Companies in snapshot','普通方法适用数':'General method applicable','原六指标可评分数':'Original six-factor scores available','原规则候选数':'Candidates under original rules','行业类型待核实数':'Unresolved industry types','当前供应商分类数':'Current supplier classifications','已验证历史 PIT 数':'Verified historical PIT count',
  '未进入普通排名可能因为专项行业、盈利非正或资料不足；不能全部解释为财报缺失。':'Exclusion from general ranking can reflect a specialist industry, nonpositive earnings or insufficient data. It does not always mean missing financial statements.',
  '候选沿用原六指标门槛，不是完整好公司结论或买入建议。':'Candidates retain the original six-factor thresholds. They are not complete company assessments or buy recommendations.',
  '逐主体、期次与状态核查；未检索监管公告不能判定无风险。':'Check each entity, period and status. Unsearched regulatory announcements cannot establish an absence of risk.',
  '普通六指标阈值仅适用于已明确普通非金融且正盈利的公司；本模块不评分。':'General six-factor thresholds apply only to confirmed general nonfinancial companies with positive earnings. This module assigns no score.',
  '保留年度事实；专项业务、亏损或周期未校正时不套持续性评分。':'Retain annual facts. Do not apply continuity ratings to specialist businesses, losses or unadjusted cycles.',
  '金融负债和客户资金需专用口径；非金融复用阶段2完整债务/受限现金/期限契约。':'Financial liabilities and customer funds need specialist definitions. Nonfinancial companies use the debt, restricted cash and maturity contract.',
  '金融经营现金流包含核心资产负债扩张；地产受预售和交付影响；周期须跨周期观察。':'Financial operating cash flows include core balance-sheet expansion. Property is affected by presales and delivery; cyclicals require observations across a cycle.',
  '保险/银行不能套工业毛利率；地产看结算与减值，周期看产品价格和成本。':'Industrial gross margins do not apply to insurers or banks. Property requires settlement and impairment analysis; cyclicals require prices and costs.',
  '金融应检查监管资本和分配限制；普通资本开支/经营现金比不通用。':'Financial firms require regulatory capital and distribution restrictions. General capital expenditure-to-cash-flow ratios are not universal.',
  '留待阶段5；周期峰值PE、账面折价或监管资本达标均不构成买入建议。':'Valuation needs a separate method. Peak-cycle P/E, a discount to book or regulatory capital compliance is not a buy recommendation.',
  '归母/合并利润已知非正，旧正PE不能替代可用盈利。':'Known parent-attributable or consolidated profit is nonpositive. An old positive P/E does not establish usable earnings.',
  '行业路由通过不代表该行业已开放上线；指标齐全也不自动给综合分。':'Method routing does not mean full sector analysis is available. Complete fields do not automatically produce an overall score.',
  '监管实体、并表范围、规则版本必须保留，禁止合并集团数据顶替子公司偿付/净资本口径。':'Preserve regulated entity, consolidation scope and rule version. Group totals cannot replace subsidiary solvency or net-capital measures.',
  '周期候选需行业与产品证据确认完整周期，固定5年不等于覆盖完整周期。':'Cyclical candidates require industry and product evidence for a complete cycle. A fixed five-year window is not necessarily a full cycle.',
  '来源匹配未完成数值、表头、单位和期间的语义复核。':'Source matching does not verify the meaning of numbers, headers, units or periods.',
  '财报ORG_TYPE为供应商报表类型；通用模板不能证明普通行业，日期与哈希匹配也不代表官方逐值或严格PIT核验。':'ORG_TYPE is a supplier statement type. A general template does not establish a general industry, and dates or hashes do not establish official numeric or strict PIT verification.'
});

Object.assign(window.ETF_EN, {
  "普通排名未开放": "General ranking unavailable",
  "港股官方资料参考": "Hong Kong official source references",
  "港股参考资料版本待核查。": "Hong Kong reference data version requires review.",
  "官方报告和元数据入口；本参考入口尚无可评分的港股财务资料，未加入 A 股排名。": "Official filings and metadata references. No Hong Kong financial data is admitted to scoring, and these cards are excluded from A-share rankings.",
  "参考公司数": "Reference companies",
  "纳入评分的财务事实": "Financial facts admitted to scoring",
  "资料核对日": "Reference review date",
  "港股资料参考": "Hong Kong source reference",
  "发行人原名": "Issuer name in source",
  "港交所证券代码": "HKEX security code",
  "交易柜台币种": "Trading counter currency",
  "报告标题": "Report title",
  "会计年度结束日": "Fiscal year-end",
  "报告覆盖截止": "Reporting period end",
  "财报币种": "Reporting currency",
  "会计准则": "Accounting standards",
  "打开官方报告": "Open official report",
  "官方报告链接待核对。": "Official report link requires review.",
  "覆盖边界与未核对事项": "Coverage and unverified items",
  "查看元数据来源": "View metadata source",
  "未核对": "Not checked",
  "阿里巴巴集团": "Alibaba Group",
  "只有年度报告元数据和原文入口，财务数值尚未获准进入评分。": "This card provides annual-report metadata and a source link. No financial values are admitted to scoring.",
  "港币与人民币柜台不等于财报币种，未连接价格或做汇率换算。": "HKD and RMB trading counters are distinct from the reporting currency. No prices or FX conversion are connected.",
  "公告精确时间未核对；报告全文未在本样本冻结，不能用于严格历史PIT。": "The publication timestamp is unverified and the full filing is not frozen in this sample. Strict historical PIT is not established.",
  "新世界发展": "New World Development",
  "原PDF体积超过浏览工具读取上限，本次仅核对官方PDF已索引节选与发行人FAQ。": "The original PDF exceeded the browser tool’s size limit. This review checked the indexed official-PDF excerpt and issuer FAQ only.",
  "受限现金、净债务定义及财务数值未完成逐项核验，不显示金额或评分。": "Restricted cash, the issuer’s net-debt definition and financial values remain unverified. No amounts or scores are shown.",
  "未核对交易币种、准则及公告精确时间，不能把港股上市地推断成这些字段。": "Trading currency, accounting standards and the publication timestamp are unverified. They are not inferred from the Hong Kong listing."
});
// END_INDUSTRY_UI

// BEGIN_PHASE4_BUSINESS_DISPLAY_FOLLOWUP
Object.assign(window.ETF_EN, {
  '亿元':'CNY 100 million',
  '万元':'CNY 10 thousand',
  '计算结果原值（未缩写）':'Unabridged calculated value',
  '部分原文尚未与公司、披露时间或完整文本对应，需要核对来源。':'Some excerpts are not yet bound to the company, disclosure date or complete text; their sources require review.',
  '部分旧文档缺少保存时的文件校验记录，需要重新核对来源。':'Some older documents lack a saved file integrity record; their sources require rechecking.',
  '查看资料缺口明细':'View evidence gap details',
  '涉及记录数':'Affected records'
});
// END_PHASE4_BUSINESS_DISPLAY_FOLLOWUP

// BEGIN_PRICE_QUALITY_UI
'use strict';
// Load after locale-en.js and before i18n.js. Source records retain their language.
Object.assign(window.ETF_EN,{
  '查看完整原值':'View the exact original value','亿元人民币':'CNY 100 million','亿港元':'HKD 100 million','亿美元':'USD 100 million','万元人民币':'CNY 10 thousand','万港元':'HKD 10 thousand','万美元':'USD 10 thousand',
  '何时更新':'When to update','有新公告或补齐核实资料时':'When a new disclosure or verified evidence is available','行情更新或现有报价过期时':'When the quote updates or expires','盈利、权益或同行资料更新时':'When earnings, equity or peer evidence changes','更新条件待核查':'Update condition needs review',
  '见价格参考面板':'See the price reference panel','下方分别列出供应商参考和完整口径要求；资料不足时不作价格结论。':'Supplier references and full-basis requirements appear below. No price conclusion is drawn when evidence is incomplete.',
  '相对同行中位数的差幅':'Difference from the peer median','原始比值':'Original ratio',
  '当前行业资料与原报告日期':'Current industry evidence and the original report date','当前行业资料':'Current industry evidence','当前适用性评估日':'Current applicability assessment date','来源观察时间':'Source observation time','原报告截止':'Original report cutoff','原报告行业状态':'Industry status in the original report','查看来源缺口':'View source gaps',
  '本段保留原报告截止；当前行业资料见下方「公司质量与价格参考」。':'This section preserves the original report cutoff. See Company quality and price references below for current industry evidence.',
  '当前行业来源不足，今日价格适用性待核查。':'Current industry sources are insufficient; today’s price applicability needs review.',
  '当前资料仅用于本页价格适用性和行业维度，不追溯补齐原报告，也不改变旧评分、AI或财务日期。':'Current evidence is used only for this page’s price applicability and industry dimension. It does not retrospectively fill the original report or change its score, AI evidence or financial dates.',
  '供应商参考可用，完整分母待复算':'Supplier reference available; complete denominator reconstruction pending',
  '多年财务持续性':'Multi-year financial persistence','债务与流动性':'Debt and liquidity','治理与审计':'Governance and assurance','竞争地位证据':'Competitive-position evidence','资本使用证据':'Capital-use evidence','行业适用性':'Industry applicability','核对报价':'Review the quote','核对同行口径':'Review peer comparability',
  '供应商已提供':'Supplier value provided','明确为零':'Explicit zero','数值为空':'Null value','未提供':'Not provided','数值无效':'Invalid value','数据冲突':'Conflicting data','仅算术可计算':'Arithmetic calculation only','资料不足':'Insufficient evidence','尚未评估':'Not assessed','模块资料已接入':'Module data present','模块缺失或不可用':'Module missing or unusable','部分资料，研究未完成':'Partial evidence; research incomplete','待补证据':'Evidence pending','自然日窗口内已观察':'Observed within the calendar-day window','条件参考可用':'Conditional reference available','优先风险待核查':'Priority risks require review','行业专项或主体待核查':'Sector-specific or entity review required','证据待补':'Evidence incomplete','存在高优先级待核查风险':'High-priority risks require review','风险待核查':'Risks require review','尚未排除风险':'Risks have not been cleared','报价在自然日参考窗口内':'Quote within the calendar-day reference window','当前不可用':'Currently unavailable',
  '未经审计':'Unaudited','已审阅，未经审计':'Reviewed, not audited','无保留审计意见':'Unqualified audit opinion','尚未核查':'Not reviewed','一般企业':'General company','银行专项':'Bank-specific analysis','保险专项':'Insurer-specific analysis','证券专项':'Securities-specific analysis','地产专项':'Property-specific analysis','周期行业专项':'Cyclical-sector analysis','行业未知':'Industry unknown','已提供正盈利口径':'Positive earnings basis provided','非正盈利':'Nonpositive earnings','高优先级':'High priority','中优先级':'Medium priority','低优先级':'Low priority',
  '已提供数值字段数':'Numeric fields provided','字段总数':'Total fields','债务范围完整':'Debt scope complete','现金范围完整':'Cash scope complete','最新报告鉴证状态':'Latest-report assurance','年度报告鉴证状态':'Annual-report assurance','监管独立公告':'Independent regulatory announcements','公司自述条数':'Issuer-claim count','独立待核查材料条数':'Independent material requiring review','反证条数':'Counterevidence count','元数据可用事件数（含方案）':'Events with usable metadata, including proposals','固定窗口数':'Fixed-window count','行业模型':'Industry model','盈利适用状态':'Earnings applicability',
  '人民币元':'CNY','港元':'HKD','美元':'USD','倍':'times','状态仍需核查':'Status requires review','单位待核查':'Unit requires review','查看来源':'Open source','来源链接尚待补齐。':'A source link is still required.','展开原字段与来源口径':'Expand original fields and source basis','原字段':'Original field','原始输入':'Original input','来源数值':'Source value','原单位':'Original unit','币种':'Currency','报表范围':'Reporting scope','报告期':'Reporting period','公告日期':'Publication date','实际报价日':'Actual quote date','期间起点':'Period start','期间终点':'Period end','金额倍率':'Amount factor','来源编号':'Source identifier','查看尚缺的口径':'View missing basis details',
  '供应商市盈率 PE TTM':'Supplier PE TTM','供应商市净率 PB':'Supplier PB','比率待归类':'Ratio unclassified','供应商同行参考可用，完整分母仍需核查':'Supplier peer reference available; full denominators still require review','完整口径层条件参考，不是价值结论':'Conditional full-basis reference, not a value conclusion','口径或适用条件未满足，暂不显示相对位置':'Basis or applicability conditions are unmet; relative position is withheld','纳入同行数':'Included peer count','同行中位数':'Peer median','本公司比率 / 中位数 − 1（原始比值）':'Company multiple / median minus 1 (raw ratio)','低于该样本中位数，不代表低估':'Below this sample median; undervaluation is not established','等于该样本中位数，不代表合理价值':'Equal to this sample median; fair value is not established','高于该样本中位数，不代表高估':'Above this sample median; overvaluation is not established','相对位置尚未确认':'Relative position is unconfirmed',
  '仅同供应商原始比率匹配；未认证每家会计政策或普通股分母。':'Same-supplier raw ratio matching only. Peer accounting policies and common-equity denominators are not certified.','独立完整口径要求仍单列，供应商参考不会补齐这些缺口。':'Independent full-basis requirements remain separate. Supplier references do not fill these gaps.','样本数量达标不证明业务或周期相同；中位数不是目标价或买入条件。':'Meeting the sample count does not prove comparable businesses or cycles. The median is not a target price or a buying condition.','查看参考限制':'View reference limitations','查看纳入与排除的同行':'View included and excluded peers','纳入样本':'Included samples','排除样本':'Excluded samples','公司代码':'Company code','查看排除原因':'View exclusion reasons',
  '复算诊断与权益候选':'Recalculation diagnostics and equity candidates','数值吻合仅表示供应商缓存的算术一致；不认证普通股权益完整，也不解除行业门禁。':'Matching numbers show arithmetic consistency with supplier cache only. They do not certify complete common equity or remove industry restrictions.','尚无可用复算资料；缺失值不补零。':'Recalculation inputs are unavailable. Missing values are not replaced with zero.','归母利润 TTM 复算诊断':'Attributable TTM profit recalculation','复算比率':'Recalculated multiple','在供应商匹配容差内，语义仍未核验':'Within the supplier matching tolerance; meaning remains unverified','数值未在供应商匹配容差内':'Outside the supplier matching tolerance','数值匹配尚不能判断':'Numeric matching cannot yet be assessed','展开 TTM 组成，不以半年利润乘二':'Expand TTM components; half-year profit is not doubled','算术符号':'Arithmetic operation','披露归母权益候选':'Reported attributable-equity candidate','归母权益减其他权益总项一次的候选':'Attributable equity less reported other-equity total once','权益口径候选待归类':'Equity-basis candidate unclassified','候选权益金额':'Candidate equity amount','这不是已认证的普通股权益；优先股和永续债可能已含在其他权益总项内，不重复扣除。':'This is not certified common equity. Preferred shares and perpetual bonds may already be included in other equity and are not deducted twice.','查看候选限制':'View candidate limitations','复算使用的市值':'Market capitalization used for recalculation','查看诊断限制':'View diagnostic limitations',
  '质量资料维度':'Quality evidence dimension','范围已声明完整，仍待核验':'Scope declared complete; verification pending','范围尚未完整':'Scope incomplete','固定三年窗口':'Fixed three-year window','固定五年窗口':'Fixed five-year window','期次待核查':'Periods require review','已覆盖年度数':'Annual periods covered','固定期次':'Fixed periods','年度槽位齐全，不代表研究完成':'Annual slots present; research is not complete','年度槽位存在缺口':'Annual slots have gaps','下一步所需证据':'Evidence needed next',
  '公司质量与价格参考':'Company quality and price references','质量证据、供应商价格参考和复算缺口分别展示；不生成综合分、目标价或买卖建议。':'Quality evidence, supplier price references and recalculation gaps remain separate. No combined score, target price or trading advice is generated.','当前报告尚无价格与综合证据资料。':'This report has no price and combined-evidence panel yet.','价格证据版本待更新，暂不展示旧结构。':'The price-evidence version needs updating. The old structure is withheld.','资料主体与当前公司不一致，已停止展示。':'The evidence belongs to a different company and is withheld.','合成验收样本，不是真实公司事实。':'Synthetic test fixture, not facts about a real company.','这是旧报告资料，尚未按最新信息重新核验。':'This is cached report data and has not been checked against the latest information.','研究截止':'Research cutoff','当前研究快照，不能用于证明历史可得信息。':'Current research snapshot; it does not establish historically available information.','按声明截止筛选，仍未认证严格历史时点可用。':'Filtered by the declared cutoff; strict point-in-time usability remains uncertified.','模块已接入不等于公司质量已确认；本面板尚未完成官方逐值核验。':'Module availability does not establish company quality. This panel has not completed official numeric verification.','行业或盈利门禁关闭；保留原始比率与复算资料，不开放普通企业相对判断。':'Industry or earnings restrictions apply. Raw ratios and diagnostics remain visible, while general-company relative assessments are withheld.',
  '报价参考与时间':'Quote reference and timing','抓取时间':'Observation time','相距自然日数':'Calendar-day age','抓取时间不替代实际报价日；自然日阈值不代表交易日历认证。':'Observation time does not replace the actual quote date. A calendar-day threshold is not trading-calendar verification.','供应商比率参考':'Supplier ratio references','完整口径的独立比较':'Independent full-basis comparisons','尚无该层参考资料。':'No reference data is available for this layer.','风险仍需核查':'Risks still require review','未列出风险不表示没有风险；较低倍数不能抵消高优先级风险。':'No listed risk does not mean no risk. Lower multiples cannot offset high-priority risks.','原风险来源':'Original risk source','这是待核查线索，不在此认定违规事实。':'This is a lead requiring review, not an established finding of misconduct.','后续观察清单':'Observation checklist','观察项是资料任务，不是交易指令，也不会自动发起付费研究。':'Observation items are evidence tasks, not trading instructions, and do not initiate paid research.','资料观察项':'Evidence observation item','更新触发条件':'Refresh trigger','所需资料（保留原文）':'Required evidence (original text preserved)','原六项初筛记录（未重算）':'Original six-factor screening record (not recalculated)','仅保留原记录参考；不是本面板的公司质量总分，也不绕过当前行业门禁。':'Original record reference only. It is not this panel’s company-quality score and does not bypass current industry restrictions.','查看假设':'View assumptions','查看面板范围':'View panel scope'
});

// END_PRICE_QUALITY_UI

// BEGIN_DEEP_RESEARCH_UI
Object.assign(window.ETF_EN,{
  "深度研究": "Deep research",
  "关闭深度研究": "Close deep research",
  "开始深度研究": "Start deep research",
  "更新研究": "Update research",
  "下载 Markdown": "Download Markdown",
  "停止深度研究": "Stop deep research",
  "刷新研究状态": "Refresh research status",
  "按经营、竞争、财务、治理、估值与风险整理可追溯的深度研究。": "Organize traceable research on the business, competition, finances, governance, valuation and risks.",
  "经营模式": "Business model",
  "竞争与反面证据": "Competition and counterevidence",
  "财务质量": "Financial quality",
  "治理与审计": "Governance and audit",
  "估值与价格条件": "Valuation and price conditions",
  "风险与待核查事项": "Risks and open questions",
  "本次研究已整理": "Research compiled",
  "部分资料报告": "Partial evidence report",
  "已有原文证据": "Source excerpts available",
  "证据不足，保留判断": "Insufficient evidence; judgment withheld",
  "原文资料不足": "Insufficient source text",
  "AI 调用额度不足": "Insufficient AI call allowance",
  "AI 尚未配置": "AI is not configured",
  "本部分研究失败": "This section could not be completed",
  "本部分尚未研究": "This section has not been researched",
  "深度研究任务主体不匹配，已停止展示。": "The deep research task belongs to a different company and is withheld.",
  "深度研究资料主体不匹配，已停止展示。": "The deep research data belong to a different company and are withheld.",
  "正在读取深度研究": "Loading deep research",
  "查看已有报告和任务状态，不会自动发起 AI 调用。": "Read saved reports and task status without automatically starting an AI call.",
  "围绕经营、竞争、财务、治理、估值与风险，整理已取得的原文证据、反证和待核查问题。": "Organize available source excerpts, counterevidence and open questions about the business, competition, finances, governance, valuation and risks.",
  "每次研究最多安排 3 轮 AI 调用，计入现有每日上限；已成功且资料未变化的轮次可复用，不重复计费。": "Each research task schedules up to 3 AI rounds within the existing daily limit. Successful rounds with unchanged evidence may be reused without another call.",
  "仅覆盖实际取得并提取的资料，不表示浏览全网或精读所有财报。研究结果不是买入建议。": "Coverage is limited to documents actually obtained and extracted. This does not imply a web-wide search or a full reading of every filing. The research is not a buy recommendation.",
  "额度统计日期": "Allowance date",
  "今日 AI 调用": "AI calls today",
  "剩余调用次数": "Calls remaining",
  "AI 尚未配置；开始后仅整理可用资料，不能生成已完成的 AI 研究。": "AI is not configured. Starting the task only organizes available evidence; it cannot produce completed AI research.",
  "今日额度已用尽或设为 0；可以整理资料，新的 AI 轮次不会执行。": "The daily allowance is exhausted or set to zero. Evidence can still be organized, but no new AI rounds will run.",
  "剩余额度不足 3 轮；本次可能只有部分主题完成，缺口会明确保留。": "Fewer than 3 calls remain. Some topics may remain incomplete, with the gaps explicitly retained.",
  "实际调用次数取决于可用资料、已有轮次和实时额度。": "The number of calls depends on available evidence, previously completed rounds and the live allowance.",
  "深度研究报告的版本或主体不匹配，暂不展示。": "The deep report version or company does not match, so its contents are withheld.",
  "正在提交深度研究…": "Submitting deep research…",
  "正在停止，等待当前步骤结束…": "Stopping after the current step…",
  "本次 AI 轮次": "AI rounds in this task",
  "关闭弹窗不会停止后台研究。要中止后续步骤，请使用停止按钮。": "Closing this dialog does not stop the background task. Use Stop to cancel subsequent steps.",
  "任务状态待核查": "Task status needs review",
  "本次任务未替换报告，下方保留的是此前已保存的研究。": "This task did not replace the report. The previously saved research remains below.",
  "尚无已保存的深度研究报告。点击开始后，资料范围和未完成主题会逐项显示。": "No deep research report has been saved yet. Starting a task will show its evidence coverage and unfinished topics.",
  "本次报告与资料范围": "Report and evidence coverage",
  "报告状态待核查": "Report status needs review",
  "报告生成时间": "Report generated",
  "已取得文档": "Documents obtained",
  "已提取正文文档": "Documents with extracted text",
  "实际提取页数": "Pages extracted",
  "完成的 AI 轮次": "AI rounds completed",
  "这是部分资料报告。未完成主题、额度限制与来源缺口不会被视为已完成研究。": "This is a partial evidence report. Unfinished topics, allowance limits and source gaps are not treated as completed research.",
  "该主题尚无已保存的研究，不能据此判断没有风险。": "No research has been saved for this topic. This does not establish the absence of risk.",
  "本部分尚未完成证据校验，不展示模型观点。": "Evidence validation is incomplete for this section, so model claims are withheld.",
  "待核查问题": "Open questions",
  "展开财务分析与原始依据": "Expand financial analysis and source evidence",
  "资料仍需核查。": "The evidence still needs review.",
  "读取或提交失败，请刷新状态后重试；已保存报告仍会保留。": "Loading or submission failed. Refresh the status before retrying; saved reports are retained.",
  "正在整理资料，请稍候。": "Organizing evidence. Please wait.",
  "本次研究未能完成。已保存报告仍可查看，刷新状态后可重试。": "This research task could not finish. Saved reports remain available; refresh the status before retrying."
});
// END_DEEP_RESEARCH_UI

Object.assign(window.ETF_EN,{'报告完成标记与资料范围不一致，按部分资料展示。':'The completion marker conflicts with the evidence coverage; this is shown as a partial report.','研究来源与披露日期':'Research sources and publication dates','披露日期':'Publication date','资料获取时间':'Evidence retrieval time','已提取页码':'Extracted page numbers'});

Object.assign(window.ETF_EN,{
  '公司研究清单':'Company research lists',
  '全部公司':'All companies',
  '已深度研究':'Saved deep research',
  '只收录已有 AI 深研结果的公司，按最近研究时间排列；仍有缺口的报告也会保留。':'Companies with saved AI deep research, ordered by most recent research date. Reports with remaining gaps are included.',
  '正在读取清单…':'Loading the list…',
  '切换清单后已清空关键词和行业筛选。':'The keyword and industry filters were cleared when switching lists.',
  '当前筛选没有深研结果':'No deep research matches these filters',
  '尚无已保存的 AI 深研结果':'No saved AI deep research yet',
  '可以清空关键词或改选全部行业。':'Clear the keyword or select all industries.',
  '完成至少一轮 AI 阅读并保存报告后，公司会出现在这里。仅下载资料或因调用次数不足未开始的报告不会收录。':'A company appears here after at least one AI reading round and a saved report. Download-only reports or reports that never started because of the call limit are excluded.',
  '已整理':'Compiled',
  '仍有缺口':'Gaps remain',
  '已完成 AI 轮次':'AI rounds completed',
  '有证据的主题':'Topics with evidence',
  '来源文档':'Source documents',
  '研究日期':'Research date',
  '六类主题已整理，结论仍需结合原文与资料范围核查。':'All six topics have been compiled. Findings still require review of the sources and coverage.',
  '已有部分 AI 深研结果，可查看已保存证据并继续未完成主题。':'Some AI deep research is saved. View the evidence and continue unfinished topics.',
  '查看深研报告':'View deep research',
  '默认关闭，需同时开启自动财报扫描。开启后后台会为候选公司调用 AI，与手动深研共用每日上限。':'Off by default; automatic financial scanning must also be enabled. Background AI reviews of candidates share the daily limit with manual deep research.',
  '自动财报扫描（不调用 AI）':'Automatic financial scan (no AI calls)',
  '每日扫描财务资料，不消耗 AI 调用次数。关闭网页后仍继续。':'Scan financial data daily without using AI calls. Scanning continues after the page is closed.',
  '自动 AI 证据整理（消耗调用次数）':'Automatic AI evidence review (uses calls)',
  '默认关闭。开启后后台会为候选公司调用 AI，与手动深研共用每日上限。':'Off by default. When enabled, background candidate reviews use AI calls and share the daily limit with manual deep research.',
  '本网站每日 AI 调用上限':'This website’s daily AI call limit',
  '财报扫描与自动 AI 分开控制。关闭自动 AI 只停止继续安排调用；已提交任务可单独停止。手动研究也受本网站每日上限约束，调整上限不会改变已用次数。':'Financial scanning and automatic AI have separate controls. Turning automatic AI off stops scheduling further calls; submitted tasks can be stopped individually. Manual research shares this website’s daily limit. Changing the limit does not reset calls already used.',
  '本网站每日 AI 调用次数已用尽或上限设为 0；这不表示 DeepSeek 余额不足。':'This website’s daily AI call limit is exhausted or set to zero. This does not mean the DeepSeek account has insufficient funds.',
  '等待网站调用次数恢复':'Waiting for website calls to become available',
  '本主题当时因本网站每日调用次数不足，尚未完成 AI 阅读；这不表示公司有问题或原文证据不足。':'AI reading of this topic was not completed because this website’s daily call allowance was insufficient. This does not indicate a company problem or a lack of source evidence.',
  '网站次数统计日期':'Website call accounting date',
  '次数恢复时间（北京时间）':'Calls reset at (Beijing time)',
  '次数恢复规则':'Call reset schedule',
  '每天北京时间 00:00 重新计数':'The call count resets daily at 00:00 Beijing time',
  '这里统计本网站每日请求次数，不是 DeepSeek 账户余额或 token 余额；达到上限不代表 API 没钱。':'This counts daily requests made by this website, not the DeepSeek account balance or token balance. Reaching the limit does not mean the API account has run out of funds.',
  '今日网站调用次数已用尽或上限设为 0，尚未发出新的 AI 请求。可等待恢复或自行调整每日上限。':'Today’s website call allowance is exhausted or set to zero. No new AI request has been sent. Wait for the reset or adjust the daily limit yourself.',
  '已有成功轮次可能可以复用；继续后会核对资料与缓存，未命中的轮次等待调用次数恢复。':'Previously successful rounds may be reusable. Continuing checks the evidence and cache; unmatched rounds wait until calls are available.',
  '剩余额度不足 3 轮；可继续未完成主题，已成功且资料未变的轮次不重复调用。':'Fewer than 3 calls remain. Unfinished topics can continue; successful rounds with unchanged evidence do not make duplicate calls.',
  '每日上限为 0 时，跨日后仍不会发出 AI 请求；请先在研究设置中设定上限。':'A daily limit of zero still blocks AI requests after midnight. Set a limit in research settings first.',
  '等待调用次数恢复':'Waiting for calls to become available',
  '继续未完成研究':'Continue unfinished research',
  '查看调用设置':'View call settings',
  '尚无已保存的深度研究报告。本次不会生成空报告；次数可用后再开始研究。':'No deep research report has been saved. This attempt will not create an empty report; start research when calls become available.',
  '报告中标记等待次数恢复的主题，当时尚未完成 AI 阅读；这是本网站的调用次数限制，不是公司的负面结论，也不能据此判断 DeepSeek 余额不足。':'Topics marked as waiting for calls did not complete AI reading at that time. This is this website’s call limit, not a negative company finding or evidence of an insufficient DeepSeek balance.',
  '当时尚未配置 AI 服务，未执行本主题阅读；请配置服务后继续研究。':'AI was not configured when this topic was attempted, so it was not read. Configure the service to continue.',
  '本主题尚未安排 AI 阅读，不能当作已阅读后发现证据不足。':'AI reading has not been scheduled for this topic. This is not a finding of insufficient evidence after reading.'
});
Object.assign(window.ETF_EN,{
  '本程序今日AI调用次数已用尽或上限设为0，北京时间次日0时重置；不是供应商余额检查，财务筛选可继续':'This application’s daily AI allowance is exhausted or set to zero. The count resets at midnight Beijing time. This is not a provider balance check; financial screening can continue.',
  '本程序AI每日调用上限设为0，且没有可复用轮次线索；深研尚未启动，原报告保留。次日计数重置不会改变这个上限。':'The application’s daily AI limit is zero and no reusable rounds were found. Deep research has not started and the previous report is retained. Resetting the count tomorrow will not change this limit.',
  '本程序今日AI调用次数已用尽，且没有可复用轮次线索；深研尚未启动，原报告保留。北京时间次日0时重置。':'The application’s daily AI allowance is exhausted and no reusable rounds were found. Deep research has not started and the previous report is retained. The count resets at midnight Beijing time.',
  '尚未配置AI，本次只整理公开资料，不会生成AI完成状态。':'AI is not configured. This task only organizes public documents and will not claim completed AI research.',
  '发现该公司的已保存轮次，可核对并复用；今天不发起新AI请求，缓存是否仍适用需核对当前资料。':'Saved rounds were found for this company and can be checked for reuse. No new AI requests will be made today; cache applicability must be checked against current evidence.',
  '可开始研究，最多请求3次；已核对的缓存轮次不重复计次，剩余次数不足时保存部分结果。':'Research can start with up to 3 calls. Validated cached rounds do not consume additional calls; partial results are saved if the allowance runs out.'
});

Object.assign(window.ETF_EN,{
  '已从本次深研保存的资料补算财务分析，无需再次调用 AI。':'Financial analysis has been recalculated from this research run’s saved data, without another AI call.',
  '下方为补算的财务结果；上方 AI 原文摘录及其生成时间保持不变，不代表旧 AI 已使用这些数值。':'The financial results below were recalculated. The AI excerpts and their generation date above are unchanged; this does not mean the original AI used these values.',
  '财务资料获取时间':'Financial data collected at',
  '财务资料截止日期':'Financial data as of',
  '财务分析使用本次深度研究取得的数据，按各模块规则计算。':'Financial analysis uses data collected for this deep research run, calculated under each module’s rules.',
  '暂未找到可安全补算的同批财务资料。下方保留原报告快照；显示缺资料不等于公司没有年报。':'Matching financial data could not be recovered safely. The original snapshot is retained below; missing data does not mean the company has no annual reports.',
  '查看原报告保存的财务快照':'View the original saved financial snapshot',
  '这是修复前保存的原始快照，可能尚未包含历年数据。':'This is the original snapshot saved before the fix; historical financial data may be absent.'
});

Object.assign(window.ETF_EN,{
  '每日 AI 调用上限必须是 0 到 100 的整数。':'The daily AI request limit must be a whole number from 0 to 100.',
  'AI每日调用上限须为0至100次':'The daily AI request limit must be a whole number from 0 to 100.',
  '深度研究轮数须为3或6':'Choose either 3 or 6 rounds for each deep research task.',
  '单次深度研究轮数只能选择 3 轮或 6 轮。':'Choose either 3 or 6 rounds for each deep research task.',
  '单次深度研究轮数':'Rounds per deep research task',
  '最多 3 轮':'Up to 3 rounds',
  '最多 6 轮':'Up to 6 rounds',
  '6 轮分别研究六类主题，3 轮合并整理。新任务使用保存后的设置；已保存报告和进行中的任务保留原轮数。':'Six rounds review the six topics separately; three rounds group them together. New tasks use the saved setting. Saved reports and tasks already running keep their original round counts.',
  '每次研究最多安排 6 轮 AI 调用，计入现有每日上限；已成功且资料未变化的轮次可复用，不重复计费。':'Each research task schedules up to 6 AI rounds within the existing daily limit. Successful rounds with unchanged evidence may be reused without another call.',
  '剩余额度不足 6 轮；可继续未完成主题，已成功且资料未变的轮次不重复调用。':'Fewer than 6 calls remain. Unfinished topics can continue; successful rounds with unchanged evidence do not make duplicate calls.',
  '已保存报告保留生成时的轮次；上方轮数用于新任务，不代表旧报告已补足。':'Saved reports retain the round count used when they were generated. The round limit above applies to new tasks and does not mean that previous reports have been expanded.',
  '可开始研究，最多请求6次；已核对的缓存轮次不重复计次，剩余次数不足时保存部分结果。':'Research can start with up to 6 calls. Validated cached rounds do not consume additional calls; partial results are saved if the allowance runs out.'
});
Object.assign(window.ETF_EN,{
  '生意模式与竞争证据':'Business model and competition evidence',
  '财务、债务与治理':'Finances, debt and governance',
  '资本使用、价格条件与反证':'Capital use, price conditions and counterevidence',
  '竞争与护城河证据':'Competition and moat evidence',
  '财务持续性与现金':'Financial sustainability and cash',
  '债务、审计与治理':'Debt, audit and governance',
  '资本使用与价格条件':'Capital use and price conditions',
  '风险、反证与待核问题':'Risks, counterevidence and open questions',
  '（复用已核对结果）':' (reusing validated results)',
  '每轮只读长度受限的主题页节选；已提取页数不等于AI逐页阅读，全部轮次完成也不是完整尽调。':'Each round reads limited excerpts from relevant pages. Extracted page counts do not mean AI has read every page, and finishing all rounds does not constitute full due diligence.'
});
window.ETF_EN_PATTERNS.push(
  [/主题 (\d+)\/(3|6)：/g,'Topic $1/$2: '],
  [/(3|6)轮深研原文已整理；仍需阅读资料范围、反证与缺口/g,'Source excerpts from $1 research rounds have been compiled. Review the evidence coverage, counterevidence and remaining gaps.'],
  [/本次计划(3|6)轮主题研究，已完成(\d+)轮（含明确保留判断的轮次）；请结合资料范围、反证与缺口阅读。/g,'This research task planned $1 topic rounds and completed $2, including rounds that explicitly withheld judgment. Read alongside the evidence coverage, counterevidence and gaps.']
);

// Dynamic financial reference: independent of saved AI evidence and stock price.
Object.assign(window.ETF_EN,{
  '合并净利率':'Consolidated net margin','收入同比':'Revenue year-on-year growth','利润现金含量':'Cash conversion of profit','扣非盈利占比':'Recurring profit share',
  '当前详情中的财务资料':'Financial data in the current company detail',
  '已保存深研报告中的财务资料':'Financial data in the saved deep research report',
  '从已核对的深研缓存补算':'Recalculated from validated deep research cache',
  '尚无可用的多年财务来源':'No multi-year financial source is available yet',
  '多年资料尚未补齐；不能从单期推断长期稳定':'Multi-year data is incomplete. A single period does not establish long-term stability.',
  '首次记录；此前评价历史未回填':'First record; earlier evaluation history has not been backfilled',
  '评价规则版本更新；不同版本不计算分数升降':'Evaluation rules changed; score changes are not calculated across different versions',
  '财务报告期更新；不同报告期分开观察':'The financial reporting period changed; different periods are observed separately',
  '行业分组变化；不同分组不计算分数升降':'The industry group changed; score changes are not calculated across different groups',
  '资料覆盖变化；不能把补齐资料当作经营改善':'Data coverage changed; filling data gaps does not establish operating improvement',
  '评价适用性或风险状态变化':'Evaluation applicability or risk status changed',
  '风险提示变化，请查看具体事项':'Risk alerts changed; review the specific matters',
  '公司财务或披露条件变化；同报告期变化可能来自资料修订':'Company finances or disclosure conditions changed; changes within the same period may reflect data revisions',
  '同行成员或财务数据变化；相对位置变化不等于公司自身变化':'Peer membership or financial data changed; a relative-position change does not establish a change in the company itself',
  '评价依据更新':'Evaluation evidence updated',
  '当前评价尚待后台记录；保留已有观察历史':'The current evaluation is awaiting a background record; existing observation history is retained',
  '指标原始数值缺失或无效':'The original metric value is missing or invalid',
  '指标来源未确认':'The metric source is unconfirmed',
  '指标报告期或公告日期未确认':'The metric reporting period or publication date is unconfirmed',
  '指标报告期与公司报告期不一致':'The metric reporting period differs from the company reporting period',
  '指标公告日期早于报告期':'The metric publication date precedes its reporting period',
  '指标报告或公告晚于评价截止日':'The metric report or publication date is after the evaluation cutoff',
  '指标来源存在冲突或无效标记':'The metric source is marked as conflicting or invalid',
  '指标币种或财务口径不一致':'The metric currency or financial basis is inconsistent',
  '原财务筛查已识别高风险，需先核查':'Original financial screening identified high risk; review it first',
  '存续A股身份尚未核验':'Active A-share identity has not been verified',
  '财务来源存在未解决冲突':'Unresolved conflicts exist in the financial sources',
  '风险警示或退市事项需核查':'Risk warnings or delisting matters require review',
  '审计意见需专项核查':'The audit opinion requires specific review',
  '持续经营重大不确定性':'Material going-concern uncertainty',
  '债务违约':'Debt default',
  '财务违规调查':'Investigation of financial irregularities',
  '合并总资产不高于总负债':'Consolidated assets do not exceed total liabilities',
  '合并或归母盈利非正，不适用普通同行换算':'Consolidated or attributable profit is nonpositive; general peer scaling is not applicable',
  '资产负债率为负，需核对数值口径':'The debt-to-assets ratio is negative; verify the numeric basis',
  '证券代码与交易所不一致':'The security code and exchange are inconsistent',
  '细分行业未确认':'The detailed industry is unconfirmed',
  '公司报告期或公告日期未确认':'The company reporting period or publication date is unconfirmed',
  '公司报告或公告晚于评价截止日':'The company report or publication date is after the evaluation cutoff',
  '公司公告日期早于报告期':'The company publication date precedes its reporting period',
  '币种或财务口径未确认或不适用':'The currency or financial basis is unconfirmed or inapplicable',
  '行业门控未明确允许普通财务排名':'Industry applicability does not explicitly permit general financial ranking',
  '行业判定晚于评价截止日':'The industry assessment is after the evaluation cutoff',
  '合并及归母盈利均为正的条件未满足':'The condition requiring positive consolidated and attributable profit is not met',
  '盈利来源、日期或口径未确认':'Profit sources, dates or basis are unconfirmed',
  '存在已识别高风险，需先核查':'Identified high risks require review first',
  '指标数值或正分母条件不足':'The metric value or positive-denominator requirement is not satisfied',
  '同一证券存在冲突记录，已从同行样本排除':'Conflicting records for this security have been excluded from the peer sample',
  '同一证券存在冲突记录':'Conflicting records exist for the same security',
  '同口径可用其他公司不足5家':'Fewer than five other usable companies have a matching financial basis',
  '同行数值尺度超出可计算范围':'The scale of peer values exceeds the calculable range',
  '六项可比资料未齐全，暂不合成同行财务参考':'Comparable data for all six metrics is incomplete; no combined peer financial reference is produced',
  '按相同细行业、报告期、币种和财务口径，对照至少5家其他可比公司；以同业中位数及四分位间距连续换算，六项齐全才按原权重合成。50表示同业中位附近，不是合格线、百分位或胜率。ROE及增长按原报告期使用，不将季度或半年值年化。仅为当前供应商快照的研究参考，未完成官方逐值核验、严格历史时点验证或收益回测；不替代绝对风险、多年财务和价格判断。':'Compare with at least five other companies matching the detailed industry, reporting period, currency and financial basis. Values are continuously scaled using the peer median and interquartile range, then combined with the original weights only when all six metrics are available. 50 is near the peer median, not a passing mark, percentile or win rate. ROE and growth use their original reporting periods; quarterly or half-year values are not annualized. This is a research reference from current supplier snapshots, without official value-by-value verification, strict point-in-time validation or return backtesting. Absolute risks, multi-year finances and prices require separate assessment.',
  '动态财务评价':'Dynamic financial evaluation',
  '同行财务参考':'Peer financial reference',
  '原财务初筛':'Original financial screening',
  '原财务初筛优先':'Original financial screening first',
  '同行财务参考优先':'Peer financial reference first',
  '同行参考可用':'Peer reference available',
  '需行业专项研究':'Sector-specific research required',
  '风险事项待核查':'Risk matters require review',
  '尚无同行参考':'No peer reference yet',
  '净资产收益率 ROE':'Return on equity (ROE)',
  '核查事项尚待补充说明。':'Further detail is needed for this review item.',
  '多年财务':'Multi-year financials',
  '查看详情了解多年财务覆盖':'Open company details to view multi-year financial coverage',
  '多年财务表现':'Multi-year financial performance',
  '尚无可用的多年财务观察。':'No multi-year financial observations are available yet.',
  '财务研究截止':'Financial research cutoff',
  '年度覆盖只表示取得的财务资料范围，不代表经营质量已获确认。':'Annual coverage describes available financial data; it does not establish operating quality.',
  '50 为同业中位附近，非胜率或合格线。':'50 is near the peer median, not a win rate or a passing mark.',
  '可用财务项':'Financial metrics available',
  '存在需核查的绝对风险事项。':'Absolute risk matters require review.',
  '尚无动态评价资料，原财务初筛仍可查看。':'Dynamic evaluation data is unavailable. Original financial screening remains available.',
  '动态评价版本待更新，暂不展示。':'The dynamic evaluation version needs updating; its contents are withheld.',
  '动态评价主体与当前公司不一致，已停止展示。':'The dynamic evaluation belongs to another company and is withheld.',
  '当前动态评价来自最新财务快照，独立于下方已保存的 AI 报告。':'This dynamic evaluation uses the latest financial snapshot, independently of the saved AI report below.',
  '50 表示接近同行中位水平，不是及格线、胜率或安全概率。':'50 means close to the peer median. It is not a passing mark, a win rate or a probability of safety.',
  '可比同行数':'Comparable peers',
  '同行行业':'Peer industry',
  '当前评价截止':'Current evaluation cutoff',
  '同行参考与原财务初筛并列展示；价格与估值单独判断。两种财务参考都不是完整公司质量结论。':'Peer references and original financial screening are shown together. Price and valuation are assessed separately. Neither financial reference is a complete judgment of company quality.',
  '绝对风险与核查事项':'Absolute risks and matters for review',
  '当前未列出风险事项，不代表已经排除风险。':'No listed risk matters does not mean risks have been ruled out.',
  '相对财务表现不能抵消债务、审计或治理问题，仍需核对绝对数值与原文。':'Relative financial performance cannot offset debt, audit or governance concerns. Absolute values and source documents still need review.',
  '本公司绝对值':'Company absolute value',
  '连续同行参考':'Continuous peer reference',
  '固定权重':'Fixed weight',
  '同行下四分位数':'Peer lower quartile',
  '同行上四分位数':'Peer upper quartile',
  '同行换算尺度':'Peer scaling interval',
  '加权贡献':'Weighted contribution',
  '变化记录暂不可用；不从当前资料推造历史':'Change records are temporarily unavailable; history is not reconstructed from current data',
  '动态评价观察记录暂不可用；原报告与账户保留':'Dynamic evaluation records are temporarily unavailable; original reports and accounts are retained',
  '该财务项尚无可用资料。':'No usable data is available for this metric yet.',
  '数据与证据状态':'Data and evidence status',
  '基于供应商财务快照，尚未完成官方逐值核验。':'Based on supplier financial snapshots; official value-by-value verification is incomplete.',
  '当前评价及观察记录尚未认证严格历史时点可用，不能直接作为无前视偏差回测数据。':'Strict point-in-time usability has not been established for these evaluations or observation records. They cannot be treated directly as backtest data free of look-ahead bias.',
  '变化与实际观察记录':'Changes and actual observations',
  '本次观察时间':'Current observation time',
  '上次观察时间':'Previous observation time',
  '较上次记录变化':'Change since the previous record',
  '当前评价尚待后台记录；历史仅展示已保存的实际观察。':'This evaluation is awaiting a background record. History shows only actual observations already saved.',
  '这是首次实际观察，没有可比的前次记录。':'This is the first actual observation; no previous record is available for comparison.',
  '变化记录暂不可用，当前财务参考仍可查看。':'Change records are temporarily unavailable. The current financial reference remains available.',
  '尚无可用的变化原因。':'No explanation of changes is available yet.',
  '同行构成、覆盖范围或评价方法改变，不等于公司经营改善或恶化。':'Changes in peers, data coverage or methodology do not establish improvement or deterioration in the business.',
  '查看已保存的观察历史':'View saved observation history',
  '历史从本功能启用后的实际观察开始记录，不回填过去，也不是历史收益。':'History begins with actual observations after this feature was enabled. It does not backfill the past or represent historical returns.',
  '尚无已保存的观察历史。':'No observation history has been saved yet.',
  '观察时间':'Observation time',
  '查看比较方法与适用范围':'View comparison method and applicability',
  '只在同细行业、同报告期及可确认财务口径的同行中比较，每项至少需要 5 家其他公司。':'Comparisons require the same detailed industry, reporting period and confirmed financial basis, with at least five other companies per metric.',
  '分项根据公司数值与同行中位数的差距平滑换算，再按固定权重合并；缺项不重新分配权重。':'Each metric is smoothly scaled by its distance from the peer median, then combined with fixed weights. Missing metrics do not redistribute weights.',
  '参考值采用 0–100 连续刻度，不是精确百分位；负债率较低的方向较优，其他项目较高的方向较优。':'References use a continuous 0–100 scale, not exact percentiles. Lower debt ratios score more favorably; other metrics favor higher values.'
});

Object.assign(window.ETF_EN, {
  '↻ 更新全市场资料':'↻ Update all-market data',
  '读取服务器结果 ↻':'Read server results ↻',
  '读取服务器结果只更新页面显示；需要重新获取财报与行情，请使用“更新全市场资料”。':'Reading server results only updates this page. Use “Update all-market data” to retrieve financial reports and quotes from sources again.',
  '同行参考从高到低':'Peer reference: high to low',
  '原初筛从高到低':'Original screening: high to low',
  '当前排序：同行财务参考，从高到低；暂不可比较的公司排在后面。':'Sorted by peer financial reference, high to low. Companies without a comparable reference follow.',
  '当前排序：原财务初筛，从高到低；卡片上的同行参考不参与此排序。':'Sorted by original financial screening, high to low. The peer reference shown on cards does not determine this order.',
  '当前排序：按原财务风险优先；不按同行参考值排列。':'Sorted by original financial risk priority, not by peer reference.',
  '当前排序：市盈率 PE 从低到高；不按同行参考值排列。':'Sorted by P/E, low to high, not by peer reference.',
  '当前排序：证券代码；不按分数排列。':'Sorted by stock code, not by score.',
  '当前排序：深研报告时间，从新到旧。':'Sorted by deep-research report date, newest first.',
  '正在读取服务器已有结果…':'Reading existing server results…',
  '读取失败，请重试；页面保留上次成功读取的结果。':'Reading failed. Please retry; the page retains the last successfully read results.',
  '读取成功，服务器已有结果未变化。':'Read successfully. Existing server results are unchanged.',
  '读取成功，已显示服务器已有结果。':'Read successfully. Existing server results are now displayed.',
  '本次更新要求重新获取来源资料。':'This update requests fresh retrieval from the data sources.',
  '本次后台扫描可复用有效来源缓存。':'This background scan can reuse valid source caches.',
  '来源网络请求':'Source network requests',
  '来源缓存命中':'Source cache hits',
  '请求数不等于财务数据变更数。':'Request counts do not count changes to financial data.',
  '来源资料实际取得时间':'Actual source retrieval times',
  '来源获取已完成；没有新的披露或行情时，分数可能不变。':'Source retrieval is complete. Scores may remain unchanged when disclosures and quotes have not changed.',
  '本次来源获取未完整完成，未取得新资料的项目保留原有数据。':'Source retrieval is incomplete. Items without new data retain their existing data.',
  '点击“更新全市场资料”开始，真实资料取得后会出现在这里。资料不足不会生成好公司结论。':'Start with “Update all-market data”. Results appear as real data arrives. Missing data never produces a positive company assessment.',
  '全市场资料更新已提交，将重新获取来源资料；关闭网页后仍可继续。':'An all-market update has been submitted to retrieve source data again. It can continue after you close this page.'
});
Object.assign(window.ETF_EN, {
  '扫描请求格式无效':'The scan request format is invalid.',
  '财报扫描完成，已重新核对资料；数值与排序未必变化，估值覆盖另列':'Financial-report scanning is complete and source data has been checked again. Values and rankings may remain unchanged; valuation coverage is shown separately.'
});

// Featured strategy navigation and reading status.
Object.assign(window.ETF_EN, {
  "按策略组，查看重点候选": "Explore candidates by strategy group",
  "四资产、创业板五策略、七组合与海外市场，各自展示已有研究支持的观察名单。": "Research-based watchlists for four-asset strategies, the ChiNext five, seven combinations and overseas markets.",
  "各组采用自己的研究区间和筛选条件；请结合卡片依据阅读，不将不同组的年化直接排成总榜。": "Groups use their own research periods and selection criteria. Read each card's evidence; annualized returns across groups are not a common ranking.",
  "筛选覆盖了哪些策略？": "What does the selection cover?",
  "四资产：原九策略中，F/L 六个版本在最新五种费用与延迟情景中表现较稳健；统计检验仍为证据不足。": "Four assets: six F/L variants from the original nine showed relative resilience in five recent cost and delay scenarios; statistical evidence remains insufficient.",
  "创业板五策略：保留此前多周期研究选出的五个候选。七组合：接入此前七组合研究明确列出的三个重点观察方案。": "ChiNext five: retain the five candidates from prior multi-timeframe research. Seven combinations: include the three watchlist candidates explicitly identified in the original study.",
  "海外：按纳指、恒生指数、恒生科技分别展示既有研究候选；不同市场同名代码是不同模型。": "Overseas: display existing research candidates separately for Nasdaq, Hang Seng and Hang Seng Tech. Identical codes in different markets represent different models.",
  "已有回测不等于通过相同的最新测试。最新 27 模型压力研究未覆盖全部 84 个模型；未出现在本页的策略不能据此视为被淘汰。": "Prior backtests do not mean a model passed the same latest tests. The recent 27-model stress study did not cover all 84 models; absence from this page does not imply rejection.",
  "这是按已有研究整理的固定观察名单。读取最新信号只更新模型状态，不会重新甄选名单、重跑回测或调整账户。": "This is a fixed watchlist compiled from existing research. Reading the latest signals updates model status; it does not reselect the list, rerun backtests or adjust accounts.",
  "精选策略": "Selected strategies",
  "6 个重点观察策略": "6 strategies to watch",
  "从近期研究中整理少量候选，集中查看表现、风险与最新信号。": "A small shortlist from recent research, with performance, risk and the latest model signals in one place.",
  "查看全部策略": "View all strategies",
  "↻ 读取最新信号": "↻ Read latest signals",
  "本期精选：境内四资产 F 系列与 L 系列。以创业板为目标市场，可配置银行、黄金、国债或现金。": "This shortlist: domestic F and L multi-asset strategies. The target market is ChiNext; allocation can also include banks, gold, government bonds or cash.",
  "为什么选这 6 个？": "Why these six?",
  "在相同市场、区间和研究口径下，这 6 个版本在五种费用与延迟情景中，均比各自的过去波动对照年化更高、回撤更小。六个相关版本不等于六份独立证据。": "For the same market, period and research basis, these six variants had higher annualized returns and smaller drawdowns than their own past-volatility benchmarks in all five cost and delay scenarios. Six related variants are not six independent pieces of evidence.",
  "研究区间：2017-08-03 至 2026-09-24；历史已见，统计检验仍为证据不足。此处是重点观察名单，不是跨市场排名或未来最优结论。": "Research period: 2017-08-03 to 2026-09-24. This history has already been seen; statistical evidence remains insufficient. This is a watchlist, not a ranking across markets or a claim of future optimality.",
  "卡片收益来自固定研究；最新信号来自原有 2023 年起的参考模型，两者起点不同。读取最新信号不会重跑历史研究或调整账户。": "Card returns come from fixed research; current signals use the existing reference models starting in 2023. Their start dates differ. Reading signals does not rerun historical research or adjust accounts.",
  "正在读取最新信号…": "Reading the latest signals…",
  "尚未成功读取最新信号": "No successful signal read yet",
  "精选策略列表": "Selected strategies list",
  "最新状态读取失败，当前内容可能过期。": "The latest read failed; displayed data may be outdated.",
  "上次成功读取（北京时间）：": "Last successful read (Beijing time): ",
  " · 每个模型的确认时间见卡片": " · Each card shows its model confirmation time"
});

Object.assign(window.ETF_EN, {
  "账户与持有ETF资产对照曲线": "Account versus buy-and-hold ETF equity chart",
  "共同日终记录": "Common end-of-day records",
  "正在读取持有大盘ETF的同期收益…": "Loading broad-market ETF buy-and-hold returns for the same period…",
  "持有大盘ETF对照暂不可用，原账户曲线保留。": "The ETF comparison is temporarily unavailable. The original account chart is retained.",
  "重试ETF对照": "Retry ETF comparison",
  "大盘ETF": "Broad-market ETF",
  "上证50ETF（510050）": "SSE 50 ETF (510050)",
  "上证50ETF": "SSE 50 ETF",
  "持有对照": "Buy-and-hold benchmark",
  "同一本金 / 元": "Same initial capital / CNY",
  "比较区间": "Comparison period",
  "账户收益": "Account return",
  "持有ETF收益": "Buy-and-hold ETF return",
  "领先 / 落后（百分点）": "Ahead / behind (percentage points)",
  "账户收益 − 持有ETF收益": "Account return − ETF buy-and-hold return",
  "多赚 / 少赚（元）": "Earned more / less (CNY)",
  "账户期末资产 − 持有ETF期末资产": "Final account equity − final ETF buy-and-hold equity",
  "账户": "Account",
  "持有ETF": "Buy-and-hold ETF",
  "查看同区间对照曲线": "Show same-period comparison",
  "查看原始账户曲线": "Show original account chart",
  "原始曲线保留每日或逐柱记录；上方收益比较仍使用共同日终区间。": "The original chart retains daily or intraday records. The returns above still use the common end-of-day period.",
  "对照按双方均有记录的日终对齐；小时账户仅取已确认收盘记录，未收盘末日不参与比较。": "The comparison aligns common end-of-day records. Hourly accounts use confirmed closes only; an incomplete final day is excluded.",
  "账户原始记录截至": "Original account records through",
  "比较口径与数据来源": "Methodology and data sources",
  "行情来源": "Price data source",
  "行情供应方": "Price data provider",
  "资料取得时间": "Data retrieved at",
  "行情确认截至": "Confirmed market data through",
  "ETF行情截至": "ETF market data through"
});
Object.assign(window.ETF_EN, {
  "正在核对ETF对照数据，暂时保留上次结果。": "Checking ETF benchmark data. The previous result is retained while loading.",
  "本次ETF对照更新未完成；仍显示上述日期的结果。": "This ETF comparison refresh did not complete. The result for the dates above remains displayed.",
  "ETF对照截至日期早于账户原始记录；下方收益仅比较上述共同区间，不代表账户最新总收益。": "The ETF comparison ends before the original account records. Returns below cover only the common period above, not the account's latest total return.",
  "本地基准缓存不可读，暂用已核验内置行情；仅显示内置行情覆盖的共同日终。": "The local benchmark cache is unreadable. Verified bundled data are used temporarily, limited to the common daily closes they cover.",
  "基准使用随版本交付的已核验行情，后台独立更新后切换到新缓存。": "The benchmark uses verified data shipped with this release. It switches to new cache data after the independent background update."
});
Object.assign(window.ETF_EN, {
  "价格来源": "Price source",
  "分红来源": "Dividend source",
  "基金公司分红记录": "Fund manager dividend records",
  "分红官方核对": "Official dividend cross-check",
  "已核对分红记录": "Dividend records cross-checked",
  "腾讯未复权日线": "Tencent unadjusted daily prices",
  "东方财富基金分红资料": "Eastmoney fund dividend records",
  "同账户本金，从账户起始日开盘一次买入上证50ETF（510050）；采用未复权成交价，佣金万分之三且最低5元、买入滑点万分之二、100份整数手；现金分红在除息日计应收、支付日转现金，保留现金不再投资、不计利息；期末按收盘市值计价，不虚构卖出。账户与基准仅在共同已确认日终比较。": "Using the account's initial capital, buy SSE 50 ETF (510050) once at the account start day's open. Use unadjusted prices, 0.03% commission with a CNY 5 minimum, 0.02% purchase slippage and 100-unit lots. Cash dividends become receivables on the ex-date and cash on the payment date; cash is not reinvested and earns no interest. Value the final holding at the close without a terminal sale. Compare only common confirmed daily closes.",
  "账户曲线来自现有真实模拟记录，未重算策略、未改动账户或成交。": "The account curve uses existing paper records. Strategy calculations, accounts and trades are unchanged.",
  "未复权价格加现金分红；基金费用已反映在净值与市场价中，不额外重复扣管理费。": "Use unadjusted prices plus cash dividends. Fund expenses are already reflected in NAV and market prices; management fees are not deducted again.",
  "超额收益为账户累计收益率减去基准累计收益率，以百分点展示，并非保证未来超额。": "Excess return is account cumulative return minus benchmark cumulative return, in percentage points. It does not guarantee future outperformance.",
  "小时策略只取15:00日终资产；盘中点及未完成收盘日不与全天收盘价混比。": "Hourly strategies use 15:00 end-of-day equity only. Intraday points and incomplete sessions are not compared with full-day closes.",
  "本金不足买入一手并支付费用，基准保持现金，收益为真实零持仓结果。": "Capital is insufficient to buy one lot and cover costs. The benchmark remains in cash; zero return reflects no position.",
  "海外账户与境内上证50ETF的市场风险不同；原账户收益及分红处理沿用原引擎，此处仅增加基准。": "Overseas accounts and the domestic SSE 50 ETF have different market risks. Existing account returns and dividend treatment retain their original engine; only a benchmark is added."
});
window.ETF_EN_PATTERNS.push([/^原账户截止(.+)，本对照仅比较至共同已确认日终(.+)；后续点未用旧价填补。$/, (_,cutoff,end)=>`The original account runs through ${cutoff}; this comparison ends at the common confirmed daily close on ${end}. Later points are not filled with stale prices.`]);
Object.assign(window.ETF_EN, {
  "创业板指数": "ChiNext Index",
  "创业板指数（399006）": "ChiNext Index (399006)",
  "上证指数": "SSE Composite Index",
  "上证指数（000001）": "SSE Composite Index (000001)",
  "大盘指数": "Market index",
  "指数收益": "Index return",
  "同区间账户收益": "Account return for this period",
  "指数比较区间": "Index comparison period",
  "指数行情截至": "Index prices through",
  "指数对照暂不可用": "Index comparison unavailable",
  "暂无共同已确认日终记录": "No common confirmed daily closes available",
  "指数按各自共同日终区间比较；缺失日期留空，曲线不延长。指数等值本金仅反映价格涨跌。": "Each index uses its own common daily-close period. Missing dates remain empty and curves are not extended. Index-equivalent capital reflects price changes only.",
  "账户与大盘对照曲线；拖动或使用左右方向键查看当日数据": "Account and market comparison chart. Drag or use left and right arrow keys to view a date.",
  "拖动查看当日数据": "Drag to view daily data",
  "前一日": "Previous day",
  "后一日": "Next day",
  "最新": "Latest",
  "所选日期": "Selected date",
  "已确认日终记录": "Confirmed daily-close records",
  "已确认收盘": "Confirmed close",
  "资产 / 等值本金（元）": "Equity / equivalent capital (CNY)",
  "较上一记录": "Change since prior record",
  "累计收益": "Cumulative return",
  "无当日记录": "No record for this date",
  "同日账户记录不一致，暂不叠加指数对照。": "Account records disagree for the same date. This index comparison is temporarily excluded.",
  "价格指数不含现金分红": "Price index excluding cash dividends",
  "腾讯实际指数日线": "Tencent actual daily index prices",
  "按账户同一本金，将实际价格指数从账户起始日开盘点位归一化，逐日按收盘点位计算对照资产；不计交易费用、滑点或现金分红。该曲线是价格指数对标，不是可直接买卖的基金资产或含分红的全收益指数。账户与指数只比较共同已确认日终，缺失日线或账户日终不填补。": "Normalize the actual price index to the account's initial capital at the start day's opening level, then value it at daily closes. Exclude fees, slippage and cash dividends. This is a price-index comparison, not a tradable fund or a total-return index. Compare only common confirmed daily closes; missing index or account records are not filled.",
  "对照资产 = 账户初始本金 × 当日指数收盘点位 ÷ 起始日指数开盘点位。": "Equivalent equity = initial account capital × daily index close ÷ the start day's index open.",
  "指数涨跌采用实际价格指数，不包含成分股现金分红，也不模拟买卖交易。": "The comparison uses the actual price index, excludes constituent cash dividends and does not simulate trades.",
  "账户曲线沿用现有模拟记录；超额收益为两者同区间累计收益之差，单位为百分点。": "The account curve retains existing simulation records. Excess return is the difference in cumulative returns over the same period, in percentage points.",
  "小时策略只取15:00日终资产；盘中点及未完成收盘日不与全天收盘点位混比。": "Hourly strategies use 15:00 end-of-day equity only. Intraday points and incomplete days are not mixed with full-day closing index levels.",
  "本地指数缓存不可读，暂用已核验内置行情；仅显示内置行情覆盖的共同日终。": "The local index cache is unreadable. Verified bundled data are used temporarily, limited to common daily closes they cover.",
  "指数使用随版本交付的已核验行情，后台独立更新后切换到新缓存。": "The index uses verified data shipped with this release and switches to new cache data after the independent background update.",
  "指数行情暂不可用，账户资产曲线仍可查看。": "Index prices are unavailable; the account chart remains available.",
  "涨跌按上一条实际记录计算；首条无前值时显示 —。": "Changes use the preceding actual record. The first record shows — when no preceding value is available."
});

// Only the new navigation button and host H1 need global translation.
Object.assign(window.ETF_EN,{"前瞻模拟":"Forward simulation","D0 前瞻模拟":"D0 forward simulation"});
// Paper fixed text is opt-in; it must never join global substring replacement.
window.ETF_PAPER_EN=Object.freeze({"前瞻模拟":"Forward simulation","D0 前瞻模拟":"D0 forward simulation","D0 前瞻模拟账户":"D0 forward simulation account","待执行":"Pending simulation estimation","整单模拟估计成交":"Whole-order estimated simulation fill","已撤销":"Cancelled","已拒绝":"Rejected","已到期":"Expired","行情过期，等待新鲜报价":"The quote is stale; waiting for a fresh quote","等待提交后的报价":"Waiting for quotes after submission","行情时间在未来，等待核对":"The quote timestamp is in the future; awaiting verification","行情乱序，等待有效报价":"Quotes are out of order; waiting for valid quotes","行情与提交同秒，等待下一秒报价":"The quote and submission share the same second; wait for a quote from a later second","等待连续两份有效报价及量额推进":"Waiting for two consecutive valid quotes with increasing cumulative volume and turnover","非连续竞价时段，等待":"Outside the continuous-auction window; waiting","交易规则待核对":"Trading rules require verification","明确停牌，等待":"Explicitly suspended; waiting","收盘目标过旧，等待确认":"The close-confirmed target is stale; awaiting confirmation","时钟异常，等待核对":"Clock anomaly; awaiting verification","未记录":"Not recorded","待核对":"Needs verification","（时区未标明，待核对）":"(Time zone unspecified; needs verification)","时间无效，待核对":"Invalid timestamp; needs verification"," 北京时间":" China Standard Time","（秒级）":"(second precision)","（小数秒 {digits} 位）":"({digits} fractional-second digits)","无法计算":"Cannot calculate","未来时间，等待核对":"Future timestamp; awaiting verification","{seconds} 秒（本机显示年龄）":"{seconds} seconds (display age using this device's clock)","信号确认":"Signal confirmed","委托提交":"Order submitted","撮合资格起点":"Simulation-estimation eligibility begins","行情源时间":"Quote source time","行情接收":"Quote received","估计成交记账":"Estimated fill recorded at","委托到期":"Order expiry","本轮启动":"Current run started","正在核对…":"Checking...","创建账户（默认停止）":"Create account (stopped by default)","保存本金":"Save capital","上次操作结果仍不明，写入暂锁定；请刷新核对，避免用新请求重复操作。":"The previous operation's outcome is still unknown. Writes are locked temporarily; refresh and verify before submitting another request.","模拟服务状态待核对；暂不能写入，请刷新状态。":"The simulation service state needs verification. Writes are unavailable for now; refresh the status.","有未保存草稿，请先保存本金或重新选择账户再启动。":"You have an unsaved draft. Save the capital or select the account again before starting.","创建后默认停止，确认状态后可手动启动。":"The account is stopped by default after creation. Verify its state, then start it manually.","账户状态待核对，暂不能操作。":"The account state needs verification; actions are unavailable for now.","暂停会撤销剩余委托并释放冻结，已记账的模拟估计成交保留。":"Pausing cancels outstanding orders and releases reservations. Recorded estimated simulation fills are retained.","启动后从当前时刻向前运行，等待委托提交后的有效报价。":"After starting, the simulation moves forward from the current time and waits for valid quotes after order submission.","按实际接收的报价向前执行，独立记录现金、委托和模拟估计成交。":"Advance using the quotes actually received, with independent records of cash, orders and estimated simulation fills.","刷新状态":"Refresh status","第一阶段 · 报价驱动整单估计":"Phase one: quote-driven whole-order simulation estimates","公共报价没有盘口，停牌与可交易状态未核验。连续两份提交后有效报价及量额推进只是估计活动门槛，不能证明真实流动性；整单估计隐含整单流动性假设。":"Public quotes provide no order book, and suspension and tradability are unverified. Two valid post-submission quotes with increasing cumulative volume and turnover are only an estimation activity gate, not proof of liquidity. Whole-order estimates assume sufficient liquidity for the entire order.","账户从启动时刻向前运行：09:35 启动不会补记 09:30 开盘成交。费用和滑点为模拟假设。":"The account moves forward from its start time. Starting at 09:35 does not backfill a 09:30 opening fill. Fees and slippage are simulation assumptions.","独立账户设置":"Independent account settings","选择前瞻模拟账户":"Select a forward simulation account","本期每个服务最多一个独立 D0 账户，已有账户后不再新建。":"This release allows at most one independent D0 account per service. Another account cannot be created once one exists.","本金（元）":"Capital (CNY)","本金仅在停止、尚无模拟估计成交且后端允许时可配置。金额最多两位小数，上限10亿元。":"Capital can be configured only while stopped, before any estimated simulation fill, and when the server permits it. Use at most two decimal places; the maximum is CNY 1 billion.","有未保存的修改；状态展示仍按已保存账户。":"You have unsaved changes. The displayed state still reflects the saved account.","启动模拟":"Start simulation","暂停并撤余单":"Pause and cancel outstanding orders","资产与运行状态":"Assets and running state","当前收盘信号与执行计划":"Current close-confirmed signal and simulation plan","收盘确认时间、首次可知时间与委托提交时间各自记录。报价不生成新的盘中策略。":"Close-confirmation time, first-known time and order-submission time are recorded separately. Quotes do not generate a new intraday strategy.","持仓与可卖份额":"Holdings and sellable units","缺少有效报价的持仓估值显示待核对，不按零估值。":"Holdings without a valid valuation quote show that verification is needed; they are not valued at zero.","报价来源与数据年龄":"Quote sources and data ages","年龄由本机时间计算用于展示；是否可用于估计成交由后端逐条核验。":"Ages use this device's clock for display. The server validates each quote's eligibility for simulation estimation.","限价委托":"Limit orders","买单冻结现金，卖单冻结可卖份额；已撤销或到期的订单不会因迟到报价恢复。":"Buy orders reserve cash; sell orders reserve sellable units. Late quotes do not revive cancelled or expired orders.","模拟估计成交明细":"Estimated simulation fill details","本期整单估计不证明真实排队、市场冲击或可成交数量。":"This release's whole-order estimates do not establish real queue position, market impact or quantities that could actually fill.","模拟事件记录":"Simulation event records","仅显示独立模拟账户事件。":"Only events from the independent simulation account are shown.","逐标的规则与模拟费率":"Per-security rules and simulation fees","委托冻结时保存规则和费用版本；这里显示响应中的规则和模拟假设。":"Rule and fee versions are saved when an order reserves funds or units. This section shows the response's rules and simulation assumptions.","选择账户":"Select an account","暂无前瞻模拟账户":"No forward simulation account","创建一个独立账户后，在这里核对资产与运行状态。":"After creating an independent account, verify its assets and running state here.","运行中 · 模拟估计":"Running: simulation estimation","已暂停":"Paused","状态待核对":"State needs verification","已保存本金":"Saved capital","现金总额":"Total cash","冻结现金":"Reserved cash","可用现金":"Available cash","持仓估值":"Holdings valuation","总资产估值":"Estimated equity"," 元":" CNY","估值按后端返回的报价记录。":"Valuation uses the quote records returned by the server.","估值过期 / 待核对":"Valuation stale / needs verification","执行状态：":"Simulation-estimation state:","等待":"Waiting","估计执行中":"Simulation estimation active","状态生成：":"Snapshot generated:","观察服务：":"Observation service:","可用":"Available","部分异常":"Partially degraded","暂不可用":"Temporarily unavailable","观察中":"Observing","异常":"Error"," · 最近观察 ":" / Last observation ","D0 收盘确认信号":"D0 close-confirmed signal","信号 / 计划 ID":"Signal / plan IDs","确认日 / 执行日":"Confirmation / simulation day","信号版本 / 来源":"Signal version / source","信号确认 · signal_at":"Signal confirmed / signal_at","首次可知 · known_at":"First known / known_at","数据截止 · data_cutoff":"Data cutoff / data_cutoff","信号状态":"Signal state","有效收盘目标":"Valid close-confirmed target"," 目标权重":" Target weight","尚无已确认信号，等待收盘目标。":"No confirmed signal yet; waiting for a close-confirmed target.","持有份额":"Held units","冻结份额":"Reserved units","可卖份额":"Sellable units","锁定份额":"Locked units","估值报价":"Valuation quote","按记录报价估值":"Valued using recorded quotes","来源 / 报价ID":"Source / quote ID","暂无持仓":"No holdings","等待账户数据":"Waiting for account data","报价 / 报价ID":"Quote / quote ID","来源 / 时间精度":"Source / time precision","行情源年龄":"Quote source age","接收后年龄":"Age since receipt","快照源年龄（后端）":"Snapshot source age (server)"," 秒":" seconds","源延迟（后端）":"Source delay (server)","队列延迟（后端）":"Queue delay (server)","累计量 / 额":"Cumulative volume / turnover","估计活动门槛":"Estimation activity gate","已达估计活动门槛，仍无流动性证明":"Estimation activity gate met; liquidity is still unproven","行情无效，等待":"Invalid quote; waiting","等待后端核验":"Waiting for server verification","停牌 / 可交易状态":"Suspension / tradability state","公共报价未核验":"Public quote unverified","状态待核对，本期公共适配器无官方可交易证明":"Status needs verification; this release's public-data adapter provides no official proof of tradability","尚无报价；等待后续有效行情。":"No quotes yet; waiting for subsequent valid quotes.","方向待核对":"Side needs verification","状态待核对（本期不支持部分成交）":"Status needs verification (this release does not support partial simulation fills)","订单 ID":"Order ID","计划 / 意图 / 信号 ID":"Plan / intent / signal IDs","限价":"Limit price","委托数量 / 剩余":"Order quantity / remaining","冻结资金 / 份额":"Reserved cash / units"," 元 / ":" CNY / ","等待 / 处理原因":"Waiting / processing reason","规则 / 费率版本":"Rule / fee versions","撤销此委托":"Cancel this order","撤销委托 ":"Cancel order ","暂无委托。启动后由已确认的 D0 目标生成新的执行计划。":"No orders. After starting, a confirmed D0 target generates a new simulation plan."," · 模拟估计成交":" / Estimated simulation fill","估计成交 ID":"Estimated fill ID","订单 / 计划 / 意图 ID":"Order / plan / intent IDs","信号 / 报价 ID":"Signal / quote IDs","估计价格 / 数量":"Estimated price / quantity","估计成交金额":"Estimated fill amount","模拟费用":"Simulation fees","滑点假设（基点）":"Assumed slippage (basis points)","报价来源":"Quote source","模型 / 规则 / 费率版本":"Model / rule / fee versions","尚无模拟估计成交；不会补记启动前的成交。":"No estimated simulation fills yet. Fills before the start time are not backfilled.","模拟事件":"Simulation event","事件 ID":"Event ID","关联订单 / 成交 / 计划":"Related order / estimated fill / plan","事件时间 · at":"Event time / at","暂无独立模拟事件。":"No independent simulation events.","规则版本":"Rule version","生效日期":"Effective from","有效截止":"Valid through","交易单位（份）":"Trading lot size (units)","价格档位":"Price tick","可卖规则":"Sellability rule","价格限制比例":"Price-limit ratio","未提供，待核对":"Not provided; needs verification","规则核验来源":"Rule verification sources","规则状态":"Rule state","规则已核验":"Rules verified","规则待核对":"Rules need verification","模拟费率与估计条件":"Simulation fees and estimation conditions","费率版本":"Fee version","模拟费率":"Simulation fee rate","模拟最低费用":"Minimum simulation fee","模型版本 / 参数说明":"Model version / parameter description","源延迟上限（秒）":"Maximum source delay (seconds)","撮合年龄上限（秒）":"Maximum quote age for simulation estimation (seconds)","队列延迟上限（秒）":"Maximum queue delay (seconds)","阈值边界":"Threshold boundary","等于上限允许":"Equal to the limit is allowed","连续报价要求":"Consecutive quotes required","交易窗口":"Continuous-auction windows","（左闭右开）":"(start inclusive, end exclusive)","日内到期时间":"Intraday expiry time","费率与最低费用是模拟假设，不代表实际券商收费。当前无盘口，整单估计不能证明真实可成交数量。":"The fee rate and minimum fee are simulation assumptions, not actual broker charges. Without an order book, whole-order estimates cannot establish quantities that could actually fill.","上次操作已通过更新后的快照核对，请查看当前状态。":"The previous operation has been verified against a newer snapshot. Review the current state.","账户响应不完整，请刷新核对。":"The account response is incomplete. Refresh and verify.","收到较旧的账户响应，已保留当前状态。":"An older account response was received. The current state has been retained.","本金须为大于零且不超过10亿元的金额，最多两位小数。":"Capital must be greater than zero and no more than CNY 1 billion, with at most two decimal places.","账户名称须为1至80个字符。":"The account name must contain 1 to 80 characters.","操作未完成，请核对当前状态。":"The operation did not complete. Verify the current state.","操作已返回，当前状态已刷新。":"The operation returned and the current state has been refreshed.","账户已创建，默认停止；确认后可手动启动。":"The account was created and is stopped by default. Verify it, then start it manually.","账户已返回，请核对运行状态。":"The account returned. Verify its running state.","本金保存请求已返回，请核对已保存本金与当前资产。":"The save-capital request returned. Verify the saved capital and current assets.","模拟已启动，从本轮启动时刻向前等待有效报价。":"The simulation started. It waits for valid quotes from the current run's start time onward.","启动请求已返回，请查看当前状态与等待原因。":"The start request returned. Review the current state and waiting reason.","账户已暂停；请在委托与冻结资金中核对撤销结果。":"The account is paused. Verify cancellation results in orders and reserved cash.","暂停请求已返回，当前状态仍需核对。":"The pause request returned. The current state still needs verification.","撤单请求已返回，请查看委托的实际状态。":"The cancellation request returned. Review the order's current state.","操作已拒绝：":"Operation rejected: ","操作结果需核对：":"Operation outcome needs verification: ","。请刷新状态后再操作。":" Refresh the status before another action.","。请刷新状态，避免重复提交。":" Refresh the status and avoid duplicate submissions.","接口契约尚未接入；此页面暂不能读取或操作账户。":"The interface contract is not connected. This page cannot read or operate the account yet.","尚未观察到有效资料":"No valid data observed yet","尚未记录来源观察状态，等待核对":"Source observation state has not been recorded; awaiting verification","等待当日新鲜报价":"Waiting for fresh quotes from the current day","报价过期，等待后续新鲜报价":"Quotes are stale; waiting for subsequent fresh quotes","报价无效，等待有效资料":"Invalid quotes; waiting for valid data","报价接收后的处理延迟过大":"Processing delay after quote receipt exceeds the limit","缺少确认日线资料":"Confirmed daily data is missing","确认日线资料无效":"Confirmed daily data is invalid","缺少应有确认日资料":"Data for the required confirmation day is missing","交易日历不在已核验范围":"The trading date is outside the verified calendar range","历史资料修订，等待核对":"Historical data was revised; awaiting verification","公司行动资料需要核对":"Corporate-action data requires verification","持仓历史资料需要核对":"Holdings history requires verification","数据来源暂不可用":"The data source is temporarily unavailable","读取资料失败，等待重试":"Data could not be read; waiting to retry","观察服务异常，等待恢复":"The observation service encountered an error; awaiting recovery","等待有效的确认目标和新鲜报价":"Waiting for a valid confirmed target and fresh quotes","等待委托后的两份有效活动报价":"Waiting for two valid post-submission activity quotes","等待委托后两次新鲜成交证据":"Waiting for two fresh post-submission quote observations","等待报价":"Waiting for quotes","未提供":"Not provided","新建账户":"New account","账户名称":"Account name","已停止":"Stopped","买入":"Buy","卖出":"Sell","方向":"Side","报价采集失败，连续报价计数已清除；等待故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。":"Quote collection failed and the consecutive-quote count was cleared. Wait for two new, fresh, valid quotes after the failure, with increasing cumulative volume and turnover, before quote-driven whole-order simulation estimates can continue.","报价采集状态无效，等待核对与恢复；恢复后须重新取得故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。":"The quote collection state is invalid. Wait for verification and recovery, then obtain two new, fresh, valid quotes after the failure, with increasing cumulative volume and turnover, before quote-driven whole-order simulation estimates can continue.","当前报价的行情源时间或接收时间不晚于采集故障时点，不能用于恢复；等待故障之后的两份新鲜有效报价及累计量额推进，才可继续报价驱动的整单模拟估计。":"The quote's source time or receipt time is at or before the collection failure, so it cannot establish recovery. Wait for two new, fresh, valid quotes after the failure, with increasing cumulative volume and turnover, before quote-driven whole-order simulation estimates can continue.","采集故障会清除连续报价计数。恢复后须重新取得同标的、同来源的两份新鲜有效报价：行情源时间和接收时间均须晚于故障时点并递增，累计成交量和成交额均须推进，委托提交后的时间要求与连续竞价窗口仍适用。历史报价或过去已通过的活动门槛不能证明当前已恢复；满足条件仅允许报价驱动的整单模拟估计，不代表真实成交、可成交数量或券商执行。":"A collection failure clears the consecutive-quote count. Recovery requires two new, fresh, valid quotes for the same security from the same source: source and receipt times must both be after the failure and increase, and cumulative volume and turnover must both advance. Post-submission timing and continuous-auction windows still apply. Historical quotes or a previously passed activity gate do not prove current recovery. These conditions only permit quote-driven whole-order simulation estimates; they do not establish actual executions, available fill quantities, or broker execution."});

// Scoped fixed text for the read-only in-app simulated-order reminder section.
window.ETF_PAPER_EN = Object.freeze({...window.ETF_PAPER_EN, ...{"D0 站内交易提醒":"D0 in-app simulated-order reminders","提醒记录来自已提交且可追溯的模拟委托，供核对模拟计划与历史状态。数量、限价和方向均为模拟委托记录。":"Reminders come from submitted, traceable simulated orders and support review of simulation plans and historical states. Quantities, limit prices and sides are simulated-order records.","邮件推送尚未接入此账户":"Email delivery is not integrated with this account","提醒记录来自最近一次快照；当前状态待核对。":"Reminder records are from the last snapshot; their current state needs verification.","正在刷新提醒状态；以下为最近一次快照记录。":"Refreshing reminder status; the records below are from the last snapshot.","提醒状态以本次账户快照为准，请核对状态生成时间。":"Reminder status reflects this account snapshot. Check its generation time.","尚无独立模拟账户，创建账户后可查看站内提醒。":"There is no independent simulation account yet. In-app reminders can be viewed after an account is created.","此账户尚未接入提醒":"Reminders are not integrated with this account yet","提醒资料待核对，请刷新账户状态。":"Reminder data needs verification. Refresh the account status.","暂无站内交易提醒；已提交并可追溯的模拟委托会显示在这里。":"No in-app reminders yet. Submitted, traceable simulated orders will appear here.","当前模拟委托参考":"Current simulated-order reference","历史提醒":"Historical reminder","资料待核对":"Data needs verification","模拟委托方向":"Simulated-order side","模拟委托数量":"Simulated-order quantity","模拟委托限价":"Simulated-order limit price","提醒触发时间 · triggered_at":"Reminder trigger time / triggered_at","当前快照订单状态":"Order status in the current snapshot","提醒 ID":"Reminder ID","来源事件 ID":"Source event IDs","提醒分类原因代码":"Reminder classification reason code","提醒状态说明":"Reminder status explanation","此模拟委托可供当前核对，仍以本次快照为准。":"This simulated order can be reviewed as a current reference, subject to this snapshot.","这是操作返回时保存的模拟委托记录，仅供历史核对。":"This simulated-order record was saved with an operation response and is for historical review only.","账户已停止，此模拟委托仅保留历史参考。":"The account is stopped. This simulated order is retained for historical reference only.","模拟委托已撤销，仅保留历史记录。":"The simulated order was cancelled and is retained as a historical record only.","模拟委托已到期，仅保留历史记录。":"The simulated order expired and is retained as a historical record only.","已记录模拟估计成交，仅供历史核对，不代表真实成交。":"An estimated simulation fill was recorded. It is for historical review and does not establish an actual fill.","委托状态需要核对，暂不能作为当前模拟委托参考。":"The order status needs verification and cannot currently serve as a current simulated-order reference.","已超过模拟委托的到期时刻，仅保留历史参考。":"The simulated order's expiry time has passed. This is a historical reference only.","缺少订单、信号或计划的关联资料，请核对。":"Order, signal or plan associations are missing and need verification.","提交事件存在冲突，触发时间和事件归属需要核对。":"Submission events conflict. The trigger time and event association need verification.","缺少必要时间记录，请核对。":"Required time records are missing and need verification.","时间记录或时区无效，请核对。":"A time record or timezone is invalid and needs verification.","模拟委托资料不完整或无效，请核对。":"Simulated-order data is incomplete or invalid and needs verification.","记录中存在晚于当前快照的时间，请核对。":"A recorded time is later than the current snapshot and needs verification.","信号、计划或委托的时间顺序不一致，请核对。":"Signal, plan or order times are inconsistent and need verification.","此委托关联历史信号，仅保留历史参考。":"This order is linked to a historical signal and is retained for historical reference only.","此委托关联历史执行计划，仅保留历史参考。":"This order is linked to a historical simulation plan and is retained for historical reference only.","此委托属于较早的模拟启动批次，仅保留历史参考。":"This order belongs to an earlier simulation run and is retained for historical reference only.","数据来源尚未就绪，模拟委托资料需要核对。":"The data source is not ready. Simulated-order data needs verification.","观察服务尚未运行，模拟委托资料需要核对。":"The observation service is not running. Simulated-order data needs verification.","尚未到模拟委托的可执行时刻，此记录仅供核对。":"The simulated order is not yet eligible. This record is for review only.","当前不在连续竞价参考时段，此记录仅供历史核对。":"The current time is outside the continuous-auction reference window. This record is for historical review only.","模拟账户或信号状态不明确，请刷新核对。":"The simulation account or signal state is unclear. Refresh and verify.","最近快照资料待核对，请刷新确认。":"Data from the last snapshot needs verification. Refresh to confirm.","此模拟委托已结束或账户已停止，仅保留历史参考。":"This simulated order has ended or the account has stopped. It is retained for historical reference only.","提醒状态资料待核对，请刷新确认。":"Reminder status data needs verification. Refresh to confirm.","此记录仅用于核对模拟委托，不表示真实成交或券商执行。":"This record supports review of simulated orders only. It does not establish actual fills or broker execution.","部分提醒资料不完整或存在冲突，未展示；请刷新核对。":"Some reminders have incomplete or conflicting data and are not shown. Refresh and verify."}});

// Fixed UI text for inert email configuration drafts and read-only previews.
window.ETF_PAPER_EN = Object.freeze({...window.ETF_PAPER_EN, ...{"D0 邮件提醒配置草稿":"D0 email reminder configuration draft","配置草稿 / 拟订阅，通道待配置，发送关闭":"Configuration draft / proposed subscription; delivery channel pending, sending off","这里只保存收件地址与 D0 账户的配置草稿，邮件推送尚未接入此账户。":"Only a configuration draft containing a recipient and a D0 account is saved here. Email delivery is not integrated with this account.","收件地址（草稿）":"Recipient address (draft)","拟订阅的 D0 账户":"D0 account for the proposed subscription","保存配置草稿":"Save configuration draft","重新读取配置草稿":"Reload configuration draft","查看内容预览":"Preview content","邮件内容预览":"Email content preview","预览，未发送":"Preview, not sent","正在保存配置草稿；发送仍关闭。":"Saving the configuration draft; sending remains off.","正在读取配置草稿；发送仍关闭。":"Reading the configuration draft; sending remains off.","配置草稿尚未核对，请重新读取；发送仍关闭。":"The configuration draft needs verification. Reload it; sending remains off.","有未保存的邮件配置输入；下方已保存草稿仍为原值。":"Email configuration inputs have unsaved changes. The saved draft below still shows its original values.","配置草稿已核对；通道待配置，发送关闭。":"The configuration draft has been checked; the delivery channel is pending and sending is off.","草稿绑定目前不可用，请核对；发送仍关闭。":"The draft binding is currently unavailable and needs verification; sending remains off.","未绑定配置草稿，预览未发送":"No configuration draft is bound; preview not sent","请选择拟订阅的 D0 账户":"Select a D0 account for the proposed subscription","原绑定不可用，需核对":"Original binding unavailable; verification needed","原绑定目前不可用，保留原值":"Original binding currently unavailable; original value retained","尚未读取已保存的配置草稿。":"The saved configuration draft has not been read yet.","上次读取的草稿（待核对）":"Last-read draft (needs verification)","尚未保存配置草稿":"No configuration draft saved yet","保存的草稿待核对":"The saved draft needs verification","已保存的配置草稿":"Saved configuration draft","已保存收件地址":"Saved recipient address","已保存账户 ID":"Saved account ID","绑定账户创建时间":"Bound account creation time","最近读取的草稿状态待核对，请重新读取确认。":"The last-read draft status needs verification. Reload to confirm.","原绑定与当前账户快照不一致或尚未核对，未自动替换账户。":"The original binding differs from the current account snapshot or has not been verified. No account was replaced automatically.","草稿绑定或账户快照尚未核对，暂不能预览；不会改用其他账户。":"The draft binding or account snapshot needs verification. Preview is unavailable; another account will not be substituted.","拟收件地址（未保存输入）":"Proposed recipient (unsaved input)","草稿收件地址":"Draft recipient address","预览账户 ID":"Preview account ID","数据时点":"Snapshot time","本预览采用未保存输入；不会保存配置或发送邮件。":"This preview uses unsaved inputs. It does not save configuration or send email.","本预览仅核对已有模拟委托记录；不会保存配置或发送邮件。":"This preview reviews existing simulated-order records only. It does not save configuration or send email.","邮件配置草稿响应不完整，请重新读取核对。":"The email configuration draft response is incomplete. Reload and verify.","邮件配置草稿接口尚未接入。":"The email configuration draft interface is not connected yet.","请输入 1 至 254 个 ASCII 字符的有效收件地址；不能含空白、换行或控制字符。":"Enter a valid recipient address of 1 to 254 ASCII characters, without whitespace, newlines or control characters.","请选择当前可核对的 D0 账户；原绑定不会自动替换。":"Select a currently verifiable D0 account. The original binding will not be replaced automatically.","尚未保存邮件配置草稿。":"No email configuration draft has been saved yet.","草稿接口已核对原绑定账户身份。":"The draft interface verified the identity of the originally bound account.","账户服务暂不可用，原绑定未替换。":"The account service is temporarily unavailable. The original binding was not replaced.","原绑定账户目前不存在，原值已保留。":"The originally bound account is currently missing. Its original value is retained.","账户身份资料待核对，原绑定未替换。":"Account identity data needs verification. The original binding was not replaced.","账户身份已变化，原绑定不可用且未自动替换。":"The account identity has changed. The original binding is unavailable and was not replaced automatically.","保存的草稿资料无效，未回显异常内容。":"The saved draft data is invalid. Invalid content has not been displayed.","草稿格式未通过校验，请核对收件地址与账户后重新读取配置。":"The draft failed validation. Check the recipient and account, then reload the configuration.","账户绑定已不可用，请重新读取配置；原绑定不会自动替换。":"The account binding is unavailable. Reload the configuration; the original binding will not be replaced automatically.","草稿服务暂不可用，请稍后重新读取配置。":"The draft service is temporarily unavailable. Reload the configuration later.","配置草稿保存未确认，请重新读取核对后再保存。":"The configuration draft save was not confirmed. Reload and verify before saving again.","配置草稿请求未确认，请重新读取核对；发送仍关闭。":"The configuration draft request was not confirmed. Reload and verify; sending remains off."}});

// UX navigation and creation copy; historical/account payloads remain unchanged.
Object.assign(window.ETF_EN,{"历史回放账户": "Historical replay accounts", "历史回放": "Historical replay", "建立历史回放账户": "Create a historical replay account", "＋ 建立历史回放账户": "+ Historical replay account", "历史回放起点": "Replay start date", "总览": "Overview", "策略": "Strategies", "账户": "Accounts", "更多": "More", "更多功能": "More features", "全部功能": "All features", "关闭全部功能": "Close all features", "手机主导航": "Mobile navigation", "选择模拟方式": "Choose a simulation mode", "从你选定的日期开始": "Start from a date you choose", "从现在开始 · 仅 D0": "Start from now · D0 only", "查看 D0 前瞻模拟": "Open D0 forward simulation", "按原策略的已确认行情回放历史，也能继续跟踪后续数据。是否自动补跑、持续推进，沿用全局自动模拟与账户暂停设置。": "Replay confirmed historical data with the original strategy, then continue following later data. Catch-up and automatic advancement follow the existing global simulation and account pause settings.", "从手动启动时刻向前等待有效报价，不补记启动前成交。创建后默认停止，启动后在后台观察，直到暂停或按原规则停止。": "Wait for valid quotes from the time you manually start. No earlier fills are backfilled. Accounts start stopped; after activation, observation continues in the background until paused or stopped under the original rules.", "从指定日期回放已确认行情，之后仍可接续新数据。若要从现在开始且不补跑历史，请使用 D0 前瞻模拟。": "Replay confirmed data from a chosen date and continue with later data. To start from now without historical catch-up, use D0 forward simulation.", "我已确认策略、本金、起点，以及上述补跑和自动推进方式": "I have confirmed the strategy, capital, start date, catch-up and automatic advancement described above", "放弃本次未提交输入，重新填写": "Discard this unsent draft and start again", "用此策略建立模拟账户": "Create a paper account with this strategy", "自动设置读取未成功，暂不能建户；请等待恢复。": "Automatic settings could not be read. Account creation is disabled until recovery.", "全局自动模拟已开启：建户后会从所选起点补跑已有确认行情，并继续按原策略自动推进；可在账户详情暂停。": "Global automatic simulation is on: after creation, confirmed history is replayed from your selected date, then the original strategy advances automatically. You can pause it in account details.", "全局自动模拟已暂停：建户后不会自动补跑历史；可手动接续指定区间，后续仍按全局与逐账户设置运行。": "Global automatic simulation is paused: creation will not automatically replay history. You can advance manually; later operation follows global and account settings.", "最新状态读取失败，当前内容可能过期。旧信号仅供回看。": "The latest read failed. This content may be stale; old signals are for review only."});
window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,...{"当前状态读取未成功，写操作已禁用；请刷新状态核对。": "The current read failed. Writes are disabled; refresh and verify the status.", "当前状态待核对，以下为上次成功读取的记录；写操作已禁用。": "Current status needs verification. The records below are from the last successful read; writes are disabled.", "我已确认本金；仅支持 D0，从手动启动时刻开始，不补跑历史。创建后默认停止；启动后后台持续观察，按原规则运行，直到暂停或停止。": "I confirm the capital. Only D0 is supported, starting from manual activation without backfilling history. Creation leaves it stopped. After activation it observes in the background under the original rules until paused or stopped.", "机制与采集恢复细则": "Mechanism and collection recovery details", "仅模拟估计 · 目前仅支持 D0": "Simulation estimates only · D0 only", "公共报价无盘口，停牌与可交易状态未核验；整单估计不证明真实流动性。费用与滑点为模拟假设。": "Public quotes have no order book; suspension and tradability are unverified. Whole-order estimates do not prove liquidity. Fees and slippage are simulation assumptions.", "账户设置与邮件草稿（发送未启用）": "Account settings and email draft (sending off)", "修改账户设置": "Edit account settings", "详细依据：信号、报价、事件与规则": "Detailed evidence: signals, quotes, events and rules", "站内交易提醒与历史参考": "In-app trade alerts and historical references", "查看完整依据与字段": "Full evidence and fields", "估计记账时间：": "Estimated fill recorded: ", "尚未建立 D0 账户。请在下方设置中确认本金和起点；创建后默认停止。": "No D0 account yet. Confirm the capital and start behavior in settings below; creation leaves it stopped.", "待执行委托：": "Pending orders: ", "最新模拟估计成交：": "Latest estimated simulation fill: ", "暂无；不会补记启动前的成交。": "None. Fills before activation are not backfilled.", "查看持仓": "View holdings", "查看成交": "View fills", "查看委托": "View orders", "资产与运行详细依据": "Detailed asset and runtime evidence", "尚未保存邮件配置草稿；发送关闭。": "No email configuration draft has been saved; sending is off.", "草稿状态待核对。": "Draft status needs verification."}});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,'设置本金与起点':'Set capital and start behavior'});

Object.assign(window.ETF_EN,{'更多，当前：':'More, current: ','当前所在：':'Current location: '});
window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,'正在读取账户状态，请稍候。':'Loading account status. Please wait.','账户状态尚未核对，读取成功后显示建户或运行操作。':'Account status is not yet verified. Creation or running actions will appear after a successful read.'});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,...{
  "账户已接纳报价与数据年龄": "Quotes accepted by the account and their age",
  "这是账户最后接纳的报价，用于记录估值与核对成交依据；历史核验阻塞时可能早于最新市场报价。": "The last quotes accepted by the account support recorded valuations and fill evidence. They can lag behind market quotes while history requires review.",
  "最新市场报价（仅展示）": "Latest market quotes (display only)",
  "盘中报价目标每30秒采集，确认行情每5分钟核对；当前页面每30秒读取状态。最新报价不代表账户已接纳，也不代表可成交。": "During trading hours, quotes target a 30-second interval and confirmed data a 5-minute interval. This page reads status every 30 seconds. Displayed quotes do not imply account acceptance or execution.",
  "行情源时间：": "Source time: ",
  "采集接收时间：": "Received at: ",
  "近期采集 · 仅供查看": "Recently collected · display only",
  "报价过期或时间待核对 · 仅供查看": "Stale or unverified time · display only",
  "尚无可展示的市场报价，等待采集；账户旧报价见详细依据。": "Waiting for market quotes. Previously accepted quotes remain in detailed evidence.",
  "已保留原信号历史并接续后续完整日线，旧成交不重算；未来信号可能与全量修订行情不同。": "Prior signal history is preserved and later confirmed bars appended. Past fills are unchanged; future signals may differ from fully revised history.",
  "最新市场报价：": "Latest market quote: ",
  "账户已接纳报价：": "Account-accepted quote: ",
  "市场报价继续采集；账户因上述原因等待，旧报价不代表当前价格。": "Market collection continues; the account is waiting for the reason above. Older account quotes are not current market prices.",
  "找不到与原信号一致的可信历史快照，保留账本并等待核对": "No trusted history snapshot matches the prior signal. The ledger is preserved pending review.",
  "原信号历史凭据无效，等待核对": "Invalid prior signal history evidence; review required.",
  "D0 历史留存凭据校验失败，等待核对": "D0 history evidence failed integrity validation; review required.",
  "D0 历史留存凭据保存失败，等待恢复": "Could not save D0 history evidence; waiting for recovery.",
  "历史行情日期存在缺失或插入，等待核对": "Historical dates are missing or inserted; review required."
}});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,'部分或全部市场报价已过期或时间待核对，请等待采集恢复。':'Some or all market quotes are stale or have unverified times. Waiting for collection recovery.'});
window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '为什么这样持仓':'Why these holdings',
  '当前读取未成功，以下持仓逻辑来自上次成功快照。':'The current read failed. The rationale below is from the last successful snapshot.',
  '尚无已确认的 D0 信号，暂不能说明目标配置。':'No confirmed D0 signal is available yet to explain the target allocation.',
  '依据确认日 {day} 的 D0 信号 · 执行日 {execution_day}':'Based on the D0 signal confirmed for {day} · Execution day {execution_day}',
  '此信号或来源需要核对；以下是已保存的配置依据，不表示当前可以执行。':'The signal or source needs verification. These are saved allocation reasons, not confirmation that execution is currently available.',
  '按已确认的资产资格和强弱／波动评分分配目标。':'Targets use confirmed asset eligibility and momentum relative to volatility.',
  '只有{asset}通过配置资格，因此本次目标为该资产 100%。':'Only {asset} qualifies, so its target allocation is 100%.',
  '四只 ETF 均未通过配置资格，本次目标为现金 100%。':'None of the four ETFs qualify, so the target is 100% cash.',
  '已保存信号的持仓逻辑资料不完整；仅展示可核对的目标和实际持仓。':'The saved rationale is incomplete. Only available target and actual holding records are shown.',
  '模型目标':'Model target',
  '实际持有':'Actual holding',
  ' 份':' units',
  '实际资产占比':'Actual portfolio weight',
  '估值待核对':'Valuation needs verification',
  '通过配置资格':'Qualifies for allocation',
  '未通过配置资格':'Does not qualify for allocation',
  '资格依据未记录':'Eligibility evidence not recorded',
  '未保存此资产的具体判断依据，不能仅凭目标比例推断原因。':'No asset-specific explanation was saved. Its target weight alone does not establish the reason.',
  '查看评分指标':'View scoring metrics',
  '20日动量权重':'20-day momentum weight',
  '60日动量权重':'60-day momentum weight',
  'SKDJ评分权重':'SKDJ scoring weight',
  'TRIX评分权重':'TRIX scoring weight',
  '无评分权重；用于准入判断':'No scoring weight; used for eligibility',
  '无评分权重；本资产未使用':'No scoring weight; not used for this asset',
  '波动率作用':'Volatility role',
  '风险调整分母，最低按8%计算':'Risk-adjustment denominator, with an 8% floor',
  '60%／40%是动量项的公式权重，不是目标仓位或当期得分贡献占比。未通过配置资格时，有效评分为0。':'60%/40% are the momentum terms’ formula weights, not target allocations or shares of the current score. Ineligible assets have an effective score of 0.',
  '20日动量':'20-day momentum',
  '60日动量':'60-day momentum',
  '20日年化波动':'20-day annualized volatility',
  '有效评分':'Effective score',
  '评分用于合格资产间的相对分配，不是收益预测或成功概率。':'Scores determine relative allocation among qualifying assets; they are not return forecasts or probabilities of success.',
  '现金：':'Cash: ',
  '模型目标 {target} · 实际余额 {amount} 元':'Model target {target} · Actual balance CNY {amount}',
  '目标比例与实际持仓分开列示。100份整手、费用与限价资金预留、待执行委托及价格变化，都可能留下现金或造成比例偏差。':'Target weights and actual holdings are shown separately. Lots of 100 units, fees, cash reserved for limit orders, pending orders and price changes can leave residual cash or different weights.',
  '如何分配，什么时候调仓':'Allocation and rebalancing rules',
  '先筛选，再评分：各资产须通过原策略多头资格、指标完整性和同一确认日数据检查；合格资产按20日、60日动量相对20日波动的评分分配。只有一只合格时目标为100%，全部不合格时保留现金。':'Eligibility comes first: each asset must pass its original bullish signal, indicator completeness and same-day data checks. Qualifying assets share capital according to 20-day and 60-day momentum relative to 20-day volatility. A sole qualifying asset gets a 100% target; no qualifying assets means cash.',
  '交易日16:10后核对当日确认日线，新信号最早从下一交易日参与模拟。每次盘中报价更新用于估值与模拟估计，不直接生成新的择时信号。':'Daily bars are checked after 16:10 Beijing time on trading days. A new signal becomes eligible from the next trading day at the earliest. Intraday quotes update valuations and simulation estimates without directly creating new timing signals.',
  '执行计划建立后按计划份额处理，先卖后买；账户运行状态、资料有效性、交易时段、可卖份额及资金都会影响执行。暂停后重新启动会建立新计划。':'Once established, a plan uses its planned quantities, selling before buying. Account status, data validity, trading hours, sellable units and available cash affect execution. Resuming after a pause creates a new plan.',
  '委托提交后仍需两份同源、新鲜且成交量额递增的报价，并满足限价与规则，才可记入整单模拟估计成交。':'After submission, two fresh quotes from the same source with increasing volume and turnover, plus limit-price and rule checks, are required for a whole-order simulated fill estimate.'
});

window.ETF_EN=Object.freeze({...window.ETF_EN,
  "从现在开始 · 原D0 / 周线择债":"From now · Original D0 / Weekly bond selection",
  "原D0与D0I-BOND-WW周线择债分别独立记账。从手动启动时刻向前等待有效报价，不补记启动前成交；新账户默认停止。":"Original D0 and D0I-BOND-WW use separate ledgers. They wait for valid quotes after manual activation and do not backfill earlier fills. New accounts start stopped."
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '创业板ETF':'ChiNext ETF',
  '银行ETF':'Bank ETF',
  '黄金ETF':'Gold ETF',
  '5年国债ETF':'5-year Treasury ETF',
  '选择 ETF，查看指标怎样变成持仓':'Select an ETF to explore its decision path',
  '目标 {weight}':'Target {weight}',
  '指标怎样变成持仓':'How indicators become holdings',
  '选择一只 ETF，沿着已保存的确认信号查看配置过程。':'Select an ETF to follow the allocation recorded in its confirmed signal.',
  '① 看强弱：20日与60日动量':'1. Strength: 20-day and 60-day momentum',
  '零点居中，四只 ETF 共用刻度。动量为正，不等于通过配置资格。':'Zero is centered and all four ETFs share a scale. Positive momentum alone does not establish eligibility.',
  '② 看波动：实际指标与计算下限':'2. Volatility: observed value and calculation floor',
  '虚线：8% 评分计算下限':'Dashed line: 8% scoring floor',
  '评分的波动分母至少取8%；这不改变实测波动，也不是风险上限。':'The scoring denominator uses at least 8% volatility. This does not change observed volatility and is not a risk cap.',
  '配置资格':'Allocation eligibility',
  '原策略多头资格、指标完整性、同一确认日共同决定。':'The original bullish gate, complete indicators and matching confirmation date determine eligibility together.',
  '直接读取已保存评分；未通过资格的资产不参与权重分配。':'This is the saved score. Ineligible assets do not participate in allocation.',
  '合格资产按有效评分占比分配；这里显示已保存目标。':'Eligible assets are allocated in proportion to their effective scores. The saved target is shown here.',
  '评分指标尚未就绪；以已保存资格和目标记录为准。':'Scoring indicators are not ready. Refer to the saved eligibility and target records.',
  '评分完整性状态未记录，不能把缺失指标当作零。':'Indicator readiness was not recorded. Missing indicators must not be treated as zero.',
  '四只 ETF 的已保存目标':'Saved targets for all four ETFs',
  '目标之后：实际账户记录':'After the target: actual account records',
  '此 ETF 待执行委托':'Pending orders for this ETF',
  '{count} 笔':'{count} orders',
  '实际占比仅在账户与持仓估值均新鲜、且本次状态已核对时显示；保留的份额不代表当前估值。':'Actual weight is shown only after the current snapshot is verified and both account and holding valuations are fresh. Retained units do not establish a current valuation.',
  '市场报价时间（仅展示）':'Market quote time (display only)',
  '账户接纳报价时间':'Account-accepted quote time',
  '持仓估值引用时间':'Holding valuation quote time',
  '市场报价与账户接纳报价分别展示；市场报价更新不会直接改写账户估值。':'Market and account-accepted quotes are shown separately. Updating a market quote does not directly change account valuation.',
  '确认日与数据截止':'Confirmation day and data cutoff',
  '信号首次可知':'Signal first known',
  '信号记录时间：{time}':'Signal recorded at: {time}',
  '最早执行日':'Earliest execution day',
  '最早从执行日的连续竞价窗口参与模拟；仍须满足账户状态、报价和委托条件。':'Simulation may begin in a continuous-auction window on the execution day at the earliest, subject to account, quote and order conditions.',
  '何时确认，何时改变持仓':'When signals confirm and holdings change',
  '模拟连续竞价窗口（北京时间）：{windows}':'Simulation continuous-auction windows (China Standard Time): {windows}',
  '账户运行状态':'Account running state',
  '后台观察状态':'Background observation state',
  '执行状态':'Execution state',
  '信号更新先改变目标；实际份额在后续模拟估计成交记账后改变。页面切换与查看指标不会提交委托。':'A signal update changes the target first. Actual units change after a subsequent estimated simulation fill is recorded. Viewing indicators or switching tabs does not submit orders.',
  '查看四只 ETF 的完整持仓依据':'View full holding rationale for all four ETFs',
  '正在核对当前状态；以下为最近一次快照，实际占比暂不展示。':'The current state is being checked. This is the latest saved snapshot; actual weights are temporarily hidden.',
  '当前状态待核对，以下持仓逻辑来自上次成功快照。':'The current state needs verification. The rationale below is from the last successful snapshot.'
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '是':'Yes',
  '否':'No',
  '保存时序已核对':'Saved timing verified',
  '保存时序无效，待核对':'Invalid saved timing; verification required',
  '保存时序未完整记录':'Saved timing is incomplete',
  '时序核对':'Timing verification',
  '日线指标日期':'Daily indicator date',
  '原策略状态日':'Original strategy state date',
  '指标周期截至':'Indicator period ending',
  '该周期首次可知日':'Period first known on',
  '① 先看原策略筛选':'1. Original strategy eligibility comes first',
  '原策略筛选决定是否具备多头资格；下方动量与波动用于通过资格后的 D0 权重分配。':'The original strategy determines bullish eligibility. Momentum and volatility below determine D0 weights after eligibility checks.',
  '此信号未保存可识别的原策略指标；不使用当前行情补算历史依据。':'This signal has no recognized saved original-strategy indicators. Current prices are not used to reconstruct historical evidence.',
  '部分原策略记录的日期缺失、冲突或晚于信号确认日；仅展示时序已核对的部分，不能视为完整确认。':'Some original-strategy dates are missing, inconsistent or later than the signal confirmation day. Only timing-verified portions are displayed; this is not complete confirmation.',
  '已保存原策略多头：是':'Saved original bullish state: yes',
  '已保存原策略多头：否':'Saved original bullish state: no',
  '原策略指标已就绪':'Original indicators ready',
  '原策略指标尚未就绪':'Original indicators not ready',
  '原策略多头未记录':'Original bullish state not recorded',
  '原策略就绪状态未记录':'Original indicator readiness not recorded',
  '周线 SKDJ：K 与 D':'Weekly SKDJ: K and D',
  '日线 SKDJ：K 与 D':'Daily SKDJ: K and D',
  'K值':'K',
  'D值':'D',
  'K、D 共用0–100刻度。即使 K 高于 D，也不能仅凭两线当前位置认定发生了新的金叉。':'K and D share a 0–100 scale. Even when K is above D, their current levels alone do not establish a new bullish crossover.',
  '周线 TRIX 与信号线（%）':'Weekly TRIX and signal line (%)',
  'TRIX信号线':'TRIX signal line',
  '横线标出零值；TRIX 直接显示原始百分点，不额外乘以100。两线的位置比较不代表刚刚发生交叉。':'The horizontal line marks zero. TRIX uses its original percentage-point values, without multiplying by 100. Comparing the two levels does not establish a new crossover.',
  '周线趋势：指标价与50周均线':'Weekly trend: indicator price and 50-week average',
  '原策略周收盘指标价':'Original weekly closing indicator price',
  '50周均线':'50-week moving average',
  '此处使用原策略保存的周线价格口径；50周趋势记录与 SKDJ、TRIX 的周期分别核对。':'These are the original strategy’s saved weekly price values. The 50-week trend dates and SKDJ/TRIX dates are verified separately.',
  '原策略保存的状态':'Saved original-strategy state',
  '周线市场状态':'Weekly market state',
  '牛市':'Bull market',
  '熊市':'Bear market',
  '预热中':'Warming up',
  '价格保护阻断':'Price-protection block',
  '已阻断':'Blocked',
  '未阻断':'Not blocked',
  '保存的当日条件与参考状态':'Saved daily conditions and reference state',
  '当日入场条件':'Daily entry condition',
  '当日指标退出条件':'Daily indicator exit condition',
  '已触发':'Triggered',
  '未触发':'Not triggered',
  '原策略正向条件':'Original positive condition',
  '成立':'Met',
  '不成立':'Not met',
  '入场条件未触发，仍可能延续原策略持仓；指标退出条件也不涵盖持有期等全部退出规则。':'An untriggered entry condition can coexist with a continuing original-strategy position. Indicator exit conditions do not cover every exit rule, such as holding duration.',
  '银行原入场条件包含前日 K≤D、当日 K>D 且 K≤40；当日指标退出条件包含 K≥70 或 K≤D。这里显示保存的条件结果，不用当前 K、D 重新判定。':'The bank strategy’s entry condition includes prior-day K≤D, current K>D and K≤40. Its daily indicator exit condition includes K≥70 or K≤D. Saved condition results are shown without re-evaluating current K and D.',
  '60日均线':'60-day moving average',
  '120日均线':'120-day moving average',
  '均线（窗口未记录）':'Moving average (window not recorded)',
  '含息收益指数与均线':'Total-return index and moving average',
  '含息收益指数':'Total-return index',
  '数值是含息收益指数及其均线，单位为指数点，不是 ETF 的交易价格。':'Values are total-return index levels and their moving average, in index points rather than ETF trading prices.',
  '原策略动量条件':'Original momentum condition',
  '原策略保存的多头':'Saved original bullish state',
  '原策略要求资料就绪、含息收益指数高于对应均线且20日动量大于0；是否多头读取保存结果。':'The original strategy requires ready data, the total-return index above its corresponding average and positive 20-day momentum. The bullish result is read from the saved signal.',
  '原策略下一期参考仓位':'Original strategy’s next-period reference weight',
  '原策略已持有交易日':'Original strategy’s trading days held',
  '原策略参考仓位和持有天数不等于 D0 模型目标，也不等于本账户实际持仓。':'The original strategy’s reference weight and holding duration are distinct from D0 targets and this account’s actual holdings.',
  '② 再看 D0 权重评分':'2. Then examine D0 weight scoring',
  '强弱：20日与60日动量':'Strength: 20-day and 60-day momentum',
  '波动：实际指标与计算下限':'Volatility: observed value and calculation floor'
});


window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '曲线来自该确认信号对应的历史行情指标，不代表逐日保存的交易决定。':'These curves show historical market indicators for this confirmed signal, not trading decisions saved on each past date.',
  '信号保存的确认值':'Confirmed values saved with the signal',
  '历史指标暂不可用；只展示信号保存的确认值，不补造趋势。':'Historical indicators are unavailable. Only confirmed values saved with the signal are shown; no trend is invented.',
  '历史显示范围':'History display range',
  '{count}周':'{count} weeks',
  '{count}日':'{count} days',
  '周线 · {count} 个观测日':'Weekly · {count} observation dates',
  '日线 · {count} 个观测日':'Daily · {count} observation dates',
  '竖虚线：信号确认日 {day}':'Vertical dashed line: signal confirmation day {day}',
  '只有一个历史观测点，不构成趋势。':'A single historical observation does not establish a trend.',
  '查看日期（方向键切换，Home / End 到首尾）':'Inspect a date (arrow keys; Home / End for first / last)',
  '可知日期':'First-known date',
  '连续性':'Continuity',
  '此前存在数据缺口；曲线已断开':'A data gap precedes this point; the line is broken',
  '查看历史数据表':'View historical data table',
  '历史行情指标':'Historical market indicators',
  '缺口后首点':'First point after gap',
  '—':'—',
  '横轴按真实可知日期间距排列；缺失值保留空档，不插值、不推算买卖点。':'The horizontal axis uses actual first-known date spacing. Missing values leave gaps; no interpolation or buy/sell signals are inferred.',
  '横线标出零值。动量为正，不等于通过配置资格。':'The horizontal line marks zero. Positive momentum alone does not establish allocation eligibility.',
  '横虚线：8% 评分计算下限':'Horizontal dashed line: 8% scoring floor'
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,'此范围内缺少有效指标值，可切换范围或查看数据表。':'No valid indicator values exist in this range. Choose a wider range or inspect the data table.'});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '价格与涨跌幅':'Price and change',
  '最近市场价（元）':'Latest market price (CNY)',
  '行情源昨收（元）':'Source previous close (CNY)',
  '较昨收涨跌幅':'Change from previous close',
  '当前状态待核对；价格与曲线来自上次成功快照，不能视为实时。':'The current state needs verification. Prices and charts are from the last successful snapshot and must not be treated as live.',
  '本次快照报价近期采集 · 仅供查看':'Quote recently collected in this snapshot · display only',
  '报价已过期、尚未采集或时间待核对；不能视为实时。':'The quote is stale, missing or has an unverified timestamp. It must not be treated as live.',
  '行情源时间':'Source quote time',
  '采集接收时间':'Collection receipt time',
  '行情来源':'Quote source',
  '价格曲线类型':'Price chart type',
  '盘中采样':'Intraday samples',
  '历史日线':'Daily history',
  '本系统采样记录，不是交易所完整分时。横轴为行情源时间；两张图共用选点，价格与涨跌幅分别使用各自刻度。':'These are samples recorded by this system, not a complete exchange intraday feed. The horizontal axis uses source quote times. Both charts share the selected point, with separate price and percentage scales.',
  '未复权收盘价；每日涨跌幅按前一交易日收盘价计算，不含分红，也不采用历史除权参考昨收。缺少前一交易日时涨跌幅留空，参考列保留上一条实际记录。两张图共用日期，分别使用各自刻度。':'Unadjusted closing prices. Daily changes compare with the preceding trading day’s close, excluding dividends and historical ex-rights reference closes. If the preceding trading day is missing, the change is blank and reference columns retain the preceding recorded observation. Both charts share the selected date and use separate scales.',
  '最近报价日 {day}':'Most recent quote day {day}',
  '已确认日线截至 {day}':'Confirmed daily prices through {day}',
  '仅保留最近采样，报价日的覆盖不完整。':'Only recent samples are retained. Coverage of this quote day is incomplete.',
  '仅展示最近一段历史，所列范围不代表全部上市历史。':'Only recent history is displayed, not the entire listing history.',
  '此范围内没有可核对的数值；缺失值不会当作零。':'No verified values exist in this range. Missing values are not treated as zero.',
  '价格曲线资料待核对，暂不绘制。':'Price chart data needs verification and is not plotted.',
  '尚无已保存的盘中采样；等待正常行情采集，不补造分时线。':'No saved intraday samples yet. Waiting for normal collection; no intraday line is invented.',
  '尚无与确认信号一致的日线价格记录，暂不绘制。':'No daily price records match the confirmed signal yet. No chart is plotted.',
  '{count} 个已记录观测点':'{count} recorded observations',
  '收盘日期':'Closing date',
  '市场价（元）':'Market price (CNY)',
  '未复权收盘价（元）':'Unadjusted close (CNY)',
  '上一记录收盘价（元）':'Previous recorded close (CNY)',
  '上一记录日':'Previous recorded date',
  '每日涨跌幅':'Daily change',
  '市场价格（元）':'Market price (CNY)',
  '每日收盘价（元，未复权）':'Daily close (CNY, unadjusted)',
  '较行情源昨收涨跌幅（%）':'Change from source previous close (%)',
  '每日涨跌幅（%）':'Daily change (%)',
  '缺失值和采集间断保留空档；不插值。行情变化用于查看，不会直接生成 D0 信号或改变实际持仓。':'Missing values and collection gaps remain unconnected, without interpolation. Market changes are for viewing; they do not directly create D0 signals or change actual holdings.',
  '查看价格与涨跌幅数据表':'View price and change table',
  '价格与涨跌幅数据表':'Price and change table',
  '已记录的盘中价格与涨跌幅':'Recorded intraday prices and changes',
  '已确认的每日收盘价与涨跌幅':'Confirmed daily closing prices and changes'
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '此处采样不连续；曲线已断开':'Samples are discontinuous here; the line is broken',
  '分段首点':'First point of segment'
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '部分采样无效，已跳过并断开曲线。':'Some samples are invalid. They were skipped and the line is broken.',
  '采集状态记录不完整，曲线按独立采样展示。':'Collection-state records are incomplete. Recorded samples are shown separately.',
  '最近报价采集失败，等待下一次正常采集。':'The latest quote collection failed. Waiting for the next successful collection.'
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '账户当前盈亏':'Current account profit / loss',
  '从账户本金起累计，非今日盈亏；与本账户总资产估值使用同一份报价。':'Cumulative since the account’s starting capital, not today’s profit / loss. Uses the same quotes as this account’s total asset valuation.',
  '当前累计盈亏':'Current cumulative profit / loss',
  '累计收益率':'Cumulative return',
  '已实现盈亏':'Realized profit / loss',
  '持仓浮动盈亏':'Unrealized holding profit / loss',
  '已付模拟费用':'Simulation fees paid',
  '盈利':'Profit',
  '亏损':'Loss',
  '持平':'Unchanged',
  '缓存估值 · 状态待刷新：以下金额来自上次成功快照，不能视为当前最新盈亏。':'Cached valuation · refresh pending: the amounts below are from the last successful snapshot and are not current profit / loss.',
  '估值已过期；以上为保留报价下的累计盈亏估算。':'The valuation is stale. The figures above estimate cumulative profit / loss using retained quotes.',
  '盈亏资料不完整；无法核对的项目显示 —。':'Profit / loss data is incomplete. Items that cannot be verified are shown as —.',
  '无持仓；盈亏按本账户现金余额核算。':'There are no holdings. Profit / loss is based on this account’s cash balance.',
  '按账户已接纳报价估算；市场报价更新不会直接改写此处盈亏。':'Estimated using quotes accepted by this account. New market quotes do not directly change these figures.',
  '部分持仓缺少估值报价，累计及浮动盈亏暂不可用。':'Some holdings lack valuation quotes. Total and unrealized profit / loss are temporarily unavailable.',
  '持仓成本记录不完整，部分盈亏待核对。':'Holding cost records are incomplete. Some profit / loss figures need verification.',
  '账户金额记录待核对。':'Account amount records need verification.',
  '账户估值与持仓记录不一致，部分盈亏暂不可用。':'Account valuation and holding records do not agree. Some profit / loss figures are unavailable.',
  '已付费用记录待核对。':'Paid fee records need verification.',
  '估值源时间未完整记录，请先核对。':'Valuation quote times are incomplete and need verification.',
  '账户快照时间：{time}':'Account snapshot time: {time}',
  '估值引用源时间：{first} 至 {last}':'Valuation source times: {first} to {last}',
  '估值引用源时间：{time}':'Valuation source time: {time}',
  '已付模拟费用已计入盈亏，不再重复扣除；冻结现金仍包含在账户资产中。':'Paid simulation fees are already included in profit / loss and are not deducted again. Frozen cash remains part of account assets.',
  '正在读取采样，请稍候。':'Reading recorded samples. Please wait.'
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '账户盈亏（缓存估值）':'Account profit / loss (cached valuation)',
  '累计盈亏（缓存）':'Cumulative profit / loss (cached)'
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '账户盈亏走势':'Account profit / loss history',
  '每日盈亏与累计盈亏来自本账户每天最后一次有效估值记录，不是收盘结算。费用已包含，不重复扣除。':'Daily and cumulative profit / loss use this account’s last valid recorded valuation for each day, not an official closing valuation. Fees are already included and are not deducted again.',
  '历史快照待刷新：当前展示上次读取的记录，不能据此认定最新账户状态。':'History refresh pending: the displayed records are from the last read and do not establish the latest account state.',
  '盈亏记录显示范围':'Profit / loss record range',
  '最近{count}条记录':'Latest {count} records',
  '当前显示 {count} 条记录':'Showing {count} records',
  '历史记录待核对，暂不绘制盈亏曲线。':'Historical records need verification. Profit / loss charts are not plotted.',
  '暂时无法读取账户盈亏历史，请等待正常刷新。':'Account profit / loss history is temporarily unavailable. Waiting for the next normal refresh.',
  '尚无账户盈亏历史；等待后续有效估值积累，不补造过去记录。':'No account profit / loss history yet. Waiting for valid valuations to accumulate; past records are not invented.',
  '历史最多保留366条记录；当前曲线只显示所选范围，不代表全部账户历史。':'Up to 366 historical records are retained. Charts show the selected range, not necessarily the account’s entire history.',
  '每日盈亏按同一本金基准内连续交易日的已记录估值比较；缺日或本金变更时留空。横轴按实际日期排列，同日本金变更可有多条记录。':'Daily profit / loss compares recorded valuations on consecutive trading days within the same capital basis. Missing days or a capital change leave a blank. The horizontal axis uses actual dates; capital changes can produce multiple records on one date.',
  '查看记录（方向键切换，Home / End 到首尾）':'Inspect a record (arrow keys; Home / End for first / last)',
  '当日暂估':'Provisional daily estimate',
  '当日最后记录（非收盘）':'Last recorded for the day (not the close)',
  '记录日期':'Record date',
  '记录状态':'Record status',
  '每日盈亏':'Daily profit / loss',
  '累计盈亏':'Cumulative profit / loss',
  '每日比较基准日':'Daily comparison baseline date',
  '尚无连续可比记录':'No consecutive comparable record yet',
  '该段本金基准':'Capital basis for this segment',
  '记录时账户估值':'Recorded account valuation',
  '观察记录时间':'Observation recorded at',
  '估值引用源时间':'Valuation source time',
  '现金账户，无持仓报价':'Cash-only account; no holding quote',
  '最新持仓报价源时间':'Latest holding quote source time',
  '本金基准变化':'Capital basis changed',
  '与上一段分开记录；不跨本金基准计算每日盈亏。':'Recorded separately from the preceding segment. Daily profit / loss is not calculated across capital bases.',
  '本条之前不连接曲线，未补算缺失记录。':'The line is disconnected before this record. Missing records are not reconstructed.',
  '每日盈亏（元）':'Daily profit / loss (CNY)',
  '累计盈亏（元）':'Cumulative profit / loss (CNY)',
  '横线为零；空心点为当日暂估。所有点都是已记录观测，不表示收盘结算；缺口与本金段之间不连线。':'The horizontal line marks zero; hollow points are provisional daily estimates. All points are recorded observations, not closing valuations. Gaps and capital segments are not connected.',
  '目前只有一条账户记录，只显示观测点；需要后续记录才能形成曲线。':'Only one account record exists, so only a point is shown. Later records are needed to form a line.',
  '查看账户盈亏数据表':'View account profit / loss table',
  '账户每日有效估值记录；每日及累计盈亏均已包含模拟费用。':'Recorded daily account valuations. Daily and cumulative profit / loss already include simulation fees.',
  '账户盈亏数据表':'Account profit / loss table',
  '尚无连续可比记录；每日盈亏保持空白，不按零处理。':'No consecutive comparable records yet. Daily profit / loss remains blank and is not treated as zero.'
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,'最近账户记录：{time}':'Latest account record: {time}'});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  "盈亏走势周期":"Profit / loss chart period",
  "盘中":"Intraday",
  "每日":"Daily",
  "盘中按分钟保存本账户的有效估值，随账户更新；每日保留每天最后一条有效记录。费用已包含。":"Intraday records save valid account valuations by minute as the account updates. Daily mode keeps the last valid record each day. Fees are included.",
  "{date} 北京时间 · 已记录 {count} 个盘中点":"{date} Beijing time · {count} intraday points recorded",
  "今天尚无有效盘中记录；开市后随账户有效估值积累。历史日线可切换到“每日”查看。":"No valid intraday record for today yet. Records accumulate from valid account valuations during market hours. Switch to Daily for the daily history.",
  "此前最近盘中记录：{time}，未作为今天的数据展示。":"Latest earlier intraday record: {time}. It is not displayed as today’s data.",
  "从今日首条记录起变化":"Change since today’s first record",
  "今日盈亏":"Today’s profit / loss",
  "从今日首条记录起变化（元）":"Change since today’s first record (CNY)",
  "今日盈亏（元）":"Today’s profit / loss (CNY)",
  "盘中暂估":"Intraday estimate",
  "已记录估值（非收盘）":"Recorded valuation (not the close)",
  "缺少可比的上一交易日估值；左图显示各本金段从今日首条真实记录起的变化，不等于完整今日盈亏。":"A comparable previous trading day valuation is missing. The left chart shows changes since today’s first actual record within each capital segment, not the full day’s profit / loss.",
  "今日盈亏以同一本金基准的上一交易日最后有效记录为基准；累计盈亏相对该段初始本金。":"Today’s profit / loss compares with the previous trading day’s last valid record on the same capital basis. Cumulative profit / loss is relative to that segment’s initial capital.",
  "当前本金段首条记录：{time}，当时累计盈亏 {value}。":"First record in the current capital segment: {time}, with cumulative profit / loss of {value}.",
  "盘中历史已达到保存上限；未展示的早期记录不会补造。":"The intraday retention limit has been reached. Earlier records that are not shown are not invented.",
  "该段今日首条记录":"Today’s first record in this segment",
  "首条记录累计盈亏":"Cumulative profit / loss at the first record",
  "横轴为北京时间，横线为零；午休、采集间断与本金变化处分段，不补算过去数据。最新空心点为盘中暂估。":"The horizontal axis uses Beijing time and the horizontal line marks zero. Lunch breaks, collection gaps and capital changes are disconnected; past data is not reconstructed. A hollow latest point is an intraday estimate.",
  "目前只有一个盘中点；后续有效估值会逐分钟形成折线，同一分钟更新已有点。":"There is one intraday point so far. Later valid valuations will form a line minute by minute; updates in the same minute refresh the existing point.",
  "账户盘中有效估值记录；每分钟保留最新有效观测，盈亏已包含模拟费用。":"Valid intraday account valuations. The latest valid observation is retained for each minute; profit / loss includes simulation fees."
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  "已略去 {count} 条休市、盘前或盘后采样；曲线仅显示交易时段，最新报价卡仍按原始时间展示。":"Omitted {count} samples from lunch breaks or outside trading hours. The chart shows trading hours only; the latest quote card keeps its original timestamp.",
  "本系统采样记录，不是交易所完整分时。横轴已压缩午休；读数保留真实行情源时间，两张图共用选点。":"System-recorded samples, not a complete exchange tape. Lunch is compressed on the axis; readouts retain actual source times and both charts share the selected point.",
  "现有采样均在非交易时段，暂不绘制；等待交易时段的有效行情。":"All recorded samples are outside trading hours. Waiting for valid trading-hour quotes before drawing the chart.",
  "横轴按北京时间压缩午休，读数保留真实记录时间；采集间断与本金变化仍断线。横线为零，最新空心点为盘中暂估。":"The Beijing-time axis compresses lunch; readouts retain actual observation times. Collection gaps and capital changes remain disconnected. The horizontal line marks zero; a hollow latest point is an intraday estimate."
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,...{
  "D0 策略信号": "D0 strategy signal",
  "查看当前账户的确认目标、计划动作和执行进度。": "Confirmed targets, planned actions and execution progress for this account.",
  "当前快照尚无策略信号摘要，请刷新状态。": "The current snapshot has no strategy signal summary yet. Refresh the status.",
  "策略信号摘要与账户记录未通过核对，暂不展示买卖方向。": "The signal summary could not be verified against this account. Buy and sell directions are not shown.",
  "计划动作": "Planned action",
  "已保存的计划": "Saved plan",
  "计划增持": "Planned increase",
  "计划减持": "Planned reduction",
  "计划调仓": "Planned rebalance",
  "按计划持有": "Hold under the plan",
  "按计划空仓": "Remain uninvested under the plan",
  "等待计划确认": "Waiting for a confirmed plan",
  "当前状态待核对": "Current status needs verification",
  "执行进度": "Execution progress",
  "条件已就绪": "Snapshot conditions ready",
  "等待执行条件": "Waiting for execution conditions",
  "账户已暂停或停止": "Account paused or stopped",
  "需要核对": "Needs verification",
  "等待刷新确认": "Waiting for refresh and verification",
  "当前状态正在读取或尚未核对；以下仅保留上次确认目标，买卖方向暂不展示。": "The current status is loading or unverified. Only the last confirmed targets are retained below; buy and sell directions are not shown.",
  "信号确认日": "Signal confirmation date",
  "账户快照时间": "Account snapshot time",
  "确认目标比例": "Confirmed target weight",
  "实际份额": "Actual units",
  "计划目标份额": "Planned target units",
  "尚未确认": "Not yet confirmed",
  "资料尚未就绪，等待更新": "Source data is not ready; waiting for an update",
  "当前快照条件已核对，成交以委托记录为准。": "Conditions have been checked in this snapshot. Execution is determined by the recorded orders.",
  "账户已暂停或停止，保留已保存的信号与计划。": "The account is paused or stopped. Its saved signal and plan are retained.",
  "尚无确认信号，等待收盘资料。": "No confirmed signal yet; waiting for closing data.",
  "信号资料待核对，暂不展示计划动作。": "Signal data needs verification. Planned actions are not shown.",
  "目标已确认，等待建立执行计划。": "The target is confirmed; waiting for an execution plan.",
  "已保存计划不属于当前信号或运行轮次，等待新计划。": "The saved plan belongs to another signal or activation. Waiting for a new plan.",
  "执行计划资料待核对，暂不展示计划动作。": "Execution-plan data needs verification. Planned actions are not shown.",
  "实际份额资料待核对，暂不展示计划动作。": "Actual position data needs verification. Planned actions are not shown.",
  "委托关联资料待核对，暂不展示计划动作。": "Order associations need verification. Planned actions are not shown.",
  "操作后的状态仍待下一次账户读取核对。": "The post-operation state awaits verification on the next account read.",
  "尚未到达计划最早执行时间。": "The plan's earliest execution time has not arrived.",
  "当前不在模拟连续竞价窗口，等待下个交易时段。": "Outside the simulation's continuous trading window; waiting for the next session.",
  "后台观察尚未就绪，等待状态恢复。": "The background observer is not ready; waiting for recovery.",
  "账户资料待核对。": "Account data needs verification.",
  "本轮委托已结束，剩余计划差额不会自动重试。": "This activation's order has ended. The remaining planned difference will not be retried automatically.",
  "尚无当前执行计划": "No current execution plan",
  "计划或记录待核对": "Plan or records need verification",
  "已有模拟委托，等待满足成交条件": "A simulated order exists; waiting for execution conditions",
  "实际份额已达到计划目标": "Actual units have reached the planned target",
  "仍有计划差额，尚未提交委托": "A planned difference remains; no order has been submitted",
  "先卖后买，等待卖出步骤": "Sell before buying; waiting for the sell step",
  "可卖份额不足，等待规则允许": "Insufficient sellable units; waiting until rules permit",
  "委托状态：{status}": "Order status: {status}",
  "已结束": "Ended",
  "已提交{side}委托：{quantity}份": "Submitted {side} order: {quantity} units",
  "触发依据与指标": "Trigger evidence and indicators",
  "评分资料": "Scoring data",
  "尚未就绪": "Not ready",
  "已保存有效评分": "Saved effective score",
  "未保存具体触发说明，可查看已有指标依据。": "No specific trigger explanation was saved. Review the available indicator evidence.",
  "查看此 ETF 的指标曲线": "View this ETF's indicator charts",
  "查看{asset}的指标曲线": "View indicator charts for {asset}",
  "最近一笔已记录模拟成交": "Latest recorded simulated fill",
  " · 历史信号或计划的成交记录": " · Fill from a historical signal or plan",
  "暂无可核对的最近成交摘要，可在成交明细中查看记录。": "No verifiable latest-fill summary is available. Review the fill details for recorded transactions.",
  "计划动作根据已保存的目标份额显示；新信号先改变目标，实际持仓在模拟成交记账后更新。盘中行情用于估值，不直接生成新的策略信号。": "Planned actions reflect saved target units. New signals change the target first; actual holdings update after a simulated fill is recorded. Intraday quotes support valuation and do not directly create new strategy signals."
}});

window.ETF_EN=Object.freeze({...window.ETF_EN,
  "在此设备保持登录":"Keep me signed in on this device",
  "首次登录后，服务重启也保持登录。":"After the first sign-in, you stay signed in through service restarts.",
  "180天有效并自动续期；退出登录或清除浏览器数据后需重新登录。":"Valid for 180 days with automatic renewal. Signing out or clearing browser data requires signing in again.",
  "共用设备请取消勾选。":"Uncheck this option on shared devices.",
  "设备登录状态暂不可用，请稍后重试":"Device sign-in is temporarily unavailable. Please try again later.",
  "无法保存设备登录状态，请稍后重试":"Unable to save device sign-in. Please try again later.",
  "记住设备选项必须为布尔值":"The remember-device option must be true or false.",
  "无法撤销设备登录状态，请稍后重试":"Unable to revoke device sign-in. Please try again later."
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,...{
  "当前策略解读": "Current strategy interpretation",
  "文字解读资料尚未就绪，等待正常刷新。": "Data for the written interpretation is not ready. Waiting for a normal refresh.",
  "依据 {day} 已确认信号；以下说明不随盘中报价变化。": "Based on the confirmed signal dated {day}; the following interpretation does not change with intraday quotes.",
  "当前展示上次成功快照的指标解读，等待状态刷新。": "Showing the indicator interpretation from the last successful snapshot while waiting for a status refresh.",
  "指标解读资料待核对。": "Indicator interpretation data needs verification.",
  "信号线": "Signal line",
  "周线 SKDJ 解读": "Weekly SKDJ interpretation",
  "日线 SKDJ 解读": "Daily SKDJ interpretation",
  "周线 TRIX 解读": "Weekly TRIX interpretation",
  "本期指标数值或时序资料不足，暂不判断两线关系。": "Current indicator values or timing evidence are incomplete. The relationship between the two lines cannot be determined.",
  "{left_name}={left}，{right_name}={right}。": "{left_name}={left}, {right_name}={right}.",
  "{left_name}在{right_name}上方，当前为上方排列。": "{left_name} is currently above {right_name}.",
  "{left_name}在{right_name}下方，当前为下方排列。": "{left_name} is currently below {right_name}.",
  "{left_name}与{right_name}当前相等，尚未形成新的交叉。": "{left_name} and {right_name} are currently equal; no new crossover has formed.",
  "显示值经过舍入，两线关系按原始精度比较。": "Displayed values are rounded. The line relationship is compared at the original precision.",
  "指标周期截至 {day}；可知日 {available}。": "Indicator period ended {day}; the observation became available on {available}.",
  "缺少可连续比较的前值，暂不判断交叉或靠拢方向。": "A comparable preceding observation is unavailable. A crossover or direction of convergence cannot be determined.",
  "从 {before} 到 {after}，{left_name}由不高于{right_name}转为高于（金叉）；这是两次观测之间的变化。": "Between {before} and {after}, {left_name} moved from at or below {right_name} to above it (upward crossover); this describes the change between the two observations.",
  "从 {before} 到 {after}，{left_name}由不低于{right_name}转为低于（死叉）；这是两次观测之间的变化。": "Between {before} and {after}, {left_name} moved from at or above {right_name} to below it (downward crossover); this describes the change between the two observations.",
  "从 {before} 到 {after}，差距由 {before_gap} 缩小至 {after_gap}；正在向金叉方向靠拢，本次观测尚未上穿。": "Between {before} and {after}, the gap narrowed from {before_gap} to {after_gap}; the lines converged toward an upward crossover, but the current observation remains below.",
  "从 {before} 到 {after}，差距由 {before_gap} 缩小至 {after_gap}；正在向死叉方向靠拢，本次观测尚未下穿。": "Between {before} and {after}, the gap narrowed from {before_gap} to {after_gap}; the lines converged toward a downward crossover, but the current observation remains above.",
  "从 {before} 到 {after}，上方差距由 {before_gap} 扩大至 {after_gap}。": "Between {before} and {after}, the gap above the other line widened from {before_gap} to {after_gap}.",
  "从 {before} 到 {after}，下方差距由 {before_gap} 扩大至 {after_gap}。": "Between {before} and {after}, the gap below the other line widened from {before_gap} to {after_gap}.",
  "从 {before} 到 {after}，两线差值未变。": "Between {before} and {after}, the difference between the two lines was unchanged.",
  "趋势与均线解读": "Trend and moving-average interpretation",
  "原策略周收盘指标价 {value}，{window}周均线 {ma}。": "Original-strategy weekly closing indicator price: {value}; {window}-week moving average: {ma}.",
  "含息收益指数 {value}，{window}日均线 {ma}。": "Total-return index: {value}; {window}-day moving average: {ma}.",
  "指标值高于均线，当前处于均线上方。": "The indicator value is currently above its moving average.",
  "指标值低于均线，当前处于均线下方。": "The indicator value is currently below its moving average.",
  "指标值等于均线，尚未满足严格高于均线的条件。": "The indicator equals its moving average; the strict above-average condition is not met.",
  "均线数值、窗口或时序资料不足，暂不判断趋势位置。": "Moving-average values, the lookback window or timing evidence are incomplete. Trend position cannot be determined.",
  "动量与波动解读": "Momentum and volatility interpretation",
  "20日动量 {short}，60日动量 {medium}。": "20-day momentum: {short}; 60-day momentum: {medium}.",
  "动量资料不完整，暂不比较短中期强弱。": "Momentum data is incomplete. Short- and medium-term strength cannot be compared.",
  "两项动量均为正，短中期累计收益均为正。": "Both momentum measures are positive; cumulative returns over both lookbacks are positive.",
  "两项动量均为负，短中期累计收益均为负。": "Both momentum measures are negative; cumulative returns over both lookbacks are negative.",
  "两项动量一正一负，短中期表现分化。": "One momentum measure is positive and the other is negative; the two lookbacks show diverging performance.",
  "至少一项动量为零，需结合其他条件观察。": "At least one momentum measure is zero; consider it alongside the other conditions.",
  "20日年化波动 {value}，低于8%下限；评分分母按8%计算。": "20-day annualized volatility is {value}, below the 8% floor; the score denominator uses 8%.",
  "20日年化波动 {value}；评分分母按实测波动计算。": "20-day annualized volatility is {value}; the score denominator uses the measured volatility.",
  "波动率资料不足，暂不解释风险调整。": "Volatility data is incomplete. The risk adjustment cannot be interpreted.",
  "对当前策略的意义": "Meaning for the current strategy",
  "该资产仅使用日线SKDJ，未使用TRIX。": "This asset uses daily SKDJ only; it does not use TRIX.",
  "原策略保存的入场条件：{entry}；退出条件：{exit}。": "Saved original-strategy entry condition: {entry}; exit condition: {exit}.",
  "SKDJ、TRIX与50周趋势参与准入；持有期限和回撤保护也会影响原策略状态。": "SKDJ, TRIX and the 50-week trend contribute to eligibility; holding-period limits and drawdown protection also affect the original strategy state.",
  "该资产使用均线与20日动量筛选，未使用SKDJ或TRIX。": "This asset uses its moving average and 20-day momentum for screening; it does not use SKDJ or TRIX.",
  "原策略保存的多头状态：{status}。": "Saved original-strategy bullish state: {status}.",
  "D0配置资格：{status}；已保存模型目标 {weight}，有效评分 {score}。": "D0 allocation eligibility: {status}; saved model target: {weight}; effective score: {score}.",
  "通过": "Passed",
  "未通过": "Not passed",
  "靠拢描述只反映两次已确认观测的差值变化，不预测下一周期交叉，也不会生成交易指令。": "Convergence describes only the change in the gap between two confirmed observations. It does not predict a crossover in the next period or generate a trading instruction."
}});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  '原策略20日动量 {value}，满足大于0的筛选条件。':'Original-strategy 20-day momentum is {value}, satisfying the greater-than-zero screening condition.',
  '原策略20日动量 {value}，未满足大于0的筛选条件。':'Original-strategy 20-day momentum is {value}, failing the greater-than-zero screening condition.',
  '原策略20日动量未记录，暂不判断此项筛选条件。':'Original-strategy 20-day momentum was not recorded; this screening condition cannot be determined.'
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,...{
  "什么时候买入、什么时候退出": "When to buy and when to exit",
  "原策略如何允许持有": "How the original strategy permits a reference holding",
  "原策略何时退出或取消资格": "When the original strategy exits or loses eligibility",
  "创业板：已完成周线 SKDJ(3,5) 的K>D，且 TRIX(4,8)>信号线，用于建立或恢复原策略进攻仓位。D0还要求50周牛市状态、原策略保持完整进攻仓位，以及指标资料就绪。": "ChiNext: completed weekly SKDJ(3,5) K>D and TRIX(4,8) above its signal line are used to establish or restore the original strategy's reference exposure. D0 also requires a bullish 50-week market state, full original-strategy reference exposure and ready indicator data.",
  "创业板采用双多头状态，持续满足也可参与；每次D0增配无需重新出现一笔金叉。价格保护退出后，要先等双多头失效解除阻断，再等后续双多头恢复。": "ChiNext uses the combined bullish state; an ongoing qualifying state can also participate, so a new upward crossover is not required for every D0 increase. After a price-protection exit, the combined bullish condition must first fail to clear the block, then return in a later confirmed period.",
  "原策略参考持仓达到20个交易日退出；50周趋势转弱或原策略不再保持完整进攻仓位时，D0目标变为0%。单次SKDJ或TRIX死叉本身不会立即退出已有原策略仓位。": "The original reference holding exits after 20 trading days. D0 targets 0% when the 50-week trend weakens or the original strategy no longer has full reference exposure. A single SKDJ or TRIX downward crossover alone does not immediately exit an existing original-strategy holding.",
  "回撤保护：原策略参考持仓先从入场价上涨至少15%，再按日收盘相对峰值回撤达到8%时减半、12%时退出并阻断。原策略减半会使D0失去完整进攻资格，D0目标为0%，并非跟着减半。": "Drawdown protection: after the original reference holding first gains at least 15% from its entry price, a daily-close drawdown from its peak of 8% halves that reference exposure; 12% exits and blocks re-entry. Halving the original reference exposure removes D0's full-exposure eligibility, so D0 targets 0% rather than halving its own allocation.",
  "银行：日线 SKDJ(9,5) 前一周期K≤D，本期K>D形成向上金叉，且本期K≤40；指标就绪、原策略参考空仓且允许入场时，新建参考仓位。银行未使用TRIX。": "Bank: daily SKDJ(9,5) must move from K≤D in the preceding period to K>D in the current period, with current K≤40. A new reference holding is established when indicators are ready, the original reference is flat and entry is permitted. This asset does not use TRIX.",
  "原策略已有有效多头时，D0可以按目标增配；本期没有新金叉或K已高于40，都不单独表示必须退出。": "When the original strategy already has a valid bullish holding, D0 can increase exposure toward its target. The absence of a new upward crossover or K rising above 40 does not by itself require an exit.",
  "原策略持仓时，K≥70、K≤D（包括死叉或相等），或参考持有达到20个交易日，会触发退出；D0随原策略多头资格失效取消配置。": "While the original reference is holding, K≥70, K≤D (including a downward crossover or equality), or reaching 20 trading days of reference holding triggers an exit. D0 removes the allocation when the original bullish eligibility is lost.",
  "{window}日均线规则：已确认的含息收益指数严格高于{window}日均线，且原策略20日动量大于0、指标就绪，才允许配置。": "{window}-day moving-average rule: allocation is permitted only when the confirmed total-return index is strictly above its {window}-day moving average, original-strategy 20-day momentum is greater than 0 and indicators are ready.",
  "含息收益指数回落至均线或下方、原策略20日动量不再大于0，或指标资料未就绪时，取消该资产配置资格，目标为0%。": "If the total-return index falls to or below the moving average, original-strategy 20-day momentum is no longer greater than 0, or indicators are not ready, the asset loses allocation eligibility and its target is 0%.",
  "逐项查看本次条件": "Review the current conditions individually",
  "满足": "Met",
  "未满足": "Not met",
  "以下观察用于理解原策略的建仓与持有条件；已有仓位可以延续，最终配置资格读取已保存结果。": "These observations explain the original strategy's entry and holding conditions. An existing reference holding may continue; final allocation eligibility is read from the saved result.",
  "周线SKDJ：K>D": "Weekly SKDJ: K>D",
  "周线TRIX：高于信号线": "Weekly TRIX: above its signal line",
  "周线指标价：高于50周均线": "Weekly indicator price: above the 50-week average",
  "原策略下一期为完整进攻仓位": "Original strategy has full reference exposure for the next period",
  "价格保护阻断已解除": "Price-protection block is clear",
  "日线SKDJ：K>D": "Daily SKDJ: K>D",
  "新建参考仓位要求K≤40": "A new reference holding requires K≤40",
  "原策略保存的当日低位入场信号": "Saved original-strategy low-level entry signal for the day",
  "原策略保存的当日退出信号": "Saved original-strategy exit signal for the day",
  "含息收益指数高于对应均线": "Total-return index is above its corresponding moving average",
  "原策略20日动量>0": "Original-strategy 20-day momentum >0",
  "原策略保存的多头资格": "Saved original-strategy bullish eligibility",
  "D0评分资料已就绪": "D0 scoring data is ready",
  "D0最终配置资格": "Final D0 allocation eligibility",
  "原策略参考持有天数": "Original-strategy reference holding days",
  "{days}个交易日（上限20日）": "{days} trading days (20-day limit)",
  "D0何时模拟买卖：先按合格资产的动量／波动评分形成目标；目标份额高于实际份额时计划买入，低于实际份额时计划卖出。新确认信号最早下一交易日参与模拟。": "When D0 plans simulated trades: targets are formed from qualifying assets' momentum/volatility scores. A target quantity above actual holdings plans a buy; a lower target plans a sell. A newly confirmed signal can participate in simulation from the next trading day at the earliest.",
  "实际模拟成交还需账户已启动、处于执行交易时段，并满足新鲜报价、限价、整手、资金及可卖份额等条件。查看指标和文字说明不会提交委托。": "A simulated fill also requires a running account, an eligible trading session, and checks for fresh quotes, limit price, trading lots, funds and sellable quantity. Viewing indicators or these explanations does not submit orders."
}});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  'D0还要求至少61个交易日的评分资料，并有同一确认日行情；20日和60日动量用于合格资产之间的评分分配。':'D0 also requires at least 61 trading days of scoring data and market data from the same confirmation day; 20-day and 60-day momentum determine relative scores among eligible assets.'
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,...{
  "为什么还在等待": "Why execution is still waiting",
  "交易逻辑待刷新": "Trading explanation awaiting refresh",
  "当前账户状态尚未核对，买卖原因等待刷新后说明；上次计划不能代表当前动作。": "The current account state has not been verified. Buy/sell reasons will be explained after refresh; the previous plan does not establish the current action.",
  "交易依据需要核对": "Trading evidence needs verification",
  "信号、计划或持仓资料需要核对，暂不补写当前买卖原因。": "Signal, plan or position records need verification. A current buy/sell reason cannot yet be established.",
  "本次已确认目标比例为 {weight}，当前缺少与信号匹配的执行计划，等待计划建立后再判断买卖份额。": "The confirmed target weight is {weight}, but there is no matching execution plan. Buy/sell quantities can be determined once the plan is established.",
  "账户当前没有这只ETF；目标比例尚未转成可核对的买入计划。": "The account currently holds none of this ETF; the target weight has not yet become a verifiable buy plan.",
  "配置资格、目标或份额记录存在不一致，需要核对后才能解释交易原因。": "Eligibility, target or quantity records are inconsistent. They must be verified before a trading reason can be explained.",
  "为什么计划买入": "Why the plan calls for buying",
  "本次计划目标为 {target} 份，实际尚未持有，仍差 {gap} 份，因此计划买入。": "The plan targets {target} units and none are currently held. The remaining gap is {gap} units, so the plan calls for buying.",
  "当前已有 {actual} 份，计划目标为 {target} 份，还需补足 {gap} 份，因此计划增持。": "Current holdings are {actual} units and the plan targets {target}. Another {gap} units are needed, so the plan calls for adding to the position.",
  "本次配置资格已通过，按合格资产的动量／波动评分分配到 {weight} 的模型目标。": "The asset passed allocation eligibility. Its model target is {weight}, based on momentum/volatility scores among eligible assets.",
  "为什么计划卖出": "Why the plan calls for selling",
  "本轮计划目标为0份，当前仍有 {actual} 份，因此计划退出已有仓位。": "The current plan targets zero units, while {actual} units are still held, so the plan calls for exiting the position.",
  "本轮计划保留 {target} 份，当前持有 {actual} 份，超出 {gap} 份，因此计划减持差额。": "The plan retains {target} units, while current holdings are {actual}. The excess is {gap} units, so the plan calls for selling that difference.",
  "本次配置资格未通过；具体失效条件以保存的筛选依据为准。": "Allocation eligibility did not pass. The saved screening evidence identifies the specific unmet conditions.",
  "这只ETF仍通过配置资格，本轮按计划减少份额并保留其余仓位。": "This ETF remains eligible. The current plan reduces its quantity and retains the remaining position.",
  "模型目标比例为 {weight}，本轮计划目标份额为0；具体份额以保存的计划为准。": "The model target weight is {weight}, while this plan targets zero units. The saved plan determines the quantity.",
  "为什么继续持有": "Why the position is being held",
  "实际持仓与计划目标均为 {actual} 份，本轮没有剩余买卖差额，因此按计划持有。": "Actual holdings and the plan target are both {actual} units. There is no remaining buy/sell gap, so the position is held according to the plan.",
  "为什么当前不持仓": "Why there is currently no position",
  "模型目标比例为 {weight}，但本轮计划目标与实际份额均为0，目前没有可执行的买入差额。": "The model target weight is {weight}, but both the current plan target and actual holdings are zero units. There is currently no executable buy gap.",
  "具体未形成目标份额的约束需结合保存的计划记录核对。": "The saved plan records are needed to identify why no target units were formed.",
  "本次配置资格未通过，模型目标为0%，计划目标和实际份额也都是0，因此保持空仓。": "Allocation eligibility did not pass. The model target is 0%, and both planned and actual quantities are zero, so the position remains empty.",
  "本次模型目标、计划目标份额和实际份额均为0，本轮计划保持空仓。": "The model target, planned quantity and actual holdings are all zero. The current plan keeps the position empty.",
  "配置资格的详细依据未记录，这里只解释已保存的计划差额。": "Detailed eligibility evidence was not recorded. This explanation covers only the saved plan gap.",
  "已经提交模拟委托，正在等待成交条件；委托尚未计为成交。": "A simulated order has been submitted and is waiting for fill conditions. It has not yet been recorded as filled.",
  "本轮按先卖后买顺序执行，买入步骤正在等待卖出步骤完成。": "This round executes sells before buys. The buy step is waiting for the sell step to complete.",
  "当前可卖份额不足，剩余卖出计划等待规则允许。": "The currently sellable quantity is insufficient. The remaining sell plan is waiting until the rules allow it.",
  "本轮委托已经结束，剩余计划差额不会自动重试；原目标与已结束委托分开保留。": "This round’s order has ended. The remaining plan gap will not be retried automatically; the original target and ended order remain separate records.",
  "计划仍有份额差额，委托尚未提交。": "A quantity gap remains in the plan; an order has not yet been submitted.",
  "交易逻辑分三步：先确认配置资格，再给合格资产分配目标，最后比较计划目标份额与实际持仓。每只ETF的配置原因和执行等待原因分开说明。": "The trading logic has three steps: confirm eligibility, assign targets to eligible assets, then compare planned target quantities with actual holdings. Each ETF’s allocation reason and execution waiting reason are explained separately.",
  "查看整体配置依据": "View overall allocation evidence",
  "这笔模拟成交用于执行本轮信号对应的委托计划；上方文字说明当前剩余计划。": "This simulated fill executed the order plan associated with the current signal. The explanation above describes the plan that remains.",
  "这笔成交属于历史信号或计划；当前指标不用于补写它当时的交易原因。": "This fill belongs to a historical signal or plan. Current indicators cannot establish its trading reason at that earlier time."
}});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,"保存的筛选依据：":"Saved screening evidence:"});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  "原 D0 · 四资产":"Original D0 · Four assets",
  "D0I-BOND-WW · 周线择债":"D0I-BOND-WW · Weekly bond selection",
  "选择前瞻策略":"Select a forward strategy",
  "两种策略独立记账；切换仅查看，不创建或启动账户。":"Strategies have separate ledgers. Switching only changes the view; it does not create or start an account.",
  "操作正在返回，完成后可切换策略。":"Wait for the current operation to finish before switching strategies.",
  "上次操作结果待核对，请先刷新当前策略。":"Refresh the current strategy to resolve the previous operation first.",
  "有未保存草稿，请先保存，或放弃草稿后切换。":"Save or discard the unsaved draft before switching.",
  "放弃未保存草稿":"Discard unsaved draft",
  "D0I-BOND-WW · 周线择债":"D0I-BOND-WW · Weekly bond selection",
  "股票优先；两股均不合格时，国债通过60周均线与20周动量资格才持有，否则现金。黄金不参与。":"Stocks take priority. When neither stock qualifies, hold government bonds only if their 60-week average and 20-week momentum gates pass; otherwise hold cash. Gold is excluded.",
  "原D0四资产：按原资格与评分，在股票、黄金和国债之间分配。":"Original D0 allocates among stocks, gold and government bonds using its existing gates and scores.",
  "每种策略最多一个独立账户，已有账户后不再新建。":"Each strategy supports one separate account. An existing account is retained.",
  "我已确认当前所选策略与本金；从手动启动时刻开始，不补跑历史。创建后默认停止，启动后按所选规则向前模拟。":"I have checked the selected strategy and capital. The account starts stopped and only simulates forward after manual activation, without replaying earlier trades.",
  "仅模拟估计 · 原D0与周线择债独立记账":"Simulation estimates only · Original D0 and weekly bond selection have separate ledgers",
  "当前策略站内交易提醒":"Current strategy trade notices",
  "当前策略收盘确认信号":"Current strategy confirmed closing signal",
  "暂无委托。启动后由当前策略已确认的目标生成执行计划。":"No orders. After activation, the selected strategy's confirmed target can generate an execution plan.",
  "尚无当前策略已确认信号，暂不能说明目标配置。":"There is no confirmed signal for this strategy yet.",
  "依据确认日 {day} 的已保存信号 · 执行日 {execution_day}":"Saved signal confirmed on {day} · Execution date {execution_day}",
  "D0I-BOND-WW 策略信号":"D0I-BOND-WW strategy signal",
  "尚未建立当前策略的独立账户。请在下方设置中确认本金；创建后默认停止。":"No separate account exists for this strategy. Check capital in settings; a new account starts stopped.",
  "两只股票与周线国债均未通过配置资格，本次目标为现金100%。":"Neither stock nor the weekly bond gate qualifies; the target is 100% cash.",
  "黄金不参与本策略":"Gold is excluded from this strategy",
  "D0I-BOND-WW 的黄金目标固定为0，不使用黄金资格或评分。":"D0I-BOND-WW fixes the gold target at zero and does not use a gold gate or score.",
  "国债资格 · 已完成周":"Bond eligibility · Completed week",
  "仅在银行与创业板均不合格时启用：国债含息周收盘高于60周均线，且20周动量大于0；周内冻结趋势，仍核对当日资料。":"Used only when both stocks fail: the bond's total-return weekly close must exceed its 60-week average and 20-week momentum must be positive. The trend stays fixed during the week, while current data is still checked.",
  "已完成周结束日":"Completed week ending",
  "首次可用确认日":"First available confirmation date",
  "含息周收盘指标值":"Total-return weekly closing indicator",
  "60周均线":"60-week average",
  "20周动量":"20-week momentum",
  "周指标就绪":"Weekly indicators ready",
  "周趋势资格":"Weekly trend eligibility",
  "本次国债配置资格":"Bond allocation eligibility",
  "通过":"Passed",
  "未通过":"Failed",
  "以上是保存的周线资格证据，含息指标值不是ETF成交价格。国债使用防守资格，不参与股票的日线动量评分归一。":"These are saved weekly eligibility facts. Total-return indicator values are not ETF trade prices. Bonds use a defensive gate and do not participate in stock momentum score normalization.",
  "周线证据缺失或时序未通过核对；不使用当前行情补算或猜测历史资格。":"Weekly evidence is missing or its chronology failed validation. Current quotes are not used to reconstruct historical eligibility.",
  "股票优先：银行沿用原日线SKDJ，创业板沿用原周线SKDJ/TRIX资格；合格股票按原评分归一。两股均不合格时，国债通过已完成周的60周均线与20周动量资格才配置，否则现金。黄金不参与。":"Stocks take priority using the original daily bank SKDJ and weekly ChiNext SKDJ/TRIX gates, with eligible stock scores normalized. If neither qualifies, use the completed-week 60-week average and 20-week momentum bond gate; otherwise hold cash. Gold is excluded."
  ,"账户设置":"Account settings","配置方式":"Allocation method","已完成周资格防守，不参与股票评分":"Completed-week defensive gate; excluded from stock scoring","本策略排除黄金":"Gold is excluded from this strategy"
});

window.ETF_PAPER_EN=Object.freeze({...window.ETF_PAPER_EN,
  "微信提醒":"WeChat alerts",
  "请核对服务器上的推送密钥":"Check the server’s delivery token",
  "请先在推送加完成实名认证":"Complete identity verification with pushplus",
  "请在推送加查看账户限制":"Review account restrictions in pushplus",
  "请在推送加查看发送额度":"Check your pushplus delivery quota",
  "接收调仓信号（每次调仓一条）":"Notify me when target weights change (one message per rebalance)",
  "同时接收每笔已提交的模拟委托":"Also notify me about each submitted simulated order",
  "发送测试提醒":"Send test alert",
  "刷新提醒状态":"Refresh alert status",
  "调仓信号":"Rebalance signal",
  "模拟委托":"Simulated order",
  "测试提醒":"Test alert",
  "等待发送":"Queued",
  "正在发送":"Sending",
  "等待重试":"Waiting to retry",
  "推送加已受理，请在微信核对":"Accepted by pushplus; check WeChat",
  "已发送":"Sent",
  "发送失败":"Delivery failed",
  "发送结果待核对":"Delivery unconfirmed",
  "请先创建当前策略的模拟账户。":"Create a simulated account for this strategy first.",
  "账户已变化，请刷新账户状态。":"The account has changed. Refresh the account status.",
  "请先在服务器配置微信推送密钥。":"Configure the WeChat delivery token on the server first.",
  "测试提醒过于频繁，请稍后再试。":"Please wait before sending another test alert.",
  "请先刷新模拟账户状态。":"Refresh the simulated account status.",
  "创建当前策略的模拟账户后可设置微信提醒。":"Create a simulated account for this strategy to set up WeChat alerts.",
  "账户身份待核对，请刷新账户状态。":"Refresh the account status to verify this account.",
  "正在保存微信提醒设置…":"Saving WeChat alert settings…",
  "正在提交测试提醒…":"Submitting test alert…",
  "正在读取微信提醒设置…":"Loading WeChat alert settings…",
  "请刷新提醒状态。":"Refresh the alert status.",
  "微信推送通道尚未配置，请联系管理员。":"Ask the administrator to configure WeChat delivery.",
  "正在核对模拟账户状态。":"Checking the simulated account status.",
  "已订阅 {strategy} 的调仓信号。":"Subscribed to rebalance signals for {strategy}.",
  "微信提醒已关闭，可先发送一条测试提醒。":"WeChat alerts are off. You can send a test alert.",
  "最近提醒 · {kind} · {status} · {time}":"Latest alert · {kind} · {status} · {time}",
  "测试提醒结果待核对，请先刷新状态并查看微信。":"Test delivery is unconfirmed. Refresh the status and check WeChat.",
  "微信提醒设置未能核对，请刷新提醒状态。":"Could not verify your WeChat settings. Refresh the alert status."
});

window.ETF_EN=Object.freeze({...window.ETF_EN,
  "本次银行新建参考仓位上限":"Bank reference-entry limit in this signal",
  "D0 · 四资产":"D0 · Four assets",
  "仅模拟估计 · D0与周线择债独立记账":"Simulation estimates only · D0 and weekly bond selection have separate ledgers",
  "D0四资产：按资格与评分分配；创业板已确认周收盘低于50周均线且资料就绪时，银行新金叉入场上限放宽至K≤50，其余时段为K≤40。":"D0 allocates across four assets using eligibility and scores. When the confirmed ChiNext weekly close is below its 50-week average and data is ready, the bank crossover-entry cap rises to K≤50; otherwise it is K≤40.",
  "已启用":"Enabled",
  "未启用":"Not enabled",
  "创业板50周条件放宽":"Conditional relaxation from ChiNext's 50-week trend",
  "已确认创业板周收盘":"Confirmed ChiNext weekly close",
  "银行原入场条件包含前日 K≤D、当日 K>D 且 K≤{limit}；当日指标退出条件包含 K≥70 或 K≤D。这里显示保存的条件结果，不用当前 K、D 重新判定。":"Bank entry requires prior K≤D, current K>D and K≤{limit}; indicator exits include K≥70 or K≤D. These are saved condition results, not decisions recalculated from the displayed K and D.",
  "仅当已确认的创业板周收盘严格低于50周均线，且指标、评分与当日行情资料就绪时，银行新金叉入场上限由K≤40放宽至K≤50；相等不放宽。此处读取本次保存的规则与证据。":"The bank crossover-entry cap rises from K≤40 to K≤50 only when the confirmed ChiNext weekly close is strictly below its 50-week average and indicators, scores and same-day quotes are ready. Equality does not qualify. This view reads the rule and evidence saved with this signal.",
  "本次银行入场上限的保存证据缺失或未通过核对，不能确定采用40还是50；不使用当前行情补算历史规则。":"Saved evidence for this bank entry limit is missing or could not be verified, so the limit of 40 or 50 is unknown. Current prices are not used to reconstruct historical rules.",
  "银行：日线 SKDJ(9,5) 前一周期K≤D，本期K>D形成向上金叉，且本期K≤{limit}；指标就绪、原策略参考空仓且允许入场时，新建参考仓位。银行未使用TRIX。":"Bank: daily SKDJ(9,5) must cross upward from prior K≤D to current K>D, with current K≤{limit}. A reference position opens only when indicators are ready, the reference is flat and entry is allowed. Bank does not use TRIX.",
  "放宽区间结束时恢复原K40参考状态；再次进入时继承原参考仓位与持有天数，并按当日规则评估。20日退出后的再入场阻断只在连续放宽区间内延续，等待K≤D解除后再等新金叉。":"When relaxation ends, the original K40 reference state resumes. Re-entry into relaxation inherits its position and holding age, then evaluates that day's rule. The re-entry block after a 20-day exit persists only within one continuous relaxed interval; K≤D must clear it before a new upward crossover.",
  "原策略已有有效多头时，D0可以按目标增配；本期没有新金叉或K已高于入场上限，都不单独表示必须退出。":"An existing valid reference long position can allow D0 to add toward its target. No new crossover, or K above the entry cap, does not by itself require an exit.",
  "新建参考仓位要求K≤{limit}":"A new reference position requires K≤{limit}",
  "新建参考仓位的K值上限":"K limit for a new reference position"
});
