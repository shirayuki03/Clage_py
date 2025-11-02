import re
import os
import math
import pygame
import ast

_state = {
    "stage_defined": False,
    "block_stack": [],
    "sprites": {},
    "sprite_order": [],
    "logical": {"xmin": -240, "xmax": 240, "ymin": -180, "ymax": 180},
    "fps": 30,
    "screen": None,
    "clock": None,
    "window_size": (960, 720),
    "images_cache": {},
    "foreign_depth": 0,
    "running": True,

    "pending_to_clambon": [],
    "drain_cursor": 0,
    "max_drain_per_frame": 64,

    "clone_scripts": {},
    "clone_counter": {},
    "clone_capture": None,

    "ppu": 2,

    "globals": {},
}

_RE_STAGE_OPEN = re.compile(r'^\s*Stage\s*\(\s*\)\s*\{\s*$')
_RE_SPRITE_OPEN = re.compile(r'^\s*Sprite\s*\(\s*"([^"]+)"\s*\)\s*\{\s*$')
_RE_START_OPEN = re.compile(r'^\s*start\s*\{\s*$')

_RE_FPS_SET = re.compile(r'^\s*fps\.set\s*\(\s*([^\)]+)\s*\)\s*$')
_RE_WIDTH_SET = re.compile(r'^\s*width\.set\s*\(\s*([^,]+)\s*,\s*([^\)]+)\s*\)\s*$')
_RE_HEIGHT_SET = re.compile(r'^\s*height\.set\s*\(\s*([^,]+)\s*,\s*([^\)]+)\s*\)\s*$')
_RE_RUN = re.compile(r'^\s*run\s*\(\s*\)\s*$')

_NAME = r'([A-Za-z_]\w*(?:#\d+)?)'

_RE_PROP_SET = re.compile(rf'^\s*{_NAME}\s*\.\s*(x|y|direction|costume)\s*=\s*(.+?)\s*$')
_RE_MOVE_CMD = re.compile(rf'^\s*{_NAME}\.move\s*\(\s*([^\)]+)\s*\)\s*$')
_RE_SHOW_CMD = re.compile(rf'^\s*{_NAME}\.show\s*\(\s*\)\s*$')
_RE_HIDE_CMD = re.compile(rf'^\s*{_NAME}\.hide\s*\(\s*\)\s*$')

_RE_TOUCHING_CALL = re.compile(rf'\b{_NAME}\s*\.\s*touching\s*\(\s*([^)]+?)\s*\)')

_SPR_REF_RE = re.compile(rf'\b{_NAME}\s*\.\s*(x|y|direction)\b')

_RE_CLONE_OPEN = re.compile(r'^\s*clone\s*\{\s*$')
_RE_CLONE_CMD = re.compile(r'^\s*clone\s*\(\s*([A-Za-z_]\w*)\s*\)\s*$')
_RE_INTERNAL_CLONE_DELETE = re.compile(r'^\s*__clage_clone_delete__\s*\(\s*"([^"]+)"\s*\)\s*$')
_RE_INTERNAL_SPRITE_CTX_OPEN  = re.compile(r'^\s*__clage_sprite_ctx_open__\s*\(\s*"([^"]+)"\s*\)\s*$')
_RE_INTERNAL_SPRITE_CTX_CLOSE = re.compile(r'^\s*__clage_sprite_ctx_close__\s*\(\s*\)\s*$')

_RE_VAR_DECL = re.compile(r'^\s*var\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$')
_RE_ASSIGN   = re.compile(r'^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$')

_RE_ARRAY_ELEM = re.compile(r'\b([A-Za-z_]\w*)\s*\[\s*([^\]]+)\s*\]')

_RE_STOP_ALL   = re.compile(r'^\s*stop\.all\s*\(\s*\)\s*$')
_RE_STOP_ALIAS = re.compile(r'^\s*stop\s*\(\s*\)\s*$')


def _in_stage():
    return "Stage" in _state["block_stack"]

def _in_sprite():
    return any(s.startswith("Sprite:") for s in _state["block_stack"])

