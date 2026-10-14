"""Legacy standalone shortcut; the unified settings window is the preferred entry."""
import tkinter as tk
from tkinter import ttk

from green_farm_panel import GreenFarmPanel


def main():
    root = tk.Tk()
    root.title('绿衣刷取 · 深度 10')
    root.geometry('610x530')
    root.resizable(False, False)
    page = ttk.Frame(root)
    page.pack(fill='both', expand=True)
    panel = GreenFarmPanel(root, page)
    root.protocol('WM_DELETE_WINDOW', lambda: root.destroy() if panel.close_requested() else None)
    root.mainloop()


if __name__ == '__main__':
    main()
