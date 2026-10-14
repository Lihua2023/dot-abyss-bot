"""Local pre-run settings. The window closes before the fast game loop starts."""
import argparse
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from farm_policy import COLOR_NAMES, ROUTE_NAMES, normalize_route_priority
from app_paths import RESOURCE_ROOT as ROOT, default_config_path, load_config
from green_farm_panel import GreenFarmPanel

MODES={'按颜色优先级':'color_priority','最左代码（最快）':'leftmost'}

def build_config(original, colors, routes, mode, checkpoint, floors, rounds, recovery):
    if mode not in MODES.values():raise ValueError('代码选择方式须为颜色优先级或最左代码')
    if set(colors)!=set(COLOR_NAMES) or len(colors)!=4:
        raise ValueError('四种代码颜色需要各出现一次')
    if set(routes)!=set(ROUTE_NAMES) or len(routes)!=len(ROUTE_NAMES):
        raise ValueError('六类路线需要各出现一次')
    checkpoint,floors,rounds=int(checkpoint),int(floors),int(rounds)
    recovery=float(recovery)
    if checkpoint not in range(10,101,10):
        raise ValueError('起始检查点为10～100层，每10层一个')
    if checkpoint<0 or checkpoint%10 or floors<=0 or floors%10 or rounds<1 or not 1<=recovery<=60:
        raise ValueError('检查点与推进层数需为10的倍数，轮数至少1，恢复时限为1～60秒')
    if checkpoint+floors>150:
        raise ValueError('终止楼层不能超过150；请减少推进层数')
    config=dict(original,code_color_priority=list(colors),route_priority=list(routes),
                code_selection=mode,checkpoint=checkpoint,floors_per_round=floors,
                target_floor=checkpoint+floors,max_rounds=rounds,stall_recovery_seconds=recovery)
    config['max_key_confirmations']=max(original.get('max_key_confirmations',6),(floors//10+1)*rounds)
    config['code_full_policy']='skip'
    config['max_minutes']=max(original.get('max_minutes',60),60*rounds)
    config.pop('event_priority',None)
    return config

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=default_config_path())
    args=parser.parse_args(argv)
    config=load_config(args.config)
    root=tk.Tk()
    root.title('像素深渊 · 开刷设置')
    root.geometry('650x790')
    root.resizable(False,False)
    style=ttk.Style(root)
    style.configure('TLabel',font=('Microsoft YaHei UI',10))
    style.configure('TButton',font=('Microsoft YaHei UI',10))
    style.configure('FarmTabs.TNotebook.Tab',font=('Microsoft YaHei UI',14,'bold'),padding=(22,9))
    pages=ttk.Notebook(root,style='FarmTabs.TNotebook')
    pages.pack(fill='both',expand=True)
    abyss_page=ttk.Frame(pages)
    green_page=ttk.Frame(pages)
    pages.add(abyss_page,text='深渊')
    pages.add(green_page,text='绿衣')
    green_panel=GreenFarmPanel(root,green_page,parent_owns_lock=True)
    frame=ttk.Frame(abyss_page,padding=22)
    frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='开刷前设置',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
    ttk.Label(frame,text='优先级从上到下；选中一项后用 ↑ ↓ 调整。').pack(anchor='w',pady=(8,14))
    mode=tk.StringVar(value=next((k for k,v in MODES.items() if v==config.get('code_selection')), '按颜色优先级'))
    row=ttk.Frame(frame);row.pack(fill='x')
    ttk.Label(row,text='代码选择方式').pack(side='left')
    ttk.Combobox(row,textvariable=mode,values=list(MODES),state='readonly',width=22).pack(side='right')
    lists=ttk.Frame(frame);lists.pack(fill='x',pady=16)
    def priority_list(title,names,order):
        box=ttk.LabelFrame(lists,text=title,padding=10);box.pack(side='left',fill='both',expand=True,padx=4)
        widget=tk.Listbox(box,height=len(names),font=('Microsoft YaHei UI',12),exportselection=False,width=14)
        widget.pack(fill='x')
        for key in order: widget.insert('end',names[key])
        def move(delta):
            selected=widget.curselection()
            if not selected:return
            old=selected[0];new=old+delta
            if 0<=new<widget.size():
                value=widget.get(old);widget.delete(old);widget.insert(new,value);widget.selection_set(new)
        buttons=ttk.Frame(box);buttons.pack(pady=(8,0))
        ttk.Button(buttons,text='↑ 上移',command=lambda:move(-1),width=8).pack(side='left')
        ttk.Button(buttons,text='↓ 下移',command=lambda:move(1),width=8).pack(side='left',padx=4)
        return widget
    colors=priority_list('代码颜色',COLOR_NAMES,config.get('code_color_priority',['impact','risk','safe','rush']))
    routes=priority_list('路线优先级',ROUTE_NAMES,normalize_route_priority(config.get('route_priority')))
    values={}
    for key,label,default in [('checkpoint','起始检查点',30),('floors_per_round','每轮推进层数',50),
                              ('max_rounds','刷取轮数',1),('stall_recovery_seconds','等待多久重新识别（秒）',5)]:
        row=ttk.Frame(frame);row.pack(fill='x',pady=5)
        ttk.Label(row,text=label).pack(side='left')
        values[key]=tk.StringVar(value=str(config.get(key,default)))
        if key=='checkpoint':
            ttk.Combobox(row,textvariable=values[key],values=[str(n) for n in range(10,101,10)],state='readonly',width=10).pack(side='right')
        else:
            ttk.Entry(row,textvariable=values[key],width=12).pack(side='right')
    ttk.Label(frame,text='事件：特殊 → 代码 → 最左\n宝箱：钥匙 → 扣血；不选增加侵蚀\n恢复固定净化。通信重连优先。',justify='left').pack(anchor='w',pady=14)
    ttk.Label(frame,text='开始后8秒内切回游戏。F7暂停，F12停止。').pack(anchor='w')
    selected=[]
    def save(start):
        if start and green_panel.process and green_panel.process.poll() is None:
            messagebox.showerror('无法启动','绿衣脚本仍在运行，请先停止。',parent=root)
            return
        try:
            reverse_colors={v:k for k,v in COLOR_NAMES.items()}
            reverse_routes={v:k for k,v in ROUTE_NAMES.items()}
            updated=build_config(config,[reverse_colors[v] for v in colors.get(0,'end')],
                                 [reverse_routes[v] for v in routes.get(0,'end')],MODES[mode.get()],
                                 values['checkpoint'].get(),values['floors_per_round'].get(),
                                 values['max_rounds'].get(),values['stall_recovery_seconds'].get())
            temp=args.config.with_suffix('.tmp')
            temp.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            temp.replace(args.config)
        except (ValueError,OSError) as exc:
            messagebox.showerror('设置未保存',str(exc),parent=root);return
        if start:selected.append(True);root.destroy()
        else:messagebox.showinfo('已保存','下次启动会使用这些设置。',parent=root)
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=14)
    ttk.Button(buttons,text='保存设置',command=lambda:save(False)).pack(side='left')
    ttk.Button(buttons,text='保存并开始刷取',command=lambda:save(True)).pack(side='right')
    def on_close():
        if green_panel.close_requested(): root.destroy()
    root.protocol('WM_DELETE_WINDOW',on_close)
    root.mainloop()
    if selected:
        from abyss_bot import main as run
        return run(['--config',str(args.config),'--run','--delay','8']) or 0
    return 0

if __name__=='__main__':
    raise SystemExit(main())
