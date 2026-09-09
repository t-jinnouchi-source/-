#!/usr/bin/env bash
# 助成金作文チェッカーの回帰テスト。
# スクリプトや禁止語リストを更新したら必ず実行し、全ケースが期待どおりになることを確認する。
#
#   bash .claude/skills/josei-sakubun/eval/run_eval.sh
#
# fixtures は実案件の作文ではなく、実案件で観測した欠陥パターンを再現した合成データ。

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="$HERE/../scripts/check_sakubun.py"
FIX="$HERE/fixtures"
PASS=0
FAIL=0

expect() { # expect <期待exit> <ラベル> <コマンド...>
  local want="$1"; shift
  local label="$1"; shift
  local out; out="$("$@" 2>&1)"; local got=$?
  if [[ "$got" == "$want" ]]; then
    echo "  ok   $label (exit=$got)"
    PASS=$((PASS+1))
  else
    echo "  NG   $label (期待 exit=$want / 実際 exit=$got)"
    echo "$out" | sed 's/^/       /'
    FAIL=$((FAIL+1))
  fi
}

expect_contains() { # expect_contains <含まれるべき文字列> <ラベル> <コマンド...>
  local needle="$1"; shift
  local label="$1"; shift
  local out; out="$("$@" 2>&1)"
  if grep -qF -- "$needle" <<<"$out"; then
    echo "  ok   $label"
    PASS=$((PASS+1))
  else
    echo "  NG   $label — 「$needle」が出力にない"
    echo "$out" | sed 's/^/       /'
    FAIL=$((FAIL+1))
  fi
}

echo "== 1. 正しく書けた作文は全項目 PASS になること =="
expect 0 "ok_3dan は exit 0" \
  python3 "$CHECK" --file "$FIX/ok_3dan.txt" --min 450 --max 583 \
    --ng-extra "$FIX/ng_extra_sample.txt" --foreign-objects "$FIX/foreign_objects_sample.txt"

echo "== 2. 0303ヘ(ロ)②の欠落を検出すること（実案件で最終版に混入した欠陥） =="
expect 1 "ng_taisho_ketsuraku は exit 1" \
  python3 "$CHECK" --file "$FIX/ng_taisho_ketsuraku.txt" --max 583
expect_contains "(2)対象労働者と従事業務" "②の欠落を名指しする" \
  python3 "$CHECK" --file "$FIX/ng_taisho_ketsuraku.txt" --max 583
expect_contains "指示対象が本文中に存在しない" "宙に浮いた「同担当者」を検出する" \
  python3 "$CHECK" --file "$FIX/ng_taisho_ketsuraku.txt" --max 583

echo "== 3. 表1(4)接触語のリグレッションを検出すること =="
expect_contains "標準化" "「標準化」を検出する" \
  python3 "$CHECK" --file "$FIX/ng_taisho_ketsuraku.txt" --max 583

echo "== 4. 平語に開くべき語を検出すること =="
expect_contains "粒度" "「粒度」を検出する" \
  python3 "$CHECK" --file "$FIX/ng_taisho_ketsuraku.txt" --max 583

echo "== 5. 旧型作文（R8.8.3以前の型）を high で落とすこと =="
expect 1 "ng_kyuugata は exit 1" \
  python3 "$CHECK" --file "$FIX/ng_kyuugata.txt" --max 583
expect_contains "リテラシー" "R8.8.3対象外語を検出する" \
  python3 "$CHECK" --file "$FIX/ng_kyuugata.txt" --max 583
expect_contains "創出された時間" "成果約束語を検出する" \
  python3 "$CHECK" --file "$FIX/ng_kyuugata.txt" --max 583
expect_contains "実データ使用の記述" "実データ使用（表2-7）を検出する" \
  python3 "$CHECK" --file "$FIX/ng_kyuugata.txt" --max 583

echo "== 6. 訓練名の行を字数に含めないこと =="
expect_contains "訓練名（字数から除外）" "訓練名を除外したと明示する" \
  python3 "$CHECK" --file "$FIX/ok_3dan.txt" --max 583

echo "== 7. 案件固有禁止語・他部門語の未指定を SKIP として明示すること =="
expect_contains "案件固有禁止語が未指定" "NG_EXTRA 未指定を警告する" \
  python3 "$CHECK" --file "$FIX/ok_3dan.txt" --max 583
expect_contains "他部門の対象物語が未指定" "FOREIGN_OBJ 未指定を警告する" \
  python3 "$CHECK" --file "$FIX/ok_3dan.txt" --max 583

echo
echo "----------------------------------------"
echo "PASS: $PASS  /  FAIL: $FAIL"
[[ "$FAIL" == "0" ]] || exit 1
