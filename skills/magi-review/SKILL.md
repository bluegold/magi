---
name: magi-review
description: 判定criteriaを整理し、MAGIの複数人格による意思決定レビューを実行する。
---

# MAGI Review

Codexが判定依頼を受けたら、対象・背景・criteria・制約・選択肢を整理して、下記の実行コマンドにJSONを渡す。

実行コマンド:

```bash
python3 {{MAGI_EXECUTABLE}} <request.json> --mock
```

形式を確認した後、`OPENAI_API_KEY`が設定されている場合は`--mock`を外して実APIを実行する。

## 手順

1. 依頼の対象と、意思決定で比較すべきcriteriaを明示する。
2. criteriaごとに必要なら重みを設定する。重みは合計1でなくてもよい。
3. 事実、仮定、制約、選択肢を分離する。
4. 依頼JSONを一時ファイルに保存する。APIキーはJSONへ書かない。
5. 初回は `python3 magi.py <request.json> --mock` で入力と出力形式を確認する。
6. API判定が必要なときだけ `OPENAI_API_KEY` が設定された環境で `--mock` なしで実行する。
7. MAGIの結論をそのまま採用せず、意見が割れた点・確信度・追加確認事項を人間向けに報告する。

## 入力契約

必須項目は `subject` と `criteria`。任意項目は `context`、`constraints`、`options`。

## 出力契約

`analyses` にMELCHIOR、BALTHASAR、CASPERの個別分析、`judgment` に統合判定が入る。
