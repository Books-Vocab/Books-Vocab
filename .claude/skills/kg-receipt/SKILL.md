---
name: kg-receipt
description: "KG 任務收尾與交接 receipt。當使用者要求交接、handoff、總結、驗證證據、下一輪接手，或任務完成前需要固定回報格式時觸發。"
user-invocable: true
version: 1.0.0
---

# KG Receipt

本 skill 固定任務完成時留下可驗證交接。receipt 不是長文檔，不取代 commit message 或 PR body。

## Receipt Checklist

收尾前確認：

1. `git status --short` 已看過。
2. 每個宣稱完成的項目都有當下驗證 command。
3. 若改 user/agent-facing surface，已跑 docs impact/lint 或明確說明為何不需要。
4. 若改 git history / branch / worktree，已跑相應 audit。
5. 若有未跑測試，明確列原因與風險。
6. **Tooling Debt 強制表態**:`none` 或一筆。非 trivial 且未當場修 → 用 `ops/backlog.py add` 登記(**不要手改** `improvement_backlog.md`,那是產出物)。**stream 由「這缺陷誰碰得到」決定,不由誰發現、也不由嚴重度決定**(判準見下「Stream 分流」)。撞到摩擦無聲妥協(硬幹)= 違鐵律9。

### Stream 分流(可判定,不是「視情況」)

問一個問題:**這個缺陷,誰碰得到?**

- 碰得到的是**使用者**(app 使用者、聽 podcast 的人、讀 App Store 頁面或 EULA 的人)→ `--stream APP`,owner = 對應 Line 部門(`ios-engineer` / `backend-engineer`)。
- 碰得到的只有**在這個 repo 裡工作的人**(agent、維護者)→ `--stream IMP`,owner = `platform-steward`。

問「誰碰得到」而不是「改哪個檔」,因為有些修法根本不改 repo 檔(見下第 4 條)。路徑只是這個問題的**常見答案速查**,不是判準本身:

| 位置 | 通常是 | 但要注意 |
|---|---|---|
| `ios/` | `APP` | **例外**:`ios/BooksAndVocab/Debug/Scenarios/`、`Support/UITestFixtureSeed*`、`ios/BooksAndVocabUITests/` 只有 repo 內的人碰得到 → `IMP`(既有 IMP-0064 / -9df883 / -c0e630 就落在這裡;`ops/i18n_lint.sh` 也已排除該路徑) |
| `backend/src/kg/` | `APP` | **例外**:同目錄下的 `ops_*` 模組(`ops_cli_app.py` / `ops_edit_app.py` 等)只有 repo 內的人經 CLI 碰得到 → `IMP` |
| `ops/` / `.claude/` / `docs/` / `backend/ops_*.py` / `backend/*_cli.py` | `IMP` | **例外**:`docs/legal/`(今天只有 `eula_plaintext.txt`)是使用者實際同意的法律文字 → `APP`,category `content` |
| `lab/`(podcast 產線等) | 見下第 3 條 | 沒有常設 owner,不可預設有人在追 |

五條收斂規則,把剩下的模糊關掉:

1. **是誰發現的不影響分流。** 做 ops 任務時撞到的 UI 缺陷仍是 `APP`;用 app 時想到的 CLI 缺陷仍是 `IMP`。
2. **兩邊都要修 = 兩筆,不混成一筆。** 各自進各自的 stream,`detail` 互相指名。混一筆等於指派給兩個 owner,結果是零個。
3. **`lab/` 產線缺陷:先看已出貨的產物,再看產線本身。** 已經送到使用者耳裡 / 眼裡的內容(錯字幕、壞音檔)= `APP` / category `content`;只有跑 pipeline 的人會痛 = `IMP`。但 `.claude/agents/` **沒有 `lab/` 的常設 owner**,所以 `APP` 那半要把「本筆無常設 owner,需上一階指派」寫進 **`--detail` 開頭**(不是只寫在 receipt 裡——receipt 用完即逝,而 schema 沒有 owner 欄位,那筆單會靜靜躺在 Line 部門的收件匣裡不帶任何解釋)。照預設寫 `ios-engineer` / `backend-engineer` 會被兩邊依 scope 邊界退回,結果就是一筆沒人追的單。
4. **修法不改任何 repo 檔的,照「誰碰得到」判,別因為 diff 是空的就往 `IMP` 塞。** App Store 文案錯字的修法是 `./ops/asc.sh set description ...`,EULA 是 `set-eula`——零檔案改動,但看到的是使用者,所以是 `APP` / category `content`。
5. **填不出 `--surface` 與 `--build` 就還不是 APP 報告。** 去把它們補齊,或承認它其實是 `IMP`。這兩格是 APP entry 唯一能讓 owner 重現問題的東西——**注意 CLI 不強制它們**(不填照樣 exit 0),所以這條純靠自律。

category 名單與欄位定義見 `ops/backlog.py --help`,此處不複述(SoT 零重複)。

## Minimal Format

```text
Result:
- <完成的高層結果>

Changed:
- <主要改動，不逐檔流水帳>

Validation:
- <command> -> <result>

Docs/Skill Sync:
- <impact/lint result or none>

Tooling Debt:
- <small friction kept for later, or fixed with regression command>

Risk:
- <remaining risk or none>

Next:
- <只列真正需要下一輪做的事>
```

## Verification Rules

- 不說「完成」但沒有 command。
- 不用「應該可以」代替驗證。
- 不把舊輸出當本輪證據。
- 若背景工作還在跑，receipt 必須標示它不是完成證據。
- Tooling Debt 不可留空:`none` 或一筆 filed item;沉默不合法(andon · 反硬幹)。非 trivial 未當場修者用 `ops/backlog.py add` 登記。
- **stream 決定 owner,所以填錯等於沒人追**:`--stream IMP` 由 `platform-steward` 追到 resolved;`--stream APP` 由對應 Line 部門(`ios-engineer` / `backend-engineer`)追到 resolved,其收件匣是 `./ops/backlog.py list --stream APP`。判準見上方 Checklist 的「Stream 分流」。
- 這條判準只有**一半**是機器守的:`add --stream IMP --surface ...` 會 exit 64 被拒(`ops/tests/test_backlog.py` 釘住);反向——該進 APP 的填成 IMP——沒有任何工具擋得住,所以那一半靠上面的判準自律。

## Handoff Prompt Rule

若使用者要交接 prompt，必須包含：

- 目標
- repo/worktree/branch
- 已改檔案與 commit hash
- 已跑驗證命令
- 已知風險
- 下一步第一個 command