def _to_int_literal(t):
    try:
        return int(str(t).strip())
    except Exception:
        return None

def _to_number_literal(t):
    s = str(t).strip()
    try:
        return int(s)
    except Exception:
        try:
            return float(s)
        except Exception:
            return None

def _to_string_literal(t):
    s = str(t).strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return None

def _resolve_path(path):
    candidates = [path,
                  os.path.join(os.getcwd(), path),
                  os.path.join(os.path.dirname(__file__), path)]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

def _load_image(path):
    if path in _state["images_cache"]:
        return _state["images_cache"][path]
    rp = _resolve_path(path)
    if rp is None:
        return None
    try:
        img = pygame.image.load(rp).convert_alpha()
        _state["images_cache"][path] = img
        return img
    except Exception:
        return None

def _substitute_sprite_refs(expr: str) -> str:
    def repl(m):
        name, prop = m.group(1), m.group(2)
        sp = _state["sprites"].get(name)
        if not sp:
            return "0"
        try:
            return str(float(sp[prop]))
        except Exception:
            return "0"
    return _SPR_REF_RE.sub(repl, expr)

def _substitute_global_vars(expr: str) -> str:
    if not _state["globals"]:
        return expr
    for k in sorted(_state["globals"].keys(), key=len, reverse=True):
        v = _state["globals"][k]
        if isinstance(v, (int, float)):
            expr = re.sub(rf'\b{k}\b', str(float(v)), expr)
    return expr

def _eval_number_expr_no_arrays(expr: str):
    expr2 = _substitute_sprite_refs(expr)
    expr2 = _substitute_global_vars(expr2)
    lit = _to_number_literal(expr2)
    if lit is not None:
        return float(lit)
    if not re.fullmatch(r'[0-9eE\.\+\-\*\/%\(\)\s]+', expr2):
        raise ValueError("数式に 関係ない 文字が 含まれています")
    val = eval(expr2, {"__builtins__": {}}, {})
    if isinstance(val, (int, float)):
        return float(val)
    raise ValueError("数式の 評価に 失敗しました")

def _substitute_array_elems(expr: str) -> str:
    def repl(m):
        name = m.group(1)
        idx_expr = m.group(2)
        arr = _state["globals"].get(name)
        if not isinstance(arr, (list, tuple)):
            return m.group(0)
        try:
            idx = int(_eval_number_expr_no_arrays(idx_expr))
        except Exception:
            return m.group(0)
        if not (0 <= idx < len(arr)):
            return "0"
        val = arr[idx]
        if isinstance(val, (int, float)):
            return str(float(val))
        return "0"
    return _RE_ARRAY_ELEM.sub(repl, expr)

def _eval_number_expr(expr: str):
    expr2 = _substitute_sprite_refs(expr)
    expr2 = _substitute_global_vars(expr2)
    expr2 = _substitute_array_elems(expr2)
    lit = _to_number_literal(expr2)
    if lit is not None:
        return float(lit)
    if not re.fullmatch(r'[0-9eE\.\+\-\*\/%\(\)\s]+', expr2):
        raise ValueError("数式に 関係ない 文字が 含まれています")
    val = eval(expr2, {"__builtins__": {}}, {})
    if isinstance(val, (int, float)):
        return float(val)
    raise ValueError("数式の 評価に 失敗しました")

def _logical_to_screen(x, y):
    xmin, xmax = _state["logical"]["xmin"], _state["logical"]["xmax"]
    ymin, ymax = _state["logical"]["ymin"], _state["logical"]["ymax"]
    lw = (xmax - xmin) or 1
    lh = (ymax - ymin) or 1
    W, H = _state["window_size"]
    sx = (x - xmin) * (W / lw)
    sy = H - (y - ymin) * (H / lh)
    return int(sx), int(sy)

