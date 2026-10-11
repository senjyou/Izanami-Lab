# -*- coding: utf-8 -*-
"""模态弹窗工具：绑定父窗口最小化/恢复处理。

从 gui_app.py 抽取，供各选择器弹窗（MemoryPickerDialog / EnemyPickerDialog /
CharacterPickerDialog / EnemyDetailDialog）复用。
"""


def _bind_modal_minimize_restore(dialog, parent):
    """为模态弹窗绑定父窗口最小化/恢复处理。

    修复bug：打开弹窗后最小化主界面（如Win+D显示桌面），再从任务栏恢复时
    无法恢复、无法关闭程序。根因：grab_set锁在不可见的弹窗上，Windows无法
    激活被grab锁定的主窗口，导致整个应用输入被锁死。
    方案：主窗口最小化时grab_release解锁；恢复时deiconify弹窗并重新grab_set。
    """
    top = parent.winfo_toplevel()

    def _on_top_unmap(event):
        # 主窗口被最小化/隐藏时，释放grab避免锁死整个应用
        if event.widget is not top:
            return
        try:
            if dialog.winfo_exists():
                dialog.grab_release()
        except Exception:
            pass

    def _on_top_map(event):
        # 主窗口恢复显示时，恢复弹窗并重新建立模态grab
        if event.widget is not top:
            return

        def _restore():
            try:
                if not dialog.winfo_exists():
                    return
                # 处理iconic和withdrawn两种隐藏状态
                state = str(dialog.state())
                if state in ('iconic', 'withdrawn'):
                    dialog.deiconify()
                dialog.lift()
                dialog.focus_force()
                dialog.grab_set()
            except Exception:
                pass

        # 延迟执行，确保窗口管理器状态已稳定
        try:
            top.after(50, _restore)
        except Exception:
            pass

    map_id = top.bind("<Map>", _on_top_map, "+")
    unmap_id = top.bind("<Unmap>", _on_top_unmap, "+")

    def _cleanup(event=None):
        try:
            top.unbind("<Map>", map_id)
            top.unbind("<Unmap>", unmap_id)
        except Exception:
            pass

    dialog.bind("<Destroy>", _cleanup, "+")
