"""Small, checked integration hooks for Windows upstream source updates."""
import ast

IMPORT = "from gui.tabs.auto_optimize import AutoOptimizeTab"
INIT = "        self.optimizer_tab = AutoOptimizeTab(self.notebook, self)"
ADD = '        self.notebook.add(self.optimizer_tab, text="自动优化")'
PRESET_BLOCK = '''
        # Full optimizer exports preserve parameters; ordinary presets are unchanged.
        if "optimizer_snapshot" in data:
            from gui.tabs.auto_optimize import apply_snapshot_to_app
            try:
                apply_snapshot_to_app(self.app, data["optimizer_snapshot"])
            except Exception as exc:
                messagebox.showerror("优化预设", str(exc))
            return
'''


def check_image_picker_contract(root):
    """Reject incompatible base dialogs before any staged optimizer hooks are written.

    The optimizer inherits upstream single-selection dialogs. Let compatible
    upstream improvements through; do not replace the original picker files.
    """
    contracts = (
        ("gui/dialogs/char_picker.py", "CharacterPickerDialog", {"parent", "app", "title", "for_ally"},
         {"_build", "_get_filtered_ids", "_refresh_grid", "_on_select", "_on_close",
          "_on_canvas_resize", "_cols_for_width", "_apply_filter"}),
        ("gui/dialogs/memory_picker.py", "MemoryPickerDialog", {"parent", "app", "title"},
         {"_build", "_get_filtered_ids", "_refresh_grid", "_on_select", "_on_close",
          "_on_canvas_resize", "_cols_for_width", "_apply_rarity_filter", "_load_card_thumb",
          "_load_thumbs_async"}),
    )
    for relative, name, arguments, needed in contracts:
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"自动优化图片选择补丁不适用：缺少 {relative}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
        if len(classes) != 1:
            raise RuntimeError(f"自动优化图片选择补丁不适用：{name}类结构已改变")
        methods = {node.name: node for node in classes[0].body if isinstance(node, ast.FunctionDef)}
        if "__init__" not in methods or not needed.issubset(methods):
            raise RuntimeError(f"自动优化图片选择补丁不适用：{name}方法接口已改变")
        init = methods["__init__"]
        positional = init.args.posonlyargs + init.args.args
        names = {arg.arg for arg in positional + init.args.kwonlyargs}
        required = {arg.arg for arg in positional[:len(positional)-len(init.args.defaults)]}
        required.update(arg.arg for arg, default in zip(init.args.kwonlyargs, init.args.kw_defaults) if default is None)
        if not arguments.issubset(names) or not required.issubset(arguments | {"self"}):
            raise RuntimeError(f"自动优化图片选择补丁不适用：{name}构造参数已改变")
        # Subclasses call these inherited methods with the existing positional
        # arguments. New optional parameters are compatible, new required ones
        # must stop the staged update before any integration hooks are written.
        one_argument = {"_on_select", "_on_canvas_resize", "_cols_for_width",
                        "_apply_filter", "_apply_rarity_filter", "_load_card_thumb"}
        for method_name in needed:
            method = methods[method_name]
            positional = method.args.posonlyargs + method.args.args
            static = any(isinstance(decorator, ast.Name) and decorator.id == "staticmethod"
                         for decorator in method.decorator_list)
            supplied = (0 if static else 1) + (method_name in one_argument)
            required_count = len(positional) - len(method.args.defaults)
            if required_count > supplied or any(default is None for default in method.args.kw_defaults):
                raise RuntimeError(f"自动优化图片选择补丁不适用：{name}.{method_name}必需参数已改变")
        fields = {node.attr for node in ast.walk(methods["_build"]) if isinstance(node, ast.Attribute)
                  and isinstance(node.value, ast.Name) and node.value.id == "self"
                  and isinstance(node.ctx, ast.Store)}
        if not {"_canvas", "_grid_inner", "_canvas_window"}.issubset(fields):
            raise RuntimeError(f"自动优化图片选择补丁不适用：{name}网格布局结构已改变")


