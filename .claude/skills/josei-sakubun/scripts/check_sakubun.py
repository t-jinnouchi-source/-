#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
助成金作文（訓練必要性説明文）の機械チェック。

「禁止語チェック済み」を文章で書くのではなく、実行結果で示すための道具。
納品前に必ず実行し、全項目 PASS になるまで戻る。

使い方:
  python3 check_sakubun.py --file 作文_営業.txt --min 450 --max 583
  python3 check_sakubun.py --file 作文_営業.txt --max 583 \
      --ng-extra 案件固有禁止語.txt --cross 作文_工場.txt 作文_業務.txt
  python3 check_sakubun.py --file 作文_営業.txt --max 583 --json

判定:
  LENGTH     改行・空白を除く実字数が器に収まっているか
  STRUCTURE  支給要領0303ヘ(ロ) (1)(2)(3) が第1段落に揃っているか
  NG_R8      令和8年8月3日改正で対象外となった語
  NG_HYO1_4  表1(4) 接触語（通常の事業活動・マニュアル作成・経営改善指導）
  NG_PROMISE 成果約束語
  NG_LEGACY  旧型作文の頻出語
  NG_EXTRA   案件固有禁止語（前年度作文からの抽出）
  JARGON     平語に開くべき語
  NUMERIC    人数・時間数・回数・講座番号の本文混入
  KARI       演習題材に「仮題」が冠されているか／実データ使用の記述がないか
  CROSS      他部門・他案件の作文との共通表現（15字以上の一致）

終了コード: 0 = 全項目 PASS / 1 = high の FAIL あり / 2 = medium 以下の FAIL のみ
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------- 禁止語定義
# references/03_ng-words.md と対応。ここが正。

NG_R8 = [
    "AIリテラシー", "情報リテラシー", "ITリテラシー", "デジタルリテラシー", "リテラシー",
    "意識の向上", "意識向上", "意識改革", "一人ひとりの意識",
    "基礎知識", "基本知識", "基礎的な知識", "基本概念",
    "概論", "入門", "初歩", "事例紹介", "活用事例の紹介",
    "操作方法", "基本操作", "使い方",
    "生成AIとは", "DXとは",
    "一般教養", "ビジネスマナー", "コンプライアンス研修",
]

NG_HYO1_4 = [
    "標準化",
    "マニュアルの作成", "マニュアル等の作成", "手順書の整備", "規程の整備",
    "社内基準", "基準を自社で", "判定の基準を定め", "ルールを定め",
    "体制を定着", "体制を構築", "体制を確立", "仕組みを構築", "仕組みづくり",
    "運用し続ける", "見直し続ける体制",
    "外注に頼らず", "内製化", "自社で組み立て",
    "業務改善の指導", "業務プロセスの改善", "経営改善",
    "情報基盤の構築", "一元管理の仕組み",
]

NG_PROMISE = [
    "競争力を強化", "競争力の強化",
    "生産性向上を実現", "生産性が抜本的に",
    "成約率の向上", "受注率の向上", "売上の向上", "売上アップ",
    "コスト削減が実現", "コストの大幅な削減", "大幅な削減",
    "劇的に削減", "大幅に短縮", "半減", "飛躍",
    "創出された時間", "創出した時間",
    "期待できます",
]

NG_LEGACY = [
    "属人化", "属人的", "経験や勘", "センスに頼らない",
    "不可欠です", "急務です", "生命線", "鍵を握",
    "ハルシネーション", "セキュリティリテラシー",
    "情報漏洩を防ぐ", "情報漏えいが許されない", "セキュリティ強化", "防御力",
    "信頼を守り", "事業の継続性を確保",
    "超速", "抜本的",
]

