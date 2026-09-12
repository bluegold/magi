# MAGI

Codexから判定criteriaを渡し、3つの視点で独立評価してから統合判定する最小CLIです。

## 使い方

APIを使わずに動作確認するには、サンプルをmockモードで実行します。

```bash
python3 magi.py examples/decision.json --mock
```

OpenAI APIを使う場合は、専用のAPIキーを環境変数に設定します。

```bash
export OPENAI_API_KEY="..."
python3 magi.py examples/decision.json
```

各人格とJudgeの回答を生成中にターミナルへ表示するには、`--stream`を付けます。進捗はstderr、最終JSONはstdoutへ出力します。

```bash
python3 magi.py examples/decision.json --stream
```

人格ごとに混ざらない表示が必要なら、端末上でTUIを起動します。3人格を上段のペイン、JUDGEを下段に表示します。

```bash
python3 magi.py examples/decision.json --tui
```

`--stream`と`--tui`は同時に指定できません。TUIは対話端末向けで、マウスは使わずキーボードで操作します。`Tab`/矢印でペイン移動、`↑↓`または`j/k`でスクロール、PageUp/PageDown、Home/Endにも対応しています。`q`またはEscで終了します。Codexスキル経由のチャット画面には表示されません。

Codexのスキル経由では、実行中のstderrがチャット画面へトークン単位で中継されるとは限りません。スキルは完了後のJSONを受け取り、Codexが要点を報告する形になります。

`OPENAI_API_KEY`はリポジトリや入力JSONに保存しないでください。モデルは`MAGI_MODEL`で変更できます。

## 入力形式

```json
{
  "subject": "設計案Aを採用するか",
  "context": "比較に必要な背景情報",
  "criteria": [
    {"name": "安全性", "weight": 0.4},
    {"name": "実装コスト", "weight": 0.3},
    {"name": "拡張性", "weight": 0.3}
  ],
  "constraints": ["既存API互換を維持する"],
  "options": ["採用", "条件付き採用", "見送り"]
}
```

criteriaの重みの合計は1でなくても構いません。MAGIが正規化します。
