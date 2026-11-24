"""Seven combinations: annotated catalog, replay comparison and paper accounts."""
import tkinter as tk
from tkinter import ttk,messagebox,filedialog
import json
from seven_service import SevenService,BY_ID,ORDER,CATALOG,CODES,NAMES,SHORT,label

def pct(value):return '不足一年' if value is None else f'{value:+.2%}'

class SevenUI:
    def build_seven(self):
        self.seven_page=ttk.Frame(self.tabs,padding=(0,12));self.tabs.add(self.seven_page,text='七组合模拟')
        p=self.seven_page
        ttk.Label(p,text='七个组合 · 逐项说明与独立模拟',font=('Microsoft YaHei UI',17,'bold')).pack(anchor='w')
        self.seven_data=tk.StringVar(value='正在加载共同交易日…')
        ttk.Label(p,textvariable=self.seven_data,foreground='#99adc1').pack(anchor='w',pady=5)
        ttk.Label(p,text='固定研究标签仅比较这7个组合：2023-01-03～2026-09-15、本金10万元、含交易费用、期末清算。\nA：独立本金各自复利；B：日终信号、次日开盘切换。历史排名不代表未来结果。',foreground='#99adc1').pack(anchor='w')
        bar=ttk.Frame(p);bar.pack(fill='x',pady=8)
        self.seven_start=tk.StringVar(value='2023-01-03');self.seven_end=tk.StringVar(value='2026-09-15');self.seven_capital=tk.StringVar(value='100000')
        for text,var in [('开始',self.seven_start),('结束',self.seven_end),('本金',self.seven_capital)]:
            ttk.Label(bar,text=text).pack(side='left',padx=(0,5));self.entry(bar,var,12).pack(side='left',padx=(0,12))
        self.button(bar,'重新比较七组合',self.seven_compare,True).pack(side='left')
        self.button(bar,'导出本次比较',self.seven_export_compare).pack(side='right')
        self.seven_table=self.table(p,[('code','编号',145),('name','组合',220),('kind','特点 / 固定研究标签',225),('cagr','本次年化',90),('dd','本次最大回撤',105),('return','本次累计收益',105),('fees','佣金',85)],7)
        self.seven_table.bind('<<TreeviewSelect>>',self.seven_select);self.seven_table.bind('<Double-1>',lambda _:self.seven_detail())
        self.seven_note=tk.StringVar(value='下面显示已核验的原研究成绩；修改区间或本金后，请点击重新比较。')
        ttk.Label(p,textvariable=self.seven_note,foreground='#60dcc2',wraplength=self.px(1200)).pack(anchor='w',pady=6)
        bar=ttk.Frame(p);bar.pack(fill='x',pady=5)
        self.seven_strategy=tk.StringVar(value=label('A_T5VOTE_P3'))
        self.seven_strategy_combo=self.combo(bar,self.seven_strategy,[label(c) for c in ORDER],width=66);self.seven_strategy_combo.pack(side='left')
        self.button(bar,'参数与研究边界',self.seven_detail).pack(side='left',padx=8)
        self.seven_name=tk.StringVar(value='我的组合模拟');self.entry(bar,self.seven_name,14).pack(side='left')
        self.button(bar,'新建组合账户',self.seven_create).pack(side='right')
        bar=ttk.Frame(p);bar.pack(fill='x',pady=5)
        self.seven_account=tk.StringVar();self.seven_account_combo=self.combo(bar,self.seven_account,width=48);self.seven_account_combo.pack(side='left')
        self.seven_account_combo.bind('<<ComboboxSelected>>',lambda _:self.seven_account_show())
        self.button(bar,'模拟至上方结束日',self.seven_advance,True).pack(side='left',padx=8)
        self.button(bar,'成交与账户明细',self.seven_account_detail).pack(side='left')
        self.button(bar,'导出账户',self.seven_export_account).pack(side='right')
        self.button(bar,'导入账户',self.seven_import_account).pack(side='right',padx=8)
        self.seven_account_note=tk.StringVar(value='组合账户保存在独立目录；引用顶部四资产账户的操作不会改变这里的持仓。')
        ttk.Label(p,textvariable=self.seven_account_note,foreground='#f5c875',wraplength=self.px(1200)).pack(anchor='w',pady=7)
        self.seven_rows=[];self.seven_results=None
        for code in ORDER:
            m=BY_ID[code]['results']['base'];self.seven_table.insert('',tk.END,iid=code,values=[code,SHORT[code],BY_ID[code]['tag'],pct(m['periods']['全期']['cagr']),f"-{m['periods']['全期']['max_drawdown']:.2%}",pct(m['periods']['全期']['total_return']),f"{m['fees']:,.2f}"])
    def init_seven(self):
        self.seven=SevenService(self.service.folder,self.service,self.top5)
        info=self.seven_sync();self.seven_end.set(info['latest']);self.seven_reload_accounts();self.render_live()
    def seven_sync(self):
        try:self.seven.sync();self.seven_error=None
        except Exception as exc:self.seven_error=str(exc)
        info=self.seven.info();self.seven_data.set(f'共同完整日线：{info["latest"]} · 恒生科技60分钟：{info["hourly"]}'+(' · 更新未完成：'+self.seven_error if self.seven_error else ''))
        if self.seven_end.get()==getattr(self,'seven_latest',None):self.seven_end.set(info['latest'])
        self.seven_latest=info['latest']
        return info
    def seven_select(self,event=None):
        selected=self.seven_table.selection()
        if selected:self.seven_strategy.set(label(selected[0]))
    def seven_detail(self):
        code=self.seven_strategy.get().split()[0];r=BY_ID[code]
        text=label(code)+'\n\n规则：'+r['rule']+'\n执行：'+r['execution']+'\n\n参考成绩（含期末清算，非持续账户收益）\n'
        for variant,title in [('base','标准费用'),('cost2','双倍费率/滑点，最低佣金仍5元'),('delay','信号额外延迟一个执行周期')]:
            m=r['results'][variant]['periods']['全期'];text+=f'{title}：年化 {pct(m["cagr"])}，最大回撤 {m["max_drawdown"]:.2%}，累计 {pct(m["total_return"])}\n'
        text+='\n研究范围：2023-01-03～2026-09-15，100,000元；收盘净值回撤。\n\n'+'\n'.join(CATALOG['limits'])
        text+='\n\n完整参数与所有分段结果\n'+json.dumps(dict(parameters=CATALOG['module_parameters'],strategy=r),ensure_ascii=False,indent=2)
        self.text_window('七组合参数、成绩与局限',text)
    def seven_compare(self):
        start,end,capital=self.seven_start.get(),self.seven_end.get(),self.seven_capital.get()
        def job():self.seven.sync();return self.seven.compare(start,end,capital,self.progress)
        self.work(job,self.seven_compared,'正在按实际本金重新记账七个组合…')
    def seven_compared(self,rows):
        self.seven_sync()
        self.seven_results=rows;self.clear_table(self.seven_table)
        cg=[r['metrics']['cagr'] for r in rows if r['metrics']['cagr'] is not None];best=max(cg) if cg else None;dd=min(r['metrics']['max_drawdown'] for r in rows)
        for r in rows:
            m=r['metrics'];tags=[]
            if best is not None and abs(m['cagr']-best)<1e-10:tags.append('本次年化最高')
            if abs(m['max_drawdown']-dd)<1e-10:tags.append('本次回撤最低')
            self.seven_table.insert('',tk.END,iid=r['strategy'],values=[r['strategy'],SHORT[r['strategy']],r['tag'],pct(m['cagr']),f'-{m["max_drawdown"]:.2%}',pct(m['total_return']),f'{m["fees"]:,.2f}'])
        a=rows[0];ranking='；'.join(r['strategy']+(' 年化最高' if best is not None and abs(r['metrics']['cagr']-best)<1e-10 else '')+(' 回撤最低' if abs(r['metrics']['max_drawdown']-dd)<1e-10 else '') for r in rows if (best is not None and abs(r['metrics']['cagr']-best)<1e-10) or abs(r['metrics']['max_drawdown']-dd)<1e-10)
        self.seven_note.set(f'本次实际区间 {a["start"]} → {a["end"]} · 本金 {a["capital"]:,.2f}元 · 含费用与期末清算。'+ranking)
    def seven_export_compare(self):
        if not self.seven_results:messagebox.showinfo('比较结果','请先运行一次七组合比较。',parent=self);return
        path=filedialog.asksaveasfilename(parent=self,initialfile='七组合比较.json',defaultextension='.json')
        if path:
            from simulator_core import write_json
            write_json(path,dict(results=self.seven_results,parameters=CATALOG['module_parameters'],limits=CATALOG['limits']))
    def seven_create(self):
        args=(self.seven_strategy.get().split()[0],self.seven_name.get(),self.seven_capital.get(),self.seven_start.get())
        self.work(lambda:self.seven.create_account(*args),lambda a:self.seven_reload_accounts(a['id']),'正在以实际本金建立独立组合账户…')
    def seven_reload_accounts(self,id=None):
        self.seven_sync()
        self.seven_rows=self.seven.accounts();self.seven_account_combo.configure(values=[a['name']+' · '+a['result']['strategy']+' · '+a['id'][:6] for a in self.seven_rows])
        if self.seven_rows:
            index=next((i for i,a in enumerate(self.seven_rows) if a['id']==id),0);self.seven_account_combo.current(index)
        self.seven_account_show()
    def seven_selected_account(self):
        index=self.seven_account_combo.current()
        if index<0:raise ValueError('请先新建或选择一个组合账户。')
        return self.seven_rows[index]
    def seven_account_show(self):
        if not self.seven_rows:return
        a=self.seven_selected_account();r=a['result'];m=r['metrics'];last=r['curve'][-1]
        self.seven_account_note.set(f'{a["name"]} · {r["strategy"]} · {r["start"]} → {r["end"]}\n持续账户总资产 {m["final_equity"]:,.2f}元 · 现金 {last["cash"]:,.2f}元 · 收益 {pct(m["total_return"])} · 最大回撤 {m["max_drawdown"]:.2%} · {m["fills"]}笔成交。未强制期末清仓；点击模拟才接续。')
    def seven_advance(self):
        try:a=self.seven_selected_account()
        except ValueError as exc:messagebox.showinfo('组合账户',str(exc),parent=self);return
        id,end=a['id'],self.seven_end.get()
        def job():self.seven.sync();return self.seven.advance(id,end)
        self.work(job,lambda a:self.seven_reload_accounts(a['id']),'正在接续组合账户并核对既有成交…')
    def seven_account_detail(self):
        try:a=self.seven_selected_account()
        except ValueError as exc:messagebox.showinfo('组合账户',str(exc),parent=self);return
        r=a['result'];self.text_window('组合账户成交与判断依据',self.seven_account_note.get()+'\n\n执行方式：'+r['plan']['execution']+'\n\n完整模拟明细（含每笔成交时刻、价格、费用）\n'+json.dumps(a,ensure_ascii=False,indent=2))
    def seven_export_account(self):
        try:a=self.seven_selected_account()
        except ValueError as exc:messagebox.showinfo('组合账户',str(exc),parent=self);return
        path=filedialog.asksaveasfilename(parent=self,initialfile=a['name']+'_七组合账户.json',defaultextension='.json')
        if path:self.seven.export_account(a['id'],path)
    def seven_import_account(self):
        path=filedialog.askopenfilename(parent=self,filetypes=[('七组合账户JSON','*.json')])
        if path:self.work(lambda:self.seven.import_account(path),lambda a:self.seven_reload_accounts(a['id']),'正在复算核验备份账户…')
    def render_seven_reference(self,code):
        self.live_ranking_note.set('七组合 · '+BY_ID[code]['tag']+'。固定排名依据：2023-01-03～2026-09-15、10万元，仅在7个组合内比较；完整规则见“七组合模拟”。')
        self.live_plan_table.heading('asset',text='组合参考配置');self.live_plan_table.heading('weight',text='下一执行时点参考比例')
        if not getattr(self,'seven',None):self.live_plan_note.set('正在加载七组合行情…');return
        try:
            self.seven_sync()
            r=self.seven.run(code,capital=self.live_capital.get(),terminal=False,intraday=True);p=r['plan']
        except (ValueError,TypeError,OverflowError) as exc:self.live_plan_note.set(str(exc));return
        self.current_live_plan=dict(strategy=code,seven=r)
        for c,name in zip(CODES,NAMES):
            w=p['weights'][c];self.live_plan_table.insert('',tk.END,values=[name,f'{w:.1%}',f'{w*r["capital"]:,.2f}','按已确认信号，等待下一执行时点' if w else '条件不符留现金'])
        self.live_plan_table.insert('',tk.END,values=['现金',f'{p["cash_weight"]:.1%}',f'{p["cash_weight"]*r["capital"]:,.2f}','未配置预算'])
        self.live_plan_note.set(f'信号截至 {p["as_of"]}；银行/黄金日线截至 {p["daily_as_of"]}。\n'+p['execution']+'\n参考状态从2023-01-03按初始本金独立模拟，比例折算到输入预算；不是实际账户订单。'+('\n更新未完成，以上为保留数据：'+self.seven_error if self.seven_error else ''))