# JARGON: (検出語, 置換案)
JARGON = [
    ("粒度", "細かさ／どこまで書くか"),
    ("工程モデル", "業務の工程／進め方（カリキュラム表の正式項目名なら引用可）"),
    ("ソリューション", "解決／手段"),
    ("リスキリング", "コース名としてのみ可"),
    ("DX人材", "17欄の区分名としてのみ可"),
    ("アセット", "資産"),
    ("ステークホルダー", "関係者／取引先"),
    ("ボトルネック", "滞り／詰まり"),
    ("ドキュメント", "文書／書類"),
    ("フォーマット", "様式／書式"),
    ("オペレーション", "業務／作業"),
    ("三項目", "3項目（表記統一）"),
    ("三つに分けて", "3つに分けて（表記統一）"),
]

# 実データ使用＝表2-7 就労の場での訓練に読まれる
JITSU_DATA = [
    "実際の業務データ", "実際のデータ", "自社の実帳票を用い", "実帳票を用い",
    "当社の業務の流れに沿って", "の流れに沿って習得", "実際の案件を用い",
    "自社の実データ",
]

# NUMERIC: 本文に書いてはいけない数値情報
NUMERIC_PATTERNS = [
    (r"[0-9０-９]+\s*名", "受講人数（7欄・17欄の記載事項）"),
    (r"[0-9０-９]+\s*時間", "訓練時間数（カリキュラム表・時間割の記載事項）"),
    (r"全\s*[0-9０-９]+\s*回", "訓練回数（カリキュラム表の記載事項）"),
    (r"第\s*[0-9０-９]+\s*回", "講座番号（カリキュラム表の記載事項）"),
    (r"[①②③④⑤⑥⑦⑧⑨⑩]", "講座番号（カリキュラム表の記載事項）"),
    (r"ISO\s*[0-9]+", "未確認の認証名"),
    (r"創業\s*[0-9０-９]+\s*年", "沿革の年数（年をまたぐとずれる）"),
]

# STRUCTURE: 0303ヘ(ロ) の3要素を第1段落から検出するための手掛かり
STRUCT_1_DX = [  # (1) 事業主が進めるDX化の取組
    "デジタル", "電子データ", "電子化", "DX", "生成AI", "ITツール", "ITシステム",
]
STRUCT_2_TAISHO = [  # (2) これに関連する業務に従事させる対象労働者
    "従事し", "従事する", "担当者は", "対象は", "担当する者",
]
STRUCT_3_GINOU = [  # (3) その上で必要な専門的な知識及び技能
    "専門的な知識及び技能",
]

SEVERITY = {
    "LENGTH": "high",
    "STRUCTURE": "high",
    "NG_R8": "high",
    "NG_HYO1_4": "high",
    "NG_EXTRA": "high",
    "KARI": "high",
    "FOREIGN_OBJ": "high",
    "NG_PROMISE": "medium",
    "NG_LEGACY": "medium",
    "NUMERIC": "medium",
    "CROSS": "medium",
    "JARGON": "low",
}


# ---------------------------------------------------------------- ユーティリティ

def real_len(text: str) -> int:
    """改行・空白（全角含む）を除いた実字数。様式の記入枠に入るかの判定用。"""
    return len([c for c in text if not c.isspace() and c != "　"])


def normalize(text: str) -> str:
    """比較用の正規化。全角英数→半角、大文字小文字を揃える。"""
    return unicodedata.normalize("NFKC", text).lower()


def strip_meta(text: str) -> str:
    """納品メモ・区切り線・見出しなど、本文でない部分を落とす。

    「────」以降、および行頭 '#' の見出し行を除外する。
    """
    cut = re.split(r"^[─―—\-=]{8,}\s*$", text, flags=re.M)[0]
    lines = []
    for ln in cut.splitlines():
        s = ln.strip()
        if s.startswith("#"):
            continue
        lines.append(ln)
    return "\n".join(lines)


# 訓練名の行を落とすための判定。訓練名は様式の別欄に書くもので、
# 4欄の記入枠の字数には含めない。ここを数えると器の判定が数十字ずれる。
TITLE_RE = re.compile(r"^\s*(?:[０-９0-9]+[．.、]\s*)?(?:【[^】]{1,30}】)?[^。\n]{0,60}(?:研修|訓練|編)\s*$")


