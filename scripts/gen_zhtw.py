"""產生 easyread/web/i18n/zh-TW.json：繁體中文（台灣用語）界面詞典。

    python scripts/gen_zhtw.py            # 轉換 + 套用 scripts/zhtw_overrides.json，寫出 zh-TW.json
    python scripts/gen_zhtw.py --diff     # 另外印出「詞組轉換 s2twp 與逐字轉換 s2tw 結果不同」的詞條，供人工複核

鍵：en.json 的所有鍵（簡體中文原文）。值：OpenCC s2twp（台灣詞彙）轉換結果，再套人工修正。
OpenCC 只在產生詞典時需要（pip install opencc-python-reimplemented 或 opencc），執行期不需要，也不在 pyproject.toml 裡。
人工修正寫在 scripts/zhtw_overrides.json（鍵 → 值），以後 en.json 新增詞條時重跑本腳本即可。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = ROOT / "easyread" / "web" / "i18n" / "en.json"
OUT = ROOT / "easyread" / "web" / "i18n" / "zh-TW.json"
OVERRIDES = ROOT / "scripts" / "zhtw_overrides.json"

# 台灣標點慣例：引號用「」，內層用『』（OpenCC 不處理這個）
_QUOTE = str.maketrans({"“": "「", "”": "」", "‘": "『", "’": "』"})


# OpenCC s2twp 之後的台灣用語修正（逐條複核過，見 CHANGELOG / 報告）：(正則, 取代)。
# 順序有關：前面的先套。針對單一詞條的修正不要寫在這裡，寫進 zhtw_overrides.json。
TERM_FIXES = [
    (r"後臺", "背景"),                      # 後台處理 → 「背景」執行，避免被讀成「後臺/後台管理」
    (r"(?<=[一二兩幾另換每])臺", "台"),      # 兩臺電腦 → 兩台電腦
    (r"釋出", "發布"),                       # release：發布
    (r"梯子（VPN）", "VPN"),
    (r"梯子", "VPN"),                        # 「梯子」是中國大陸說法
    (r"國內", "中國大陸"),
    (r"賬", "帳"),
    (r"許可權", "權限"),                     # OpenCC 把「权限」誤轉成「許可權」
    (r"聯絡", "關聯"),                       # 「联系」在這裡是「關聯」，不是「聯絡」
    (r"全域性", "全域"),
    (r"高階", "進階"),                       # 高级設定 = 進階設定
    (r"繫結", "綁定"),
    (r"流資料", "串流資料"),
    (r"熒光", "螢光"),
    (r"實時", "即時"),
    (r"(?<!百度)網盤", "雲端硬碟"),          # 品牌「百度網盤」保留
    (r"客戶端", "用戶端"),
    (r"頂欄", "頂部列"),
    (r"預印本型別", "預印本類型"),
    (r"型別不對", "類型不對"),
    (r"新傳送", "新輸入"),
    (r"雙擊", "按兩下"),
    (r"下劃線", "底線"),
    (r"自定義", "自訂"),
    (r"構建", "建置"),
    (r"回收站", "資源回收筒"),
    (r"宋體", "明體"),                       # 字型名：宋體 → 明體（台灣叫法）
    (r"(?<=[一-鿿])VPN", " VPN"),            # 中英文之間留空格，和「梯子」改成 VPN 之後的排版一致
    (r"VPN(?=[一-鿿])", "VPN "),
]


def converters():
    try:
        from opencc import OpenCC
    except ImportError:
        sys.exit("需要 OpenCC：pip install opencc-python-reimplemented（只在產生詞典時用，不是執行期依賴）")
    return OpenCC("s2twp"), OpenCC("s2tw")


def convert(text: str, phrase, fix: bool = True) -> str:
    out = phrase.convert(text)
    # 英文單引號/撇號不動：只換成對出現在中文旁邊的彎引號
    if re.search(r"[“”]", out):
        out = out.translate({ord("“"): "「", ord("”"): "」"})
    if re.search(r"[‘’]", out) and re.search(r"[一-鿿]", out):
        out = re.sub(r"‘([^’]*[一-鿿][^’]*)’", r"『\1』", out)
    if fix:
        for pattern, repl in TERM_FIXES:
            out = re.sub(pattern, repl, out)
    return out


def main() -> int:
    keys = list(json.loads(EN.read_text(encoding="utf-8")))
    overrides = json.loads(OVERRIDES.read_text(encoding="utf-8")) if OVERRIDES.exists() else {}
    unknown = [k for k in overrides if k not in keys]
    if unknown:
        sys.exit(f"overrides 裡有 en.json 沒有的鍵（{len(unknown)} 個），例如：{unknown[:3]}")
    phrase, char = converters()
    out: dict[str, str] = {}
    diffs = []
    for k in keys:
        auto = convert(k, phrase)
        out[k] = overrides.get(k, auto)
        if "--diff" in sys.argv:
            plain, raw = convert(k, char, False), convert(k, phrase, False)
            if plain != raw:
                diffs.append((k, plain, raw, out[k]))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"寫出 {OUT.relative_to(ROOT)}：{len(out)} 條，人工修正 {len(overrides)} 條")
    for k, plain, auto, final in diffs:
        print(json.dumps({"key": k, "s2tw": plain, "s2twp": auto, "final": final}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
