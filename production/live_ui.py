from datetime import datetime,timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import json
import time
from simulator_core import CODES,NAMES,ORDER,TITLES
from intraday import LiveService,PollClock,now
from chinext_service import STRATEGIES,BY_ID
from seven_service import BY_ID as SEVEN, label as seven_label

def reference_values(labels):
    return [f'{s["id"]}  {s["name"]}' for s in STRATEGIES]+labels.values()+[seven_label(code) for code in SEVEN]

def reference_label(labels,code):
    if code in SEVEN:return seven_label(code)
    return f'{code}  {BY_ID[code]["name"]}' if code in BY_ID else labels.label(code)

class LiveUI:
    def build_live(self):
        panel=self.live_page
        ttk.Label(panel,text='当天行情 · 每30分钟刷新',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        ttk.Label(panel,text='程序打开时自动采集；休市时仍按30分钟检查，报价时间可能保持不变。收盘日线在16:10后尝试确认。',foreground='#99adc1').pack(anchor='w',pady=(7,15))
        bar=ttk.Frame(panel);bar.pack(fill='x',pady=(0,14))
        self.live_auto=tk.BooleanVar(value=True)
        self.live_auto_check=ttk.Checkbutton(bar,text='自动刷新（30分钟）',variable=self.live_auto,command=self.auto_live_changed);self.live_auto_check.pack(side='left',padx=(0,20))
        self.controls.append((self.live_auto_check,'normal'))
        self.live_countdown=tk.StringVar(value='启动后立即读取');ttk.Label(bar,textvariable=self.live_countdown,foreground='#60dcc2').pack(side='left')
        self.button(bar,'立即刷新当天报价',self.refresh_live,True).pack(side='right')
        self.live_quotes=self.table(panel,[('asset','ETF',210),('price','现价',115),('change','较昨收',115),('open','今日开盘',115),('range','当日高 / 低',165),('time','来源报价时间',210)],4)
        self.live_summary=tk.StringVar(value='等待首次报价；没有联网成功前不会显示为当天行情。')
        ttk.Label(panel,textvariable=self.live_summary,foreground='#99adc1',wraplength=self.px(1230),justify='left').pack(anchor='w',pady=14)
        bar=ttk.Frame(panel);bar.pack(fill='x',pady=(0,12))
        ttk.Label(bar,text='参考策略',foreground='#99adc1').pack(side='left',padx=(0,8))
        self.live_strategy=tk.StringVar(value=reference_label(self.strategy_labels,'T5VOTE'))
        self.live_strategy_combo=self.combo(bar,self.live_strategy,reference_values(self.strategy_labels),width=70)
        self.live_strategy_combo.pack(side='left',padx=(0,18));self.live_strategy_combo.bind('<<ComboboxSelected>>',lambda _:self.live_reference_selected())
        ttk.Label(bar,text='独立参考本金 / 元',foreground='#99adc1').pack(side='left',padx=(0,8))
        self.live_capital=tk.StringVar(value='100000');self.entry(bar,self.live_capital,13).pack(side='left',padx=(0,10))
        self.button(bar,'更新参考目标',self.render_live).pack(side='left')
        self.live_ranking_note=tk.StringVar(value='创业板优选5策略＋原四资产9策略＋新增7组合，均可在此查看参考目标。')
        ttk.Label(panel,textvariable=self.live_ranking_note,foreground='#99adc1',wraplength=self.px(1230),justify='left').pack(anchor='w',pady=(0,12))
        self.live_plan_table=self.table(panel,[('asset','盘中参考配置',240),('weight','临时目标仓位',190),('budget','参考金额 / 元',200),('state','状态',360)],5)
        self.live_plan_note=tk.StringVar(value='盘中目标不会改动历史账户；正式交易仍等待收盘确认。')
        ttk.Label(panel,textvariable=self.live_plan_note,foreground='#f5c875',wraplength=self.px(1230),justify='left').pack(anchor='w',pady=13)
        bar=ttk.Frame(panel);bar.pack(fill='x')
        self.button(bar,'查看策略判断依据',self.live_detail).pack(side='left')
        self.button(bar,'导出已采集的30分钟记录',self.export_live).pack(side='left',padx=10)
        self.button(bar,'导出2013起历史日线',self.export_daily_history).pack(side='left')
        self.live_archive=tk.StringVar();ttk.Label(bar,textvariable=self.live_archive,foreground='#99adc1').pack(side='right')
    def init_live(self):
        if hasattr(self,'live'):return
        self.live=LiveService(self.service);self.live_clock=PollClock()
        code=self.service.settings.get('live_reference_strategy','T5VOTE')
        self.live_strategy.set(reference_label(self.strategy_labels,code if code in BY_ID or code in ORDER or code in SEVEN else 'T5VOTE'))
        self.live_auto.set(self.service.settings.get('intraday_auto',True))
        self.render_live();self.after(1000,self.tick_live)
    def live_reference_selected(self):
        if self.service:
            self.service.settings['live_reference_strategy']=self.live_strategy.get().split()[0]
            self.service.save_settings()
        self.render_live()
    def auto_live_changed(self):
        if not self.service:return
        self.service.settings['intraday_auto']=self.live_auto.get();self.service.save_settings()
        if self.live_auto.get():self.live_clock.next_due=self.live_clock.clock()
    def tick_live(self):
        if self.live_auto.get():
            remain=self.live_clock.remaining();mins,secs=divmod(remain,60)
            self.live_countdown.set(f'下次刷新：{mins:02d}:{secs:02d}'+('（当前任务完成后读取）' if remain==0 and self.busy else ''))
            if self.live_clock.due(True,self.busy):self.refresh_live(automatic=True)
        else:self.live_countdown.set('自动刷新已暂停，可随时手动读取')
        self.after(1000,self.tick_live)
    def refresh_live(self,force_history=False,automatic=False):
        if not hasattr(self,'live') or self.busy:return
        self.live_clock.started()
        update_top5=bool(getattr(self,'top5',None)) and (not automatic or (self.top5_auto.get() and time.monotonic()>=self.top5_next_due))
        def done(result):
            self.live_refresh_error=result['quote_error']
            self.data_label.set('收盘日线至 '+self.service.market.latest)
            if result['top5_refreshed']:
                self.top5_refresh_error=result['top5_error']
                self.top5_next_due=time.monotonic()+1800
                self.top5_update_info()
                if result['signals']:self.top5_show_signals(result['signals'])
                if result['top5_error']:self.top5_warning.set('刷新未完成，保留此前行情：'+result['top5_error'])
            if getattr(self,'seven',None):self.seven_sync()
            self.render_live()
            errors=[x for x in [result['quote_error'],result['top5_error']] if x]
            success='当天报价'+('与五策略完整K线' if result['top5_refreshed'] else '')+'已刷新；参考目标不自动成交。'
            self.status.set('部分行情未更新，保留此前数据：'+'；'.join(errors) if errors else success)
        self.work(lambda:self.refresh_reference_sources(force_history,update_top5),done,'正在刷新当天报价'+('与五策略完整K线…' if update_top5 else '…'))
    def refresh_reference_sources(self,force_history=False,update_top5=True):
        result=dict(quote_error=None,top5_error=None,signals=None,top5_refreshed=False)
        try:self.live.refresh(self.progress,force_history)
        except Exception as exc:result['quote_error']=str(exc)
        if update_top5 and getattr(self,'top5',None):
            result['top5_refreshed']=True
            try:
                self.top5.refresh(progress=self.progress)
                result['signals']=self.top5.signal_summary()
            except Exception as exc:result['top5_error']=str(exc)
        return result
    def render_live(self):
        if not hasattr(self,'live'):return
        self.current_live_plan=None
        self.clear_table(self.live_quotes);self.clear_table(self.live_plan_table)
        stats=self.live.store.stats();self.live_archive.set(f'已保存 {stats["count"]} 批盘中快照')
        batch=self.live.batch;moment=now();today=moment.date().isoformat()
        if batch:
            qts=[]
            for c in CODES:
                q=batch['quotes'][c];qt=datetime.fromisoformat(q['quote_at']);qts.append(qt)
                label=qt.strftime('%Y-%m-%d %H:%M:%S')+('（旧）' if q['day']!=today else '')
                self.live_quotes.insert('',tk.END,values=[NAMES[c]+' '+c[2:],f'{q["price"]:.3f}',f'{q["change"]:+.2%}',f'{q["open"]:.3f}' if q['started'] else '未开盘',f'{q["high"]:.3f} / {q["low"]:.3f}' if q['started'] else '—',label])
            received=datetime.fromisoformat(batch['received_at']).strftime('%Y-%m-%d %H:%M:%S')
            age=max(0,int((moment-min(qts)).total_seconds()/60))
            self.live_summary.set(f'本机采集：{received} · 腾讯公开行情 · 最早报价距现在约{age}分钟。\n收盘历史已保存至 {self.service.market.latest}。'+self.live.history_note)
        else:self.live_summary.set('尚无报价记录；五策略可使用本地已确认K线，时间显示在下方。')
        if getattr(self,'live_refresh_error',None):self.live_summary.set(self.live_summary.get()+'\n本次报价刷新失败，以上为保留记录：'+self.live_refresh_error)
        code=self.live_strategy.get().split()[0]
        if code in SEVEN:
            self.render_seven_reference(code);return
        if code in BY_ID:
            self.render_top5_reference(code);return
        self.live_ranking_note.set(self.strategy_labels.note)
        self.live_plan_table.heading('asset',text='盘中参考配置');self.live_plan_table.heading('weight',text='临时目标仓位')
        if hasattr(self.live_plan_table,'sort_labels'):self.live_plan_table.sort_labels.update(asset='盘中参考配置',weight='临时目标仓位')
        try:
            plan=self.live.plan(code,self.live_capital.get())
        except ValueError as e:self.live_plan_note.set(str(e));return
        self.current_live_plan=plan
        if plan:
            for c in CODES:
                weight=plan['observation']['weights'][c]
                self.live_plan_table.insert('',tk.END,values=[NAMES[c],f'{weight:.1%}',f'{plan["budgets"][c]:,.2f}','临时纳入配置' if weight else '暂不配置'])
            self.live_plan_table.insert('',tk.END,values=['现金',f'{plan["cash"]/plan["capital"]:.1%}',f'{plan["cash"]:,.2f}','剩余预算'])
        self.live_plan_note.set(self.live.preview_note+'\n这是按独立参考本金计算的方案，不是当前历史账户的实际仓位，也不自动成交。')
    def render_top5_reference(self,code):
        self.live_ranking_note.set('创业板优选 · '+BY_ID[code]['parameters']+'。历史筛选结果见“五策略历史对比”；原九策略排名不适用于这一组。')
        self.live_plan_table.heading('asset',text='已确认K线参考配置');self.live_plan_table.heading('weight',text='下一步参考目标仓位')
        if hasattr(self.live_plan_table,'sort_labels'):self.live_plan_table.sort_labels.update(asset='已确认K线参考配置',weight='下一步参考目标仓位')
        if not getattr(self,'top5',None):
            self.live_plan_note.set('正在载入五策略完整K线，稍后显示参考目标。');return
        try:
            from top5_reference import reference_plan
            plan=reference_plan(self.top5,code,self.live_capital.get())
        except (ValueError,TypeError,OverflowError) as exc:
            self.live_plan_note.set(str(exc));return
        self.current_live_plan=plan
        weight=plan['weight']
        self.live_plan_table.insert('',tk.END,values=['创业板ETF 159915',f'{weight:.1%}',f'{plan["budgets"]["sz159915"]:,.2f}',plan['signal']])
        self.live_plan_table.insert('',tk.END,values=['现金',f'{1-weight:.1%}',f'{plan["cash"]:,.2f}','等待执行时仍以实际账户持仓为准'])
        note=f'完整60分钟行情截至 {plan["as_of"]} · {plan["timeframe"]}信号K线截至 {plan["signal_bar"]}\n'+plan['reason']
        note+='\n按独立参考本金分配；参考持仓从2023-01-03起模拟，不是顶部账户的实际持仓，也不自动成交。'
        if getattr(self,'top5_refresh_error',None):note+='\n五策略刷新失败，显示上次确认的数据：'+self.top5_refresh_error
        self.live_plan_note.set(note)
    def live_detail(self):
        if not getattr(self,'current_live_plan',None):
            messagebox.showinfo('盘中参考',self.live_plan_note.get(),parent=self);return
        p=self.current_live_plan
        if p.get('strategy') in SEVEN:
            self.text_window('七组合实时参考依据',json.dumps(p['seven'],ensure_ascii=False,indent=2));return
        if p.get('strategy') in BY_ID:
            self.text_window('创业板策略判断依据',p['name']+'\n参数：'+p['parameters']+'\n完整行情截至：'+p['as_of']+'\n信号K线截至：'+str(p['signal_bar'])+'\n\n'+p['reason']+'\n\n独立参考状态与待执行信号\n'+json.dumps(p,ensure_ascii=False,indent=2));return
        o=p['observation'];b=self.live.batch
        self.text_window('盘中临时判断依据',f'{p["day"]} · {p["strategy"]} {TITLES[p["strategy"]]}\n采集时间：{b["received_at"]}\n\n'+self.live.preview_note+'\n\n'+o['reason']+'\n\n全部计算依据\n'+json.dumps(o,ensure_ascii=False,indent=2))
    def export_live(self):
        path=filedialog.asksaveasfilename(parent=self,title='导出从现在起保存的盘中记录',initialfile='每30分钟行情记录.csv',defaultextension='.csv',filetypes=[('CSV表格','*.csv')])
        if path:
            self.work(lambda:self.live.store.export(path),lambda count:self.status.set(f'已导出 {count} 批真实采集记录：'+path),'正在导出已采集的盘中快照…')
    def attach_daily(self):
        id=self.selected
        self.work(lambda:self.service.update_market(id,data=self.service.market.data),lambda note:(self.refresh(),self.status.set(note)),'正在核对已确认日线与当前账户…')
    def export_daily_history(self):
        dest=filedialog.askdirectory(parent=self,title='选择2013起历史日线导出位置')
        if not dest:return
        folder=Path(dest)/('2013起ETF历史日线_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
        self.work(lambda:self.service.export_history(folder),lambda path:self.status.set('历史日线已导出：'+path),'正在导出原始历史日线…')
