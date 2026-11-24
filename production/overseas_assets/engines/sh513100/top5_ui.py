"""Five ChiNext candidates, isolated from the original multi-asset accounts."""
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json, os, time, sys

FG='#eef3f8'; MUTED='#99adc1'; PANEL='#182330'; ACCENT='#60dcc2'
COLORS={'T5VOTE':'#60dcc2','T5WEEK':'#879fff','T5DON':'#f5bc66','T5SUPER':'#cba1f3','T5MA':'#ff91b1','BENCH':'#9aa6b5'}

def fmt_pct(x):return '不足一年' if x is None else f'{x:+.2%}'

class Top5UI:
    def build_top5(self):
        self.top5_page=ttk.Frame(self.tabs,padding=(0,12));self.tabs.add(self.top5_page,text='纳指100优选 · 5策略')
        self.top5=None;self.top5_result=None;self.top5_detail=None;self.top5_signal=None;self.top5_initialized=False
        self.top5_data_text=tk.StringVar(value='正在加载纳指100ETF历史行情…')
        top=ttk.Frame(self.top5_page);top.pack(fill='x',pady=(0,10))
        ttk.Label(top,text='纳指100ETF · 五个优选策略',font=('Microsoft YaHei UI',17,'bold')).pack(side='left')
        self.button(top,'研究报告',self.top5_open_report).pack(side='right')
        self.button(top,'刷新60分钟行情',self.top5_refresh_market,True).pack(side='right',padx=8)
        ttk.Label(self.top5_page,textvariable=self.top5_data_text,foreground=MUTED,wraplength=self.px(1200)).pack(anchor='w',pady=(0,9))
        self.top5_tabs=ttk.Notebook(self.top5_page);self.top5_tabs.pack(fill='both',expand=True)
        self.top5_signals_page=ttk.Frame(self.top5_tabs,padding=10)
        self.top5_compare_page=ttk.Frame(self.top5_tabs,padding=10)
        self.top5_accounts_page=ttk.Frame(self.top5_tabs,padding=10)
        for page,label in [(self.top5_signals_page,'已确认信号'),(self.top5_compare_page,'五策略历史对比'),(self.top5_accounts_page,'纳指100模拟账户')]:self.top5_tabs.add(page,text=label)
        p=self.top5_signals_page
        self.top5_auto=tk.BooleanVar(value=True)
        auto=ttk.Checkbutton(p,text='程序打开时，每30分钟刷新已完成的60分钟K线',variable=self.top5_auto,command=self.top5_auto_changed)
        auto.pack(anchor='w',pady=(0,10));self.controls.append((auto,'normal'))
        self.top5_signal_tree=self.table(p,[('name','策略',300),('timeframe','周期',80),('signal','当前已确认信号',205),('bar','信号K线截至',185),('ready','指标状态',90)],6)
        self.top5_signal_tree.bind('<Double-1>',lambda _:self.top5_signal_detail())
        ttk.Label(p,text='信号在K线结束后确认，最早下一根可执行K线开盘模拟。周线策略固定持有20个交易日，实际退出同时取决于账户买入日。',foreground=MUTED,wraplength=self.px(1170)).pack(anchor='w',pady=12)
        self.button(p,'查看选中策略的规则与依据',self.top5_signal_detail).pack(anchor='w')
        self.top5_warning=tk.StringVar(value='仅模拟159915与现金；已确认信号与未完成K线分开。')
        ttk.Label(p,textvariable=self.top5_warning,foreground='#f5c875',wraplength=self.px(1170)).pack(anchor='w',pady=12)
        self.top5_build_compare();self.top5_build_accounts()
        self.tabs.bind('<<NotebookTabChanged>>',lambda _:self.top5_sync_header(),add='+')

    def top5_build_compare(self):
        p=self.top5_compare_page;bar=ttk.Frame(p);bar.pack(fill='x',pady=(0,10))
        self.top5_start=tk.StringVar(value='2023-01-03');self.top5_end=tk.StringVar(value='2026-09-15');self.top5_capital=tk.StringVar(value='100000')
        for label,var in [('开始',self.top5_start),('结束',self.top5_end),('本金',self.top5_capital)]:
            ttk.Label(bar,text=label,foreground=MUTED).pack(side='left',padx=(0,5));self.entry(bar,var,12).pack(side='left',padx=(0,12))
        self.button(bar,'比较五策略',self.top5_compare,True).pack(side='left')
        self.button(bar,'导出结果',self.top5_export_compare).pack(side='right')
        self.top5_compare_tree=self.table(p,[('name','策略',265),('equity','期末资产 / 元',120),('return','累计收益',100),('cagr','年化收益',100),('dd','最大回撤',100),('trades','完整交易',80)],6)
        self.top5_chart=tk.Canvas(p,bg=PANEL,highlightthickness=0,height=self.px(205));self.top5_chart.pack(fill='both',expand=True,pady=(10,5))
        self.top5_chart.bind('<Configure>',lambda _:self.top5_draw_compare())
        self.top5_chart_kind=tk.StringVar(value='资产')
        line=ttk.Frame(p);line.pack(fill='x')
        for label in ['资产','回撤']:
            ttk.Radiobutton(line,text=label,variable=self.top5_chart_kind,value=label,command=self.top5_draw_compare).pack(side='left',padx=(0,12))
        self.top5_compare_note=tk.StringVar(value='同一区间、同一本金；含佣金、滑点与T+1，末日按统一评价口径清算。')
        ttk.Label(line,textvariable=self.top5_compare_note,foreground=MUTED,wraplength=self.px(970)).pack(side='left')

    def top5_build_accounts(self):
        p=self.top5_accounts_page;bar=ttk.Frame(p);bar.pack(fill='x',pady=(0,12))
        self.top5_account_var=tk.StringVar();self.top5_account_combo=self.combo(bar,self.top5_account_var,width=35);self.top5_account_combo.pack(side='left')
        self.top5_account_combo.bind('<<ComboboxSelected>>',lambda _:self.top5_select_account())
        self.button(bar,'＋ 新建纳指100账户',self.top5_new_account,True).pack(side='left',padx=10)
        self.button(bar,'导出账户',self.top5_export_account).pack(side='right')
        self.button(bar,'导入备份',self.top5_import_account).pack(side='right',padx=8)
        self.top5_account_status=tk.StringVar(value='选择一种策略新建账户，随后按已完成的60分钟K线接续模拟。此页的账户独立保存。')
        ttk.Label(p,textvariable=self.top5_account_status,foreground=ACCENT,wraplength=self.px(1170)).pack(anchor='w',pady=(0,12))
        self.top5_account_chart=tk.Canvas(p,bg=PANEL,highlightthickness=0,height=self.px(165));self.top5_account_chart.pack(fill='both',expand=True,pady=(0,8))
        self.top5_account_chart.bind('<Configure>',lambda _:self.top5_draw_account())
        self.top5_trade_tree=self.table(p,[('buy','买入时间',170),('sell','卖出时间',170),('qty','份数',80),('profit','完整交易净盈亏',135),('reason','退出依据',210)],5)
        bar=ttk.Frame(p);bar.pack(fill='x',pady=(10,0))
        ttk.Label(bar,text='模拟至',foreground=MUTED).pack(side='left',padx=(0,8));self.top5_account_end=tk.StringVar();self.entry(bar,self.top5_account_end,17).pack(side='left')
        self.button(bar,'接续模拟',self.top5_advance,True).pack(side='left',padx=8)
        self.button(bar,'使用最新完整K线',self.top5_use_latest).pack(side='left')
        self.button(bar,'查看持仓与待执行依据',self.top5_account_more).pack(side='right')
        ttk.Label(p,text='持续账户不在每次查看时清仓；新增成交只在你点击接续模拟后记入。股票ETF当日买入次日可卖，原有四资产账户在其他页面使用。',foreground=MUTED,wraplength=self.px(1170)).pack(anchor='w',pady=(10,0))

    def init_top5(self):
        from chinext_service import Top5Service
        self.top5=Top5Service(self.service.folder)
        self.top5_auto.set(self.service.settings.get('top5_auto',True))
        self.top5_catalog=self.top5.list_strategies()
        self.top5_next_due=time.monotonic()+1800
        self.top5_update_info();self.top5_reload_accounts()
        self.tabs.select(self.live_page);self.render_live()
        self.after(300,self.top5_initial_load);self.after(1000,self.top5_tick)

    def top5_initial_load(self):
        if self.busy:self.after(1000,self.top5_initial_load);return
        def job():return self.top5.signal_summary(),self.top5.compare('2023-01-03',self.top5.info()['latest_daily'],100000,progress=self.progress)
        def done(result):
            self.top5_show_signals(result[0]);self.top5_compared(result[1]);self.top5_initialized=True;self.render_live()
            self.top5_next_due=time.monotonic()
        self.work(job,done,'正在核对五个优选策略的已确认信号与历史成绩…')

    def top5_update_info(self):
        info=self.top5.info();self.top5_info=info
        self.top5_data_text.set(f'159915 · 完整日线至 {info["latest_daily"]} · 完整60分钟K线至 {info["latest_bar"]} · 本地模拟')
        self.top5_end.set(info['latest_daily']);self.top5_account_end.set(info['latest_bar'])

    def top5_tick(self):
        if self.top5_initialized and self.top5_auto.get() and not self.busy and time.monotonic()>=self.top5_next_due:self.top5_refresh_market()
        self.after(1000,self.top5_tick)

    def top5_auto_changed(self):
        if not self.service:return
        self.service.settings['top5_auto']=self.top5_auto.get();self.service.save_settings()
        if self.top5_auto.get():self.top5_next_due=time.monotonic()

    def top5_refresh_market(self):
        if not self.top5 or self.busy:return
        self.top5_next_due=time.monotonic()+1800
        def job():
            try:return self.top5.refresh(progress=self.progress),self.top5.signal_summary(),None
            except Exception as exc:return None,None,str(exc)
        def done(result):
            self.top5_refresh_error=result[2]
            if result[2]:
                self.top5_warning.set('刷新未完成，保留此前行情与账户：'+result[2]);self.status.set('纳指100行情刷新未完成，已保留旧数据。');self.render_live();return
            self.top5_update_info();self.top5_show_signals(result[1])
            if getattr(self,'seven',None):self.seven_sync()
            self.render_live()
            warnings=result[0].get('warnings',[])
            self.status.set('纳指100已确认行情已刷新；模拟账户等待你接续。'+(' '+str(warnings[0]) if warnings else ''))
        self.work(job,done,'正在更新真实60分钟行情与日线，只接受完整K线…')

    def top5_show_signals(self,result):
        self.top5_signal=result;self.clear_table(self.top5_signal_tree)
        for r in result['rows']:
            self.top5_signal_tree.insert('',tk.END,iid=r['id'],values=[r['name'],r['timeframe'],r['signal'],r['last_bar'],'已就绪' if r['ready'] else '等待预热'])
        self.top5_warning.set('；'.join(map(str,result.get('warnings',[]))) or '当前显示已结束K线的信号，开盘成交仍需等待下一根行情；不自动下实盘单。')

    def top5_signal_detail(self):
        selection=self.top5_signal_tree.selection()
        if not selection or not self.top5_signal:return
        r=next(x for x in self.top5_signal['rows'] if x['id']==selection[0]);s=next(x for x in self.top5_catalog if x['id']==r['id'])
        text=s['name']+'\n\n'+s['description']+'\n\n参数\n'+str(s['parameters'])+'\n\n信号K线截至 '+str(r['last_bar'])+'\n'+r['signal']+'\n\n'+str(r['detail'])
        self.text_window('纳指100策略规则与依据',text)

    def top5_compare(self):
        if not self.top5:return
        start=self.top5_start.get().strip();end=self.top5_end.get().strip();capital=self.top5_capital.get().strip()
        self.work(lambda:self.top5.compare(start,end,float(capital),progress=self.progress),self.top5_compared,'正在以真实60分钟开盘执行五个策略…')

    def top5_compared(self,result):
        self.top5_result=result;self.clear_table(self.top5_compare_tree)
        for r in result['rows']:
            self.top5_compare_tree.insert('',tk.END,iid=r['id'],values=[r['name'],f'{r["final_equity"]:,.2f}',fmt_pct(r['total_return']),fmt_pct(r['cagr']),f'{r["max_drawdown"]:.2%}',r['trades']])
        self.top5_compare_note.set(f'{result["start"]} → {result["end"]} · 本金{float(result["capital"]):,.0f}元 · 每日收盘回撤 · 期末统一清算')
        self.top5_draw_compare()

    def top5_draw_lines(self,canvas,curves,capital,drawdown=False):
        canvas.delete('all');width=canvas.winfo_width();height=canvas.winfo_height()
        if width<50 or height<50:return
        if not curves:canvas.create_text(width/2,height/2,text='完成模拟后显示资产走势',fill=MUTED);return
        prepared=[]
        for key,label,points in curves:
            if not points:continue
            high=float(capital);arr=[]
            for p in points:
                day=str(p.get('date',p.get('datetime','')))
                stamp=datetime.fromisoformat(day).timestamp();equity=float(p['equity']);high=max(high,equity)
                arr.append((stamp,(equity/high-1)*100 if drawdown else equity/10000))
            prepared.append((key,label,arr))
        if not prepared:return
        left,right,top,bottom=self.px(54),self.px(18),self.px(35),self.px(28)
        xs=[p[0] for _,_,ps in prepared for p in ps];ys=[p[1] for _,_,ps in prepared for p in ps]+([0] if drawdown else [float(capital)/10000])
        xmin,xmax=min(xs),max(xs);low,high=min(ys),max(ys);pad=max((high-low)*.08,.01);low-=pad;high+=pad
        xx=lambda x:left+(x-xmin)/max(86400,xmax-xmin)*(width-left-right)
        yy=lambda y:top+(high-y)/max(.0001,high-low)*(height-top-bottom)
        for i in range(4):
            y=low+(high-low)*i/3;py=yy(y);canvas.create_line(left,py,width-right,py,fill='#2b3949');canvas.create_text(left-7,py,text=f'{y:.0f}%' if drawdown else f'{y:.1f}',anchor='e',fill=MUTED,font=('Microsoft YaHei UI',8))
        canvas.create_text(left,8,text='距高点回撤 / %' if drawdown else '账户资产 / 万元',anchor='nw',fill=MUTED,font=('Microsoft YaHei UI',8))
        for key,label,ps in prepared:
            coords=[v for point in ps for v in (xx(point[0]),yy(point[1]))]
            if len(coords)>=4:canvas.create_line(*coords,fill=COLORS.get(key,ACCENT),width=2,dash=(6,4) if key=='BENCH' else ())
        canvas.create_text(left,height-8,text=datetime.fromtimestamp(xmin).strftime('%Y-%m-%d'),anchor='sw',fill=MUTED,font=('Microsoft YaHei UI',8))
        canvas.create_text(width-right,height-8,text=datetime.fromtimestamp(xmax).strftime('%Y-%m-%d'),anchor='se',fill=MUTED,font=('Microsoft YaHei UI',8))
        short={'T5VOTE':'三指标','T5WEEK':'周线SKDJ/TRIX','T5DON':'唐奇安','T5SUPER':'Supertrend','T5MA':'SMA50','BENCH':'买入持有'}
        pos=left+self.px(120)
        for key,label,_ in prepared:
            canvas.create_text(pos,8,text=short.get(key,label),anchor='nw',fill=COLORS.get(key,ACCENT),font=('Microsoft YaHei UI',8));pos+=self.px(125 if key=='T5WEEK' else 90)

    def top5_draw_compare(self):
        if not self.top5_result:return
        curves=[(r['id'],r['name'],self.top5_result['curves'].get(r['id'],[])) for r in self.top5_result['rows']]
        self.top5_draw_lines(self.top5_chart,curves,self.top5_result['capital'],self.top5_chart_kind.get()=='回撤')

    def top5_reload_accounts(self,selected=None):
        if not self.top5:return
        self.top5_account_rows=self.top5.list_accounts()
        self.top5_account_combo.configure(values=[f'{r["name"]} · {r["strategy_name"]}' for r in self.top5_account_rows])
        if self.top5_account_rows:
            ix=next((i for i,r in enumerate(self.top5_account_rows) if r['id']==selected),0)
            self.top5_account_combo.current(ix);self.top5_select_account()

    def top5_select_account(self):
        ix=self.top5_account_combo.current()
        if ix<0 or not self.top5:return
        detail=self.top5.account_detail(self.top5_account_rows[ix]['id']);self.top5_show_account(detail)

    def top5_show_account(self,detail):
        self.top5_detail=detail;a=detail['account']
        self.top5_account_status.set(f'{a["name"]} · {a["strategy_name"]} · 截至 {a["last_bar"]}\n总资产 {a["equity"]:,.2f}元  |  现金 {a["cash"]:,.2f}元  |  纳指100ETF {a["shares"]:,}份')
        self.clear_table(self.top5_trade_tree)
        for t in detail.get('trades',[]):self.top5_trade_tree.insert('',tk.END,values=[t.get('buy_time',''),t.get('sell_time',''),t.get('quantity',''),f'{t.get("profit",0):+,.2f}',t.get('reason','')])
        self.top5_draw_account()

    def top5_draw_account(self):
        if not self.top5_detail:return
        a=self.top5_detail['account'];self.top5_draw_lines(self.top5_account_chart,[(a['strategy_id'],a['strategy_name'],self.top5_detail.get('ledger',[]))],a['capital'])

    def top5_new_account(self):
        if not self.top5:return
        w=tk.Toplevel(self);w.title('新建纳指100优选模拟账户');w.configure(bg='#101720');w.geometry(f'{self.px(630)}x{self.px(410)}');w.transient(self)
        form=ttk.Frame(w,padding=24);form.pack(fill='both',expand=True)
        name=tk.StringVar(value='纳指100优选账户');capital=tk.StringVar(value='100000');start=tk.StringVar(value='2023-01-03');strategy=tk.StringVar(value=self.top5_catalog[0]['name'])
        choices=[s['name'] for s in self.top5_catalog]
        for row,(label,var) in enumerate([('账户名称',name),('初始本金 / 元',capital),('开始日期',start)]):
            ttk.Label(form,text=label).grid(row=row,column=0,sticky='w',pady=9);ttk.Entry(form,textvariable=var,width=35).grid(row=row,column=1,sticky='ew',padx=12)
        ttk.Label(form,text='固定策略').grid(row=3,column=0,sticky='w',pady=9);ttk.Combobox(form,textvariable=strategy,values=choices,state='readonly',width=35).grid(row=3,column=1,sticky='ew',padx=12)
        ttk.Label(form,text='从所选日期开始，按完整K线接续模拟。\n已有账户历史保留；每个新账户固定一种策略。',foreground=MUTED).grid(row=4,column=0,columnspan=2,sticky='w',pady=14)
        def submit():
            if self.busy:return
            sid=self.top5_catalog[choices.index(strategy.get())]['id'];n=name.get();st=start.get();c=capital.get();w.destroy()
            def done(d):self.top5_reload_accounts(d['account']['id']);self.top5_tabs.select(self.top5_accounts_page)
            self.work(lambda:self.top5.create_account(n,sid,st,float(c)),done,'正在建立独立纳指100模拟账户…')
        ttk.Button(form,text='建立账户',command=submit,style='Accent.TButton').grid(row=5,column=1,sticky='e',padx=12)

    def top5_use_latest(self):
        if self.top5:self.top5_account_end.set(self.top5.info()['latest_bar'])

    def top5_advance(self):
        if not self.top5_detail:messagebox.showinfo('选择账户','请先新建或选择纳指100模拟账户。',parent=self);return
        sid=self.top5_detail['account']['id'];end=self.top5_account_end.get().strip() or None
        def done(d):self.top5_reload_accounts(sid);self.top5_show_account(d)
        self.work(lambda:self.top5.advance_account(sid,end),done,'正在按真实完整K线接续，保留已有成交…')

    def top5_account_more(self):
        if not self.top5_detail:return
        d=self.top5_detail
        self.text_window('纳指100账户持仓与执行依据',json.dumps({k:d.get(k) for k in ['account','pending','warnings','events']},ensure_ascii=False,indent=2))

    def top5_export_account(self):
        if not self.top5_detail:return
        folder=filedialog.askdirectory(parent=self,title='选择纳指100账户导出位置')
        if not folder:return
        sid=self.top5_detail['account']['id'];dest=Path(folder)/('纳指100模拟账户_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
        self.work(lambda:self.top5.export_account(sid,dest),lambda r:self.status.set('账户已导出：'+str(r['path'])),'正在导出账户与配套行情…')

    def top5_import_account(self):
        if not self.top5:return
        if not hasattr(self.top5,'import_account'):
            messagebox.showinfo('导入账户','请保留本软件导出的完整备份；当前账户会自动保存在本机。',parent=self);return
        path=filedialog.askopenfilename(parent=self,title='选择纳指100账户备份',filetypes=[('账户备份','*.zip')])
        if path:self.work(lambda:self.top5.import_account(path),lambda d:self.top5_reload_accounts(d['account']['id']),'正在核对并导入为独立账户…')

    def top5_export_compare(self):
        if not self.top5_result:return
        path=filedialog.asksaveasfilename(parent=self,title='导出五策略比较',initialfile='纳指100五策略比较.json',defaultextension='.json',filetypes=[('JSON','*.json')])
        if path:
            Path(path).write_text(json.dumps(self.top5_result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');self.status.set('比较结果已导出：'+path)

    def top5_open_report(self):
        from simulator_core import ROOT
        folders=[Path(sys.executable).resolve().parent,ROOT] if getattr(sys,'frozen',False) else [ROOT]
        for folder in folders:
            for filename in ['纳指100策略研究与应用报告.pdf','纳指100策略研究与应用报告.md']:
                p=folder/filename
                if p.exists():os.startfile(str(p));return
        messagebox.showinfo('研究报告','研究报告位于本次交付文件夹。',parent=self)

    def top5_sync_header(self):
        if not hasattr(self,'top5_page'):return
        active=self.tabs.select() in [str(self.top5_page),str(getattr(self,'seven_page',''))]
        if hasattr(self,'new_account_button'):self.new_account_button.configure(state='disabled' if self.busy or active else 'normal')
        self.accounts.configure(state='disabled' if self.busy or active else 'readonly')
