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