def _apply_window_from_logical():
    xmin, xmax = _state["logical"]["xmin"], _state["logical"]["xmax"]
    ymin, ymax = _state["logical"]["ymin"], _state["logical"]["ymax"]
    ppu = max(int(_state.get("ppu", 2)), 1)

    lw = max((xmax - xmin), 1)
    lh = max((ymax - ymin), 1)
    new_size = (int(lw * ppu), int(lh * ppu))

    size_changed = tuple(new_size) != tuple(_state["window_size"])
    _state["window_size"] = new_size

    if size_changed and _state.get("screen") is not None:
        _state["screen"] = pygame.display.set_mode(new_size)
        pygame.display.set_caption("clage")

def _ensure_render_image(sp):
    base = sp.get("image")
    if base is None:
        sp["_render_img"] = None
        sp["_render_angle"] = None
        sp["_render_src"] = None
        return None

    angle = float(sp.get("direction", 90.0))
    snapped = int(round(angle))

    if (sp.get("_render_img") is None or
        sp.get("_render_angle") != snapped or
        sp.get("_render_src") is not base):
        rotated = pygame.transform.rotozoom(base, -(snapped - 90.0), 1.0)
        sp["_render_img"] = rotated
        sp["_render_angle"] = snapped
        sp["_render_src"] = base

    return sp["_render_img"]

def _sprite_rect(name: str):
    sp = _state["sprites"].get(name)
    if not sp:
        return None
    sx, sy = _logical_to_screen(sp["x"], sp["y"])
    img = _ensure_render_image(sp)
    if img is None:
        return pygame.Rect(sx - 25, sy - 25, 50, 50)
    return img.get_rect(center=(sx, sy))

def _is_touching(self_name: str, target: str) -> bool:
    if not _state.get("screen") or not _state.get("running", True):
        return False
    sp_self = _state["sprites"].get(self_name)
    if not sp_self or not sp_self.get("visible", True):
        return False
    r1 = _sprite_rect(self_name)
    if r1 is None:
        return False

    if str(target).lower() == "edge":
        W, H = _state["window_size"]
        return (r1.left <= 0 or r1.right >= W or r1.top <= 0 or r1.bottom >= H)

    tgt_name = str(target)
    candidates = []
    if tgt_name in _state["sprites"]:
        candidates.append(tgt_name)
    prefix = tgt_name + "#"
    for nm in _state["sprites"].keys():
        if nm.startswith(prefix):
            candidates.append(nm)

    if not candidates:
        return False

    for nm in candidates:
        sp_t = _state["sprites"].get(nm)
        if not sp_t or not sp_t.get("visible", True):
            continue
        r2 = _sprite_rect(nm)
        if r2 and r1.colliderect(r2):
            return True
    return False

_KEYMAP = {
    "right arrow": pygame.K_RIGHT,
    "left arrow": pygame.K_LEFT,
    "up arrow": pygame.K_UP,
    "down arrow": pygame.K_DOWN,
    "space": pygame.K_SPACE,
    "enter": pygame.K_RETURN,
    "shift": pygame.K_LSHIFT,
    "a": pygame.K_a, "s": pygame.K_s, "d": pygame.K_d, "w": pygame.K_w,
}

def _key_pressed(keyname: str) -> bool:
    if not _state.get("running", True):
        return False
    keys = pygame.key.get_pressed()
    code = _KEYMAP.get(str(keyname).lower().strip())
    return bool(code and keys[code])

def _sanitize_token(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1]
    return s

def _draw_frame():
    if _state["screen"] is None:
        return
    _state["screen"].fill((255, 255, 255))
    for name in _state["sprite_order"]:
        sp = _state["sprites"].get(name)
        if not sp or not sp.get("visible", True):
            continue
        sx, sy = _logical_to_screen(sp["x"], sp["y"])
        img = _ensure_render_image(sp)
        if img is None:
            pygame.draw.rect(_state["screen"], (180, 180, 180),
                             pygame.Rect(sx - 25, sy - 25, 50, 50))
        else:
            rect = img.get_rect(center=(sx, sy))
            _state["screen"].blit(img, rect.topleft)
    pygame.display.flip()