def restore_optimizer_hooks(root):
    check_image_picker_contract(root)
    plans = {}
    modal = root / "gui/widgets/modal.py"
    if not modal.is_file():
        raise RuntimeError("自动优化图片选择补丁不适用：缺少模态窗口生命周期辅助文件")
    source = modal.read_text(encoding="utf-8")
    tree = ast.parse(source)
    binders = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == "_bind_modal_minimize_restore"]
    if len(binders) != 1 or "dialog" not in {arg.arg for arg in binders[0].args.args}:
        raise RuntimeError("自动优化图片选择补丁不适用：模态窗口接口已改变")
    cleanups = [node for node in ast.walk(binders[0]) if isinstance(node, ast.FunctionDef)
                and node.name == "_cleanup"]
    if len(cleanups) != 1 or "event" not in {arg.arg for arg in cleanups[0].args.args}:
        raise RuntimeError("自动优化图片选择补丁不适用：模态清理接口已改变")
    guard = "if event is not None and event.widget is not dialog:\n    return\n"
    expected = ast.parse(guard).body[0]
    cleanup = cleanups[0]
    if not any(isinstance(node, ast.If) and ast.dump(node.test) == ast.dump(expected.test)
               and len(node.body) == 1 and isinstance(node.body[0], ast.Return) for node in cleanup.body):
        lines = source.splitlines(keepends=True)
        lines.insert(cleanup.body[0].lineno - 1, "        if event is not None and event.widget is not dialog:\n            return\n")
        source = "".join(lines)
    plans[modal] = source
    app = root / "gui/app.py"
    source = app.read_text(encoding="utf-8")
    for existing, anchor in ((IMPORT, "from gui.tabs.tactical_exercise import TacticalExerciseTab"),
                             (INIT, "        self.tactical_tab = TacticalExerciseTab(self.notebook, self)"),
                             (ADD, '        self.notebook.add(self.tactical_tab, text="战术演习")')):
        if source.count(existing) == 1:
            continue
        if existing in source or source.count(anchor) != 1:
            raise RuntimeError("自动优化补丁不适用：主窗口结构已改变；中止更新以保留现有功能")
        source = source.replace(anchor, anchor + "\n" + existing, 1)
    favorites_hook = '        from gui.tabs.favorites import FavoritesTab\n        self.favorites_tab = FavoritesTab(self.notebook, self)\n        self.notebook.add(self.favorites_tab, text="★ 收藏")'
    if source.count(favorites_hook) != 1:
        anchor = '        self.notebook.add(self.composite_tab, text="复合战术演习")'
        if 'self.favorites_tab' in source or source.count(anchor) != 1:
            raise RuntimeError('收藏页面补丁不适用：主标签结构已改变')
        source = source.replace(anchor, anchor+'\n'+favorites_hook, 1)
    plans[app] = source
    tab = root / "gui/tabs/tactical_exercise.py"
    source = tab.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                 and node.name == "_load_tactical_preset"]
    if len(functions) != 1:
        raise RuntimeError("自动优化补丁不适用：预设加载结构已改变")
    func = functions[0]
    lines = source.splitlines(keepends=True)
    body = "".join(lines[func.lineno - 1:func.end_lineno])
    if '"optimizer_snapshot" in data' not in body:
        assignments = [node for node in ast.walk(func) if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "data" for target in node.targets)
                       and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                       and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == "json"
                       and node.value.func.attr == "load"]
        if len(assignments) != 1:
            raise RuntimeError("自动优化补丁不适用：预设JSON读取方式已改变")
        lines.insert(assignments[0].end_lineno, PRESET_BLOCK)
        source = "".join(lines)
    plans[tab] = source
    # Shared single-select favorites filtering must also survive upstream files.
    for relative,kind,highlight in (
            ('gui/dialogs/char_picker.py','characters','self._update_filter_highlight()'),
            ('gui/dialogs/memory_picker.py','memories','self._update_rarity_highlight()')):
        path=root/relative
        source=path.read_text(encoding='utf-8')
        hooks=(
            ('from gui.widgets.favorite_filters import init_picker_favorites, add_picker_star, favorites_filtered',
             'from gui.widgets.modal import _bind_modal_minimize_restore', 'before'),
            (f'        init_picker_favorites(self, "{kind}")', '        self.app = app', 'after'),
            ('        add_picker_star(self, filter_frame)', '        '+highlight, 'after'))
        for hook,anchor,position in hooks:
            if source.count(hook)==1:continue
            if hook in source or source.count(anchor)!= (2 if 'highlight()' in anchor else 1):
                raise RuntimeError('收藏筛选补丁不适用：选择窗口结构已改变')
            source=source.replace(anchor,hook+'\n'+anchor if position=='before' else anchor+'\n'+hook,1)
        tree=ast.parse(source)
        cls=next(node for node in tree.body if isinstance(node,ast.ClassDef))
        method=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='_get_filtered_ids')
        lines=source.splitlines(keepends=True)
        body=''.join(lines[method.lineno-1:method.end_lineno])
        if 'favorites_filtered(self, result)' not in body:
            returns=[node for node in ast.walk(method) if isinstance(node,ast.Return)
                     and isinstance(node.value,ast.Name) and node.value.id=='result']
            if not returns:raise RuntimeError('收藏筛选补丁不适用：筛选返回结构已改变')
            for node in returns:
                lines[node.lineno-1]=lines[node.lineno-1].replace('return result','return favorites_filtered(self, result)')
            source=''.join(lines)
        plans[path]=source
    for path, code in plans.items():
        compile(code, str(path), "exec")
    for path, code in plans.items():
        path.write_text(code, encoding="utf-8")
