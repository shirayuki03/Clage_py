import re

JP2EN = {
    "設定": "set",
    "横幅": "width",
    "縦幅": "height",
    "実行": "run",

    "ステージ": "Stage",
    "スプライト": "Sprite",
    "スタート": "start",
    "ずっと": "forever",

    "動かす": "move",
    "向き": "direction",
    "コスチューム": "costume",
    "触れた": "touching",
    "押された": "pressed",

    "表示する": "show",
    "隠す": "hide",
    "削除する": "delete",

    "端": "edge",

    "停止": "stop",
    "すべて": "all",
}

_STR_SPLIT_RE = re.compile(r'(".*?"|\'.*?\')', re.DOTALL)

STRING_KEY_REPLACES = [
    ("右向き矢印キー", "right arrow"),
    ("左向き矢印キー", "left arrow"),
]

def _apply_clone_specials(line: str) -> str:
    line = re.sub(r'^\s*クローン\s*\{', 'clone {', line)
    line = re.sub(r'(?<!\w)クローン(?=\.)', 'clone', line)
    line = re.sub(r'(?<!\w)クローン(?=\s*\()', 'clone', line)
    return line

def _replace_outside_strings(line: str) -> str:
    parts = _STR_SPLIT_RE.split(line)
    for i in range(0, len(parts), 2):
        seg = parts[i]
        for kata, en in JP2EN.items():
            seg = re.sub(r'(?<!\w)' + re.escape(kata) + r'(?!\w)', en, seg)
        parts[i] = seg
    return "".join(parts)

def process_line(line: str) -> str:
    stripped = line.strip()
    if stripped == '' or stripped.startswith('//'):
        return line

    for src, dst in STRING_KEY_REPLACES:
        if src in line:
            line = line.replace(src, dst)

    line = _apply_clone_specials(line)

    return _replace_outside_strings(line)

def on_import():
    try:
        import sys
        clambon = sys.modules.get('clambon')
        me = sys.modules.get(__name__)
        if clambon and me:
            lst = getattr(clambon, 'active_extensions', None)
            if isinstance(lst, list) and me in lst:
                lst.remove(me)
                lst.insert(0, me)
    except Exception:
        pass