def _stop_all():
    if not _state.get("running", True):
        return
    _state["running"] = False
    try:
        if _state.get("screen") is not None:
            pygame.display.quit()
    except Exception:
        pass
    try:
        pygame.quit()
    except Exception:
        pass

def on_import():
    pygame.init()
    _state["clock"] = pygame.time.Clock()

    _state["stage_defined"] = False
    _state["block_stack"].clear()
    _state["sprites"].clear()
    _state["sprite_order"].clear()
    _state["logical"].update({"xmin": -240, "xmax": 240, "ymin": -180, "ymax": 180})
    _state["fps"] = 30
    _state["images_cache"].clear()
    _state["foreign_depth"] = 0
    _state["running"] = True

    _state["pending_to_clambon"].clear()
    _state["drain_cursor"] = 0

    _state["clone_scripts"].clear()
    _state["clone_counter"].clear()
    _state["clone_capture"] = None

    _state["globals"].clear()  # グローバル変数の初期化

    _apply_window_from_logical()
    _state["screen"] = pygame.display.set_mode(_state["window_size"])
    pygame.display.set_caption("clage")

def tick():
    if _state.get("screen") is None or not _state.get("running", True):
        return
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            _state["running"] = False
            try:
                pygame.quit()
            finally:
                return
    _draw_frame()
    if _state.get("clock"):
        _state["clock"].tick(max(_state.get("fps", 30), 1))

def drain_pending_lines():
    buf = _state.get("pending_to_clambon", [])
    cur = _state.get("drain_cursor", 0)
    n = _state.get("max_drain_per_frame", 64)
    if not buf:
        _state["drain_cursor"] = 0
        return []
    chunk = buf[cur:cur+n]
    cur += len(chunk)
    if cur >= len(buf):
        _state["pending_to_clambon"] = []
        _state["drain_cursor"] = 0
    else:
        _state["drain_cursor"] = cur
    return chunk

def _assign_global(name: str, rhs: str):
    rhs_s = rhs.strip()
    try:
        num = _eval_number_expr(rhs_s)
        _state["globals"][name] = num
        return
    except Exception:
        pass
    try:
        val = ast.literal_eval(rhs_s)
        _state["globals"][name] = val
        return
    except Exception:
        _state["globals"][name] = rhs_s

