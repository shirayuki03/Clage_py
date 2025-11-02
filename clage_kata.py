import re

KATA2EN = {
    "セット": "set",
    "ウィドゥス": "width",
    "ヘイト": "height",
    "ラン": "run",

    "ステージ": "Stage",
    "スプライト": "Sprite",
    "スタート": "start",
    "フォーエバー": "forever",

    "ムーブ": "move",
    "ディレクション": "direction",
    "コスチューム": "costume",
    "タッチング": "touching",
    "プレスド": "pressed",

    "ショー": "show",
    "ハイド": "hide",
    "デリート": "delete",

    "エッヂ": "edge",
    "エッジ": "edge",

    "ストップ": "stop",
    "オール": "all",
}

_STR_SPLIT_RE = re.compile(r'(".*?"|\'.*?\')', re.DOTALL)

STRING_KEY_REPLACES = [
    ("ライトアロー", "right arrow"),
    ("レフトアロー", "left arrow"),
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
        for kata, en in KATA2EN.items():
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