def strip_title(text: str):
    """先頭の訓練名行を落とす。落とした行を第2要素で返す。"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        if "。" not in ln and TITLE_RE.match(ln.strip()):
            return "\n".join(lines[:i] + lines[i + 1:]), ln.strip()
        break
    return text, None


def paragraphs(text: str):
    """空行区切りの段落に分割。空行がなければ全体を1段落として返す。"""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return parts if parts else [text.strip()]


# 第2段落の書き出し。ここまでが第1段落＝0303ヘ(ロ)の3要素を置く範囲。
P2_MARKERS = ["本研修では", "本訓練では", "本講座では", "研修では、", "訓練では、"]


def opening_block(text: str) -> str:
    """0303ヘ(ロ)の3要素を探す範囲＝訓練内容の記述が始まる前まで。

    空行の入れ方が版によって違う（訓練名の後で切る／第1文の後で切る）ため、
    段落分割ではなく「本研修では」等のマーカーで切る。マーカーがなければ
    第1段落、それも取れなければ先頭45%を使う。
    """
    pos = [text.find(m) for m in P2_MARKERS]
    pos = [p for p in pos if p > 0]
    if pos:
        return text[:min(pos)]
    paras = paragraphs(text)
    if len(paras) >= 2:
        return paras[0]
    return text[:max(1, int(len(text) * 0.45))]


def find_all(text: str, words):
    """禁止語の検出。正規化テキスト上で探し、元の語を返す。"""
    norm = normalize(text)
    hits = []
    for w in words:
        if normalize(w) in norm:
            hits.append(w)
    return hits


def common_substrings(a: str, b: str, min_len: int = 15):
    """a と b の共通部分文字列（min_len 以上）を返す。作文間の使い回し検出用。"""
    a_c = re.sub(r"\s+", "", a)
    b_c = re.sub(r"\s+", "", b)
    found = set()
    n = len(a_c)
    i = 0
    while i <= n - min_len:
        # i から始まる最長一致を探す
        length = min_len
        best = None
        while i + length <= n and a_c[i:i + length] in b_c:
            best = a_c[i:i + length]
            length += 1
        if best:
            found.add(best)
            i += len(best)
        else:
            i += 1
    # 他の一致に包含されるものを落とす
    out = []
    for s in sorted(found, key=len, reverse=True):
        if not any(s in t for t in out):
            out.append(s)
    return out


# ---------------------------------------------------------------- チェック本体

def check(body: str, args, extra_ng, cross_texts):
    results = []

    def add(name, ok, detail):
        results.append({
            "check": name,
            "severity": SEVERITY[name],
            "status": "PASS" if ok else "FAIL",
            "detail": detail,
        })

    # LENGTH（訓練名の行は別欄の記載事項なので数えない）
    n = real_len(body)
    lo, hi = args.min, args.max
    ok = (lo is None or n >= lo) and (hi is None or n <= hi)
    rng = f"{lo if lo is not None else '-'}〜{hi if hi is not None else '-'}"
    add("LENGTH", ok, f"実字数 {n} 字（器 {rng} 字／訓練名の行は除外）")

    # STRUCTURE
    p1 = opening_block(body)
    s1 = bool(find_all(p1, STRUCT_1_DX))
    s2 = bool(find_all(p1, STRUCT_2_TAISHO))
    s3 = bool(find_all(p1, STRUCT_3_GINOU))
    miss = []
    if not s1:
        miss.append("(1)事業主が進めるDX化の取組")
    if not s2:
        miss.append("(2)対象労働者と従事業務 ← 最頻の欠落")
    if not s3:
        miss.append("(3)必要な専門的な知識及び技能（条文語をそのまま使う）")
    add("STRUCTURE", not miss,
        "第1段落に0303ヘ(ロ)の3要素あり" if not miss else "第1段落に不足: " + " / ".join(miss))

    # 宙に浮いた指示語（(2)欠落の典型的な副作用）
    if not s2 and re.search(r"(同担当者|当該担当者|同部門の担当者)", body):
        results.append({
            "check": "STRUCTURE", "severity": "high", "status": "FAIL",
            "detail": "「同担当者」等の指示語があるが、対象労働者を特定する文が第1段落にない（指示対象が本文中に存在しない）",
        })

    # 禁止語
    for name, words in (("NG_R8", NG_R8), ("NG_HYO1_4", NG_HYO1_4),
                        ("NG_PROMISE", NG_PROMISE), ("NG_LEGACY", NG_LEGACY)):
        hits = find_all(body, words)
        add(name, not hits, "0件" if not hits else f"{len(hits)}件: " + " / ".join(hits))

    # 案件固有禁止語
    if extra_ng:
        hits = find_all(body, extra_ng)
        add("NG_EXTRA", not hits,
            f"0件（{len(extra_ng)}語で照合）" if not hits else f"{len(hits)}件: " + " / ".join(hits))
    else:
        results.append({
            "check": "NG_EXTRA", "severity": "high", "status": "SKIP",
            "detail": "案件固有禁止語が未指定。過去の計画届から抽出して --ng-extra で渡すこと",
        })

    # JARGON
    jhits = [f"{w}→{alt}" for w, alt in JARGON if normalize(w) in normalize(body)]
    add("JARGON", not jhits, "0件" if not jhits else f"{len(jhits)}件: " + " / ".join(jhits))

    # NUMERIC
    nhits = []
    for pat, why in NUMERIC_PATTERNS:
        for m in re.findall(pat, body):
            nhits.append(f"{m}（{why}）")
    add("NUMERIC", not nhits, "0件" if not nhits else f"{len(nhits)}件: " + " / ".join(nhits))

    # KARI（仮題ルール）
    jd = find_all(body, JITSU_DATA)
    has_kari = "仮題" in body or "訓練用の" in body
    detail = []
    if jd:
        detail.append("実データ使用の記述: " + " / ".join(jd))
    if not has_kari:
        detail.append("「仮題の◯◯」が本文にない（演習題材が仮題であることを示す必要がある）")
    add("KARI", not detail, "仮題ルールOK" if not detail else " ／ ".join(detail))

    # FOREIGN_OBJ（他部門の対象物語の混入）— 部門別3本を同時提出するときの本丸
    if args.foreign_objects:
        fo = find_all(body, args.foreign_objects)
        add("FOREIGN_OBJ", not fo,
            f"0件（{len(args.foreign_objects)}語で照合）" if not fo
            else f"{len(fo)}件の他部門語が混入: " + " / ".join(fo))
    else:
        results.append({
            "check": "FOREIGN_OBJ", "severity": "high", "status": "SKIP",
            "detail": "他部門の対象物語が未指定。部門別に複数本出す場合は --foreign-objects で渡すこと",
        })

    # CROSS
    if cross_texts:
        all_hits = []
        for label, other in cross_texts:
            for s in common_substrings(body, other, args.cross_min):
                all_hits.append(f"[{label}] 「{s}」({len(s)}字)")
        if args.cross_mode == "dept":
            # 同一社の部門別。共通フレームは「同一社の書類として自然」なので許容し、
            # 対象物語の混入は FOREIGN_OBJ が high で拾う。
            add("CROSS", not all_hits,
                f"0件（{len(cross_texts)}本と照合）" if not all_hits
                else f"{len(all_hits)}件の共通表現（同一社の部門別なら共通フレームは許容。"
                     f"課題語・着地の指標が重なっていないかを目視で確認）: " + " / ".join(all_hits))
        else:
            add("CROSS", not all_hits,
                f"0件（{len(cross_texts)}本と照合）" if not all_hits
                else f"{len(all_hits)}件の共通表現（別会社への使い回しに読まれる。全て潰すこと）: "
                     + " / ".join(all_hits))
    else:
        results.append({
            "check": "CROSS", "severity": SEVERITY["CROSS"], "status": "SKIP",
            "detail": "比較対象が未指定。同時提出する他部門・他案件の作文を --cross で渡すこと",
        })

    return results


# ---------------------------------------------------------------- 出力

MARK = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}


def render(path, results, body, title=None):
    lines = []
    lines.append("=" * 72)
    lines.append(f"助成金作文チェック: {path}")
    if title:
        lines.append(f"訓練名（字数から除外）: {title}")
    lines.append(f"実字数（改行・空白を除く）: {real_len(body)} 字")
    lines.append("=" * 72)
    width = max(len(r["check"]) for r in results)
    for r in results:
        lines.append(f'[{MARK[r["status"]]}] {r["check"]:<{width}}  ({r["severity"]})  {r["detail"]}')
    lines.append("-" * 72)
    fails = [r for r in results if r["status"] == "FAIL"]
    highs = [r for r in fails if r["severity"] == "high"]
    skips = [r for r in results if r["status"] == "SKIP"]
    if not fails and not skips:
        lines.append("判定: 全項目 PASS。納品可。")
    elif not fails:
        lines.append(f"判定: FAIL なし。ただし SKIP {len(skips)} 件（未指定の照合あり）。")
    else:
        lines.append(f"判定: FAIL {len(fails)} 件（うち high {len(highs)} 件）。修正して再実行。")
        if highs:
            lines.append("  high の FAIL は不支給・否認に直結する。必ず潰すこと。")
    lines.append("=" * 72)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="助成金作文の機械チェック")
    ap.add_argument("--file", required=True, help="チェックする作文のテキストファイル")
    ap.add_argument("--min", type=int, default=None, help="器の下限字数")
    ap.add_argument("--max", type=int, default=None, help="器の上限字数（様式の記入枠の実測値）")
    ap.add_argument("--ng-extra", default=None, help="案件固有禁止語ファイル（1行1語）")
    ap.add_argument("--cross", nargs="*", default=[], help="重複照合する他の作文ファイル")
    ap.add_argument("--cross-min", type=int, default=15, help="重複とみなす最小一致文字数")
    ap.add_argument("--cross-mode", choices=["dept", "client"], default="dept",
                    help="dept=同一社の部門別（共通フレームは許容）／client=別会社（全て潰す）")
    ap.add_argument("--foreign-objects", default=None,
                    help="他部門の対象物語ファイル（1行1語）。混入していたら high の FAIL")
    ap.add_argument("--keep-title", action="store_true",
                    help="先頭の訓練名行を字数に含める（訓練名も同じ欄に書く様式の場合）")
    ap.add_argument("--raw", action="store_true", help="納品メモを除去せず全文をチェック")
    ap.add_argument("--json", action="store_true", help="JSON で出力")
    args = ap.parse_args()

    def load_body(path):
        t = Path(path).read_text(encoding="utf-8")
        if not args.raw:
            t = strip_meta(t)
        title = None
        if not args.keep_title:
            t, title = strip_title(t)
        return t, title

    body, title = load_body(args.file)

    extra_ng = []
    if args.ng_extra:
        extra_ng = [l.strip() for l in Path(args.ng_extra).read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.strip().startswith("#")]

    if args.foreign_objects:
        args.foreign_objects = [
            l.strip() for l in Path(args.foreign_objects).read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")]
    else:
        args.foreign_objects = []

    cross_texts = []
    for p in args.cross:
        t, _ = load_body(p)
        cross_texts.append((Path(p).name, t))

    results = check(body, args, extra_ng, cross_texts)

    if args.json:
        print(json.dumps({
            "file": args.file,
            "title_excluded": title,
            "real_length": real_len(body),
            "results": results,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(args.file, results, body, title))

    fails = [r for r in results if r["status"] == "FAIL"]
    if any(r["severity"] == "high" for r in fails):
        return 1
    if fails:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