def process_line(line: str) -> str:
    stripped = line.strip()

    if stripped == "" or stripped.startswith("//") or stripped.startswith("import "):
        return line

    if _state["clone_capture"] is not None:
        cap = _state["clone_capture"]
        if stripped == "}":
            cap["depth"] -= 1
            if cap["depth"] == 0:
                _state["clone_scripts"][cap["owner"]] = cap["lines"]
                _state["clone_capture"] = None
            else:
                cap["lines"].append(line)
            return ""
        opens = line.count("{")
        closes = line.count("}")
        cap["lines"].append(line)
        cap["depth"] += (opens - closes)
        if cap["depth"] == 0:
            _state["clone_scripts"][cap["owner"]] = cap["lines"]
            _state["clone_capture"] = None
        return ""

    def _touching_eval_sub(m):
        self_name = m.group(1)
        target_tok = _sanitize_token(m.group(2))
        return "true" if _is_touching(self_name, target_tok) else "false"
    line = _RE_TOUCHING_CALL.sub(_touching_eval_sub, line)

    _RE_PRESSED_CALL = re.compile(r'\bpressed\s*\(\s*([^)]+)\s*\)')
    def _pressed_eval_sub(m):
        return "true" if _key_pressed(_sanitize_token(m.group(1))) else "false"
    line = _RE_PRESSED_CALL.sub(_pressed_eval_sub, line)

    m = _RE_STAGE_OPEN.match(line)
    if m:
        if _state["stage_defined"]:
            print('Stageエラー: Stage()は 1つだけ 宣言できます')
        else:
            _state["stage_defined"] = True
            _state["block_stack"].append("Stage")
            return "if ((true)) {"
        return ""

    m = _RE_SPRITE_OPEN.match(line)
    if m:
        name = m.group(1)
        if name in _state["sprites"]:
            print(f'Sprite名エラー: "{name}"は もう 使用されています')
            return ""
        _state["sprites"][name] = {"x": 0.0, "y": 0.0, "direction": 90.0,
                                   "costume": None, "image": None, "visible": True,
                                   "_render_img": None, "_render_angle": None, "_render_src": None}
        _state["sprite_order"].append(name)
        _state["block_stack"].append(f"Sprite:{name}")
        return "if ((true)) {"

    m = _RE_START_OPEN.match(line)
    if m:
        if not _state["block_stack"]:
            print("startエラー: Stageか Spriteの 中だけで 使えます")
            return ""
        _state["block_stack"].append("Start")
        return "if ((true)) {"

    m = _RE_CLONE_OPEN.match(line)
    if m:
        if not _in_sprite():
            print("cloneエラー: cloneブロックは Spriteの 中だけで 使えます")
            return ""
        sp_blocks = [b for b in _state["block_stack"] if b.startswith("Sprite:")]
        if not sp_blocks:
            print("cloneエラー: ブロックがありません）")
            return ""
        spname = sp_blocks[-1].split(":", 1)[1]
        _state["clone_capture"] = {"owner": spname, "depth": 1, "lines": []}
        return ""

    opens = line.count("{")
    closes = line.count("}")
    if opens or closes:
        _state["foreign_depth"] += opens
        for _ in range(closes):
            if _state["foreign_depth"] > 0:
                _state["foreign_depth"] -= 1
            elif _state["block_stack"]:
                _state["block_stack"].pop()
        return line

    m = _RE_FPS_SET.match(line)
    if m:
        if not _in_stage():
            print("fpsは Stageの 中だけで 使えます")
            return ""
        v = _to_int_literal(m.group(1))
        if v is None:
            print("fps: 整数を 指定してください")
            return ""
        _state["fps"] = max(int(v), 1)
        return ""

    m = _RE_WIDTH_SET.match(line)
    if m:
        if not _in_stage():
            print("widthは Stageの 中だけで 使えます")
            return ""
        a = _to_int_literal(m.group(1)); b = _to_int_literal(m.group(2))
        if a is None or b is None or not (a < b):
            print("width: min<maxの 整数を 使ってください")
            return ""
        _state["logical"]["xmin"] = int(a)
        _state["logical"]["xmax"] = int(b)
        _apply_window_from_logical()
        return ""

    m = _RE_HEIGHT_SET.match(line)
    if m:
        if not _in_stage():
            print("heightは Stageの 中だけで 使えます")
            return ""
        a = _to_int_literal(m.group(1)); b = _to_int_literal(m.group(2))
        if a is None or b is None or not (a < b):
            print("height: min<maxの 整数を 使ってください")
            return ""
        _state["logical"]["ymin"] = int(a)
        _state["logical"]["ymax"] = int(b)
        _apply_window_from_logical()
        return ""

    m = _RE_RUN.match(line)
    if m:
        return ""

    m = _RE_STOP_ALL.match(line)
    if m:
        _stop_all()
        return ""

    m = _RE_STOP_ALIAS.match(line)
    if m:
        _stop_all()
        return ""

    m = _RE_PROP_SET.match(line)
    if m:
        spr, prop, rhs = m.group(1), m.group(2), m.group(3).strip()
        if spr not in _state["sprites"]:
            print(f'Sprite参照エラー: "{spr}"は 宣言されていません')
            return ""
        sp = _state["sprites"][spr]
        if prop in ("x", "y", "direction"):
            try:
                sp[prop] = float(_eval_number_expr(rhs))
            except Exception:
                print(f"{spr}.{prop}: 数値式を 指定してください")
            return ""
        if prop == "costume":
            s = _to_string_literal(rhs)
            if s is None:
                print(f'{spr}: "画像ファイル名"で 指定してください')
                return ""
            sp["costume"] = s
            img = _load_image(s)
            if img is None:
                print(f'costumeエラー: "{s}"を 読み込めません')
                sp["image"] = None
            else:
                sp["image"] = img
                sp["_render_img"] = None
                sp["_render_src"] = None
            return ""

    m = _RE_CLONE_CMD.match(line)
    if m:
        src = m.group(1)
        if src not in _state["sprites"]:
            print(f'クローンエラー: "{src}"は 宣言されていません')
            return ""
        num = _state["clone_counter"].get(src, 0) + 1
        _state["clone_counter"][src] = num
        cname = f"{src}#{num}"

        base = _state["sprites"][src]
        copied = dict(base)
        copied["is_clone"] = True
        copied["_render_img"] = None
        copied["_render_angle"] = None
        copied["_render_src"] = None

        _state["sprites"][cname] = copied
        _state["sprite_order"].append(cname)

        templ = _state["clone_scripts"].get(src)
        if templ:
            pat_clone_ident = re.compile(r'\bclone\b')
            _state["pending_to_clambon"].append(f'__clage_sprite_ctx_open__("{cname}")')
            for ln in templ:
                ln2 = ln
                if "clone.delete()" in ln2:
                    ln2 = ln2.replace("clone.delete()", f'__clage_clone_delete__("{cname}")')
                ln2 = pat_clone_ident.sub(cname, ln2)
                _state["pending_to_clambon"].append(ln2)
            _state["pending_to_clambon"].append('__clage_sprite_ctx_close__()')
        return ""

    m = _RE_MOVE_CMD.match(line)
    if m:
        spr_name, val = m.group(1), m.group(2)
        if spr_name not in _state["sprites"]:
            print(f'Sprite参照エラー: "{spr_name}"は 宣言されていません')
            return ""
        if not _in_sprite():
            print(f"{spr_name}.moveは Spriteの ブロックの中 だけで 使えます")
            return ""
        try:
            dist = _eval_number_expr(val)
        except Exception:
            print(f"{spr_name}.move: 数値を 指定してください")
            return ""
        sp = _state["sprites"][spr_name]
        rad = math.radians(float(sp["direction"]))
        sp["x"] += float(dist) * math.sin(rad)
        sp["y"] += float(dist) * math.cos(rad)
        return ""

    m = _RE_INTERNAL_CLONE_DELETE.match(line)
    if m:
        target = m.group(1)
        _state["sprites"].pop(target, None)
        try:
            _state["sprite_order"].remove(target)
        except ValueError:
            pass
        return ""

    m = _RE_INTERNAL_SPRITE_CTX_OPEN.match(line)
    if m:
        nm = m.group(1)
        if nm not in _state["sprites"]:
            print(f'内部エラー: Sprite "{nm}"が ありません')
            return ""
        _state["block_stack"].append(f"Sprite:{nm}")
        return "if ((true)) {"

    m = _RE_INTERNAL_SPRITE_CTX_CLOSE.match(line)
    if m:
        for i in range(len(_state["block_stack"]) - 1, -1, -1):
            if _state["block_stack"][i].startswith("Sprite:"):
                _state["block_stack"].pop(i)
                break
        return "}"

    m = _RE_SHOW_CMD.match(line)
    if m:
        spr_name = m.group(1)
        sp = _state["sprites"].get(spr_name)
        if not sp:
            print(f'Sprite参照エラー: "{spr_name}"は 宣言されていません')
            return ""
        sp["visible"] = True
        return ""

    m = _RE_HIDE_CMD.match(line)
    if m:
        spr_name = m.group(1)
        sp = _state["sprites"].get(spr_name)
        if not sp:
            print(f'Sprite参照エラー: "{spr_name}"は 宣言されていません')
            return ""
        sp["visible"] = False
        return ""

    m = _RE_VAR_DECL.match(line)
    if m:
        name, rhs = m.group(1), m.group(2)
        _assign_global(name, rhs)
        return line

    m = _RE_ASSIGN.match(line)
    if m:
        name, rhs = m.group(1), m.group(2)
        _assign_global(name, rhs)
        return line

    if not _state["block_stack"]:
        print("エラー: コードは Stage()か Sprite()の 中だけに 書けます")
        return ""

    return line
