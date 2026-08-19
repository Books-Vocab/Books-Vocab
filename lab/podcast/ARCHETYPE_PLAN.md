# Archetype Podcast Mode — Implementation Plan

> 把 book→podcast pipeline 從「隱性只服務 non-fiction」升級成 **triage → profile → archetype → resolver → 13 stages** 的製作團隊。你只挑書,AI 判斷 archetype + 劇透政策 + 生成。
>
> 本計畫**合成自** `wyudnygc2` workflow 的 fiction 設計(14 agents,full prompt text 存於 workflow 輸出與各 design section,以 `[design-key]` 引用)+ 本 repo 對話確立的 archetype 方向。commit prefix `ops:`(lab/podcast 屬 ops 域)。測試一律 `uv run pytest`。每 phase 一個可獨立 commit 單位,做 N phase 時派 review agent 審 N-1(鐵律 4)。

---

## 0. 已決策(產品取捨,附理由 — 不再回頭問)

1. **不設全域旗艦,flagship 由 triage per-book 決定。** thriller/推理 → `readalong`;經典/文學/思想小說 → `retrospective`。兩種都建(workflow 已含),retrospective 先 bring-up 去風險。理由:「該推哪個」是假問題——劇透政策本來就該隨書變。
2. **triage = v1 一鍵確認,非全自動。** `triage.py` 印建議 + rationale,人跑 pipeline 確認;`--auto` 全自動留待 Phase 10。理由:選錯 archetype 整集白燒 TTS;且**複用既有 approval-gate 哲學**(`pipeline.py:165` `.plan_approved`/`.script_approved` 本就停等人確認),triage confirm 是同一條 UX。
3. **路由鍵 = archetype(多值),非 fiction/nonfiction(bool)。** workflow 的 `--mode fiction` 是這個的退化投影;本計畫從 Phase 0 就一般化成 `--mode <archetype>`,加 archetype = append registry entry + prompt 變體檔,**零 pipeline code 改動**。
4. **archetype × spoiler_mode 正交。** fiction 是**一套** prompt set,`spoiler_mode ∈ {readalong, retrospective}` 是參數(注入 + 截斷開關),不重複 prompt。沿用 workflow 設計。

---

## 1. North Star 架構

```
你: 丟 EPUB
 └ triage.py            讀 metadata + 抽樣章節 → 結構化 profile
     │                   {archetype, spoiler_mode, axes, confidence, rationale}
     │                   (一鍵確認 / --auto)
     ▼
   pipeline.py --mode <archetype> [--spoiler-mode <m>]
     └ _prompt(name, archetype)  解析 prompt-set       ← 共用為預設, 分叉為例外
        └ 13 stages (STAGES 凍結)  部分 fork / 部分注入 {production_profile}
           └ synthesize → audio-qa → subtitle → upload
```

**核心不變式**:`STAGES`(`pipeline.py:145-152`)**凍結 13 個**,archetype 不加 stage;triage 是**獨立 CLI 前置步**(不進 STAGES),保留 marker/resume/gate 全部不動。

---

## 2. Archetype Registry(SoT,新增檔 `archetypes.py`)

唯一真相源。加 archetype = 在此 append 一筆 + 放對應 `<stage>_<suffix>.md` 變體檔。resolver 靠**檔案存在性**做 per-stage fallback,故一個 archetype 只 fork 它需要的 stage(只放 `analyst_practical.md` → 其餘自動 fall through base)。

```python
# archetypes.py
ARCHETYPES = {
    "nonfiction": {            # fallback archetype;無 _nonfiction.md 變體 → 全走 base prompt
        "label": "Idea Explainer",
        "suffix": None,                    # None → resolver 一律 fall through base
        "requires_spoiler_policy": False,
        "spoiler_modes": [],
        "enricher": "web",                 # 外部佐證(現行行為,零改動)
    },
    "fiction": {               # 敘事傘 archetype;spoiler_mode 決定節目形狀
        "label": "Narrative / Read-Along",
        "suffix": "fiction",               # analyst_fiction.md, architect_fiction.md, ...
        "requires_spoiler_policy": True,
        "spoiler_modes": ["readalong", "retrospective"],   # hybrid 延後
        "enricher": "canon",               # 內向 canon + 條件式 web(P3)
    },
    # ── FUTURE(append-only,零 code 改動)──
    # "practical":  {label:"Actionable",   suffix:"practical",  enricher:"web", requires_spoiler_policy:False}
    # "deep_study": {label:"Deep Study",   suffix:"deep_study", enricher:"web", requires_spoiler_policy:False}
    # "saga":       {label:"Saga Companion",suffix:"saga",      enricher:"canon", requires_spoiler_policy:True}  # 需 series-layout(Phase 11+)
}
DEFAULT_ARCHETYPE = "nonfiction"
```

`triage.py` 與 `pipeline.py` 都 import 此 dict;triage 從 `label`+axes 選 archetype,pipeline 從 `suffix`/`enricher`/`requires_spoiler_policy` 驅動行為。

---

## 3. 路由機制(workflow D1/D3,一般化)

**Resolver**(`pipeline.py`,`PROMPTS_DIR` 定義後 `:70` 附近新增):
```python
def _prompt(name: str, archetype: str) -> str:
    suffix = ARCHETYPES.get(archetype, {}).get("suffix")
    if suffix:
        variant = PROMPTS_DIR / f"{name}_{suffix}.md"
        if variant.exists():
            log_resolution(name, variant)           # missing-variant fallback 可見
            return variant.read_text()
    return (PROMPTS_DIR / f"{name}.md").read_text()
```
改 10 個 prompt-load 點(現行 `(PROMPTS_DIR / "X.md").read_text()`)為 `_prompt("X", archetype)`:
`:674` scriptwriter ・ `:691` script_review ・ `:727` prep ・ `:731` analyst ・ `:735` architect ・ `:739` plan_review ・ `:760` enricher_gap ・ `:765` enricher ・ `:874` series_polish ・ `:899` tts_prep。
> `archetype` 由各 stage 內 `_read_mode(workspace)` 從 sidecar 讀取(resume self-heal),**非**從 `args`——確保 resume 不混 prompt set。

**Profile 注入**:`run_claude` 的 replace chain(`:659`)加 `{production_profile}` token,內容 = archetype label + spoiler 政策塊 + 建議壓縮/時長(advisory)。`run_scriptwriter`(`:674`)/`run_script_reviewer`(`:691`)在 `run_claude` 外組 prompt,自行 substitute。nonfiction 時 `{production_profile}` → `""`,**對既有 genre 可證明零行為改變**。

**CLI**(`main()` `:1175` 後):
```
--mode <archetype>      choices=ARCHETYPES.keys(), default=nonfiction
--spoiler-mode <m>      no default;post-parse 驗證:archetype.requires_spoiler_policy 為真時必填,
                        否則禁止;m 必須 ∈ archetype.spoiler_modes
```

**Sidecars**(workspace 狀態,resume 真相):`.mode` / `.spoiler_mode`。在 **`setup_workspace`(`:298`,fresh-EPUB 路徑)和 `resolve_target` 回傳非空 workspace 後(`:1183`,resume 路徑)兩處**都寫/refresh —— 這是 workflow 標的 BLOCKER(fresh + `find_workspace` resume 雙路徑都要覆蓋)。resume 時:explicit flag 與 sidecar 衝突 → `parser.error`;flag 缺 → sidecar 勝,絕不用 `args`。

---

## 4. Triage Stage(新角色 — 你「只挑書」的解鎖點)

**獨立 CLI `triage.py`**(不進 STAGES,保 13 凍結)。讀**便宜訊號**:EPUB OPF metadata(title/author/subjects)+ 抽樣章節(首章 / ~25% / ~75% / 末章),**不讀全書**(analyst 才讀全書;triage 必須跑在 prompt 選擇之前,故只能是抽樣前置分類器)。

輸出 `triage.json`(結構化,非自由文字 → 滿足 workflow D2「控制流不依賴 agent 自由文字」):
```json
{
  "archetype": "fiction",
  "spoiler_mode": "readalong",
  "confidence": 0.82,
  "axes": {"drive":"plot", "spoiler_sensitivity":"critical",
           "structure":"standalone", "length":"novel", "density":"medium"},
  "rationale": "偵探敘事, 三幕反轉結構, 劇透敏感 → readalong",
  "recommended_cmd": "uv run pipeline.py book.epub --mode fiction --spoiler-mode readalong"
}
```
v1 行為:印 `recommended_cmd` + rationale,人複製執行(一鍵確認)。`--auto` 旗標(Phase 10):直接 exec pipeline。
prompt:`prompts/triage.md`(分類進 registry archetype + 沿 4 軸給座標 + 建議 spoiler_mode + confidence)。

---

## 5. Hard Contracts 保留(fiction 路徑不可破 — workflow 已逐項驗證)

| # | 契約 | enforced at | honored by |
|---|------|-------------|-----------|
| 1 | Voice Mapping regex,恰 2 條 | `synthesize.py:132/141` hard-fail | `architect_fiction.md` 出相同 block;reader-host 只改文案 |
| 2 | `(TBD)` 字面 | `synthesize.py:152` | architect 寫 `(TBD)`,tts-prep(不動)替換 |
| 3 | speaker tag `**Name:**`,名無 `:`/`*` | `synthesize.py:208` | fiction 用同 tag |
| 4 | `END_OF_SCRIPT` sentinel | `pipeline.py:734/834` | fiction script 收尾;reviewer 缺則補、不刪 |
| 5 | skip-line set 只 `#`/`>`/blank/`<!--…-->` | `synthesize.py:213` | fiction 遵守;hybrid fence 用 `**Host:**` 行非 `---` |
| 6 | 4 QA-gate tokens | `pipeline.py:694/828/805/853` | fiction review 出相同 token;`SPOILER_VIOLATION` 為**加法** |
| 7 | 必需檔名 / 路徑 | pipeline glob | fiction 寫同路徑;Beat Map 在 `analysis.md` 內、horizon 在 `ep_NN.md` 內 |
| 8 | Cold-Open/Sign-Off 3 行(voice cold-start) | `scriptwriter.md:60-66` | fiction 保 ≥3 substantial 開場/收場 turn |
| 9 | **`STAGES` 凍結** | `pipeline.py:145-152` | **零 stage 增刪改名** — master 不變式;triage 是外部 CLI |
| 10 | `series_id` slug `^[a-z0-9_]+$` | `pipeline.py:223-239` | 不動 |
| 11 | `## Enrichment` idempotency marker | `enricher.md:14-26` | `enricher_fiction.md` 沿用同字串 |

---

## 6. Phased Implementation Plan(每 phase 可獨立 commit,TDD)

> Phase 0-1 = 一般化骨架(取代 workflow Phase 0-1)。Phase 3-9 = workflow 的 fiction 實質(prompt full text 見對應 `[design-key]`)。Phase 2/10 = 新增 triage。

### Phase 0 — Archetype 路由骨架(可跑)
**Goal**:`uv run pipeline.py book.epub --mode fiction --spoiler-mode retrospective` 13 stage 跑完(用 stub fiction prompt = base 薄包一層)。證明 resolver + registry + sidecar + nonfiction 不變。
**Files**:`archetypes.py`(registry);`pipeline.py`(`_read_mode`/`_prompt`/`_policy_block` helper @ `:70` 後;10 個 load 點換 resolver;`--mode`/`--spoiler-mode` argparse + post-parse 驗證;sidecar 寫於 `setup_workspace`;`{production_profile}` 入 `run_claude` replace chain `:659`);stub `prompts/{analyst,architect,enricher_gap,enricher}_fiction.md`;`scripts/test_archetype_routing.py`。
**Failing test first**:`test_resolver_prefers_variant_else_base` + `test_nonfiction_prompt_selection_byte_identical`(golden)+ `test_unknown_archetype_rejected`。
**Done**:resolver/registry test 綠;真 EPUB 跑完 `--mode fiction --spoiler-mode retrospective`;`--mode fiction` 無 `--spoiler-mode` → `parser.error`;nonfiction 走 base 不變。
**Commit**:`ops: archetype routing skeleton (registry + resolver + sidecars, stub fiction prompts)`

### Phase 1 — Resume 正確性 + conflict guard
**Goal**:resume 永不混 prompt set;覆蓋 fresh-EPUB / bare-workspace / `epub + --skip-to`(`find_workspace`)三路徑。
**Files**:`pipeline.py`(`resolve_target` 回非空 workspace 後、`detect_resume_point` 前,單一 persist+guard block,涵蓋兩 sidecar;衝突 explicit flag → `parser.error`,缺 flag → sidecar 勝);test 擴充。
**Failing test first**:`test_resume_epub_skipto_fiction_does_not_fall_through_to_nonfiction` + `test_resume_conflicting_mode_hard_errors`。
**Done**:三路徑都 persist/refresh sidecar;conflict-guard 在 `find_workspace` 分支觸發。
**Commit**:`ops: archetype resume-correctness across all workspace-resolution branches`

### Phase 2 — Triage CLI
**Goal**:`uv run triage.py book.epub` → `triage.json` + 印 `recommended_cmd`。獨立可測(fixture:已知書 → 期望 archetype)。
**Files**:`triage.py`;`prompts/triage.md`;`scripts/test_triage.py`(fixture EPUB metadata + 抽樣 → 斷言 archetype/spoiler 分類)。
**Failing test first**:`test_thriller_sample_classifies_fiction_readalong` + `test_business_book_classifies_nonfiction` + `test_triage_json_schema_valid`。
**Done**:分類器對 fixture 給正確 archetype;`triage.json` schema 合法;`recommended_cmd` 可直接執行。
**Commit**:`ops: triage CLI — sample-based archetype/spoiler classifier`

### Phase 3 — Fiction analyst(真 schema + split-anchor Spoiler Ladder)
**Files**:`prompts/analyst_fiction.md`(full text `[fiction-analyst]`;**B1 fix**:`disclosure_anchor` + `safe_anchor` + `seeded_but_cryptic_at` 三欄取代單一 `earliest_safe_anchor`);canonical `##` header 輸出契約小節;`scripts/test_fiction_parsers.py`。
**Failing test first**:`test_spoiler_ladder_parses_split_anchors` + `test_cryptic_flashforward_safe_anchor_later_than_disclosure`。
**Done**:parser 抽兩 anchor;ladder round-trip。
**Commit**:`ops: fiction analyst — dramaturgical schema + split-anchor spoiler ladder`

### Phase 4 — Source 截斷(read-along 物理保證,非叮嚀)
**Goal**:scriptwriter **物理讀不到** horizon 後章節;reviewer 可。
**Files**:`pipeline.py`(`run_scriptwriter` 讀 `ep_NN.md` 的 `source_horizon_chapters`;readalong/hybrid 指向 per-episode clipped view `source/episodes/ep_N/ch_*.md`(只 symlink horizon 內章節)並收窄 Glob root;reviewer 保 full `source/chapters/`);`setup_workspace` lazy 建 per-ep dir;`test_fiction_truncation.py`。
**Failing test first**:`test_scriptwriter_source_view_excludes_post_horizon` + `test_reviewer_source_view_includes_full_book`。
**Done**:非對稱 file-set 驗證;nonfiction/retrospective 不裁切;specimen 引文 inline 在 `ep_NN.md`(截斷的 scriptwriter 仍能引用)。
**Commit**:`ops: fiction read-along source truncation (per-episode clipped scriptwriter view)`

### Phase 5 — Fiction architect + 劇透子系統
**Files**:`prompts/architect_fiction.md`(full text `[fiction-architect]`;episode 切於 dramatic turn;two-reader host;每集 `**spoiler_horizon**:` + `**source_horizon_chapters**:` + inline specimen quotes + listener Spoiler Contract;**canonical field 名** scriptwriter/reviewer 綁定);`stage_architect`(`:735`)加 Voice-Mapping 存在檢查 fail-fast;`test_fiction_parsers.py` 擴充。
**Failing test first**:`test_episode_plan_emits_horizon_fields` + `test_architect_fails_fast_on_missing_voice_mapping`。
**Done**:episode plan 帶雙 horizon 欄;specimen ≤ horizon;Voice Mapping byte-shape 合契約 #1。
**Commit**:`ops: fiction architect + per-episode spoiler-horizon contract`

### Phase 6 — Fiction scriptwriter(param-inject,fail-closed)
**Files**:`prompts/scriptwriter_fiction.md`(full text `[fiction-scriptwriter] PROMPT 1`;perform-not-knowing、anti-summary、two-reader、paraphrase-first;**B1 fix**:綁 architect 真欄名;**缺 spoiler 欄 → 阻斷 note 進 review verdict,絕不靜默 retrospective**);`run_scriptwriter` substitute `{production_profile}`。
**Failing test first**:`test_scriptwriter_missing_horizon_fails_closed_not_retrospective`。
**Done**:script 收 `END_OF_SCRIPT`;cold-open/sign-off 3 行;bounded mode 的 "Next time" 只 affect-only。
**Commit**:`ops: fiction scriptwriter — perform-not-knowing, fail-closed horizons`

### Phase 7 — Script-review + `SPOILER_VIOLATION` gate
**Goal**:gate。reviewer 用全書 view 對 horizon 掃前洩;`SPOILER_VIOLATION`+`REWRITE_NEEDED` 同出;pipeline grep **所有** review 檔(非僅新寫的 — 補 resume 盲點)。
**Files**:`prompts/script_review_fiction.md`(full text `[fiction-scriptwriter] PROMPT 2`);`pipeline.py`(~8 行:grep `SPOILER_VIOLATION` across all `ep_*_review.md`,log 獨立 failure class,仍經 `REWRITE_NEEDED` `:805` hard-fail);`test_fiction_spoiler_gate.py`。
**Failing test first**:`test_forward_reference_past_horizon_triggers_violation` + `test_spoiler_gate_scans_preexisting_reviews_on_resume`。
**Done**:植入前洩 script fail stage;retrospective mode gate inert;resume re-scan work。
**Commit**:`ops: fiction SPOILER_VIOLATION gate (rides REWRITE_NEEDED, scans all reviews)`

### Phase 8 — Fiction enricher(內向 canon,條件式 web)
**Files**:`prompts/{enricher_gap,enricher}_fiction.md`(full text `[enricher-and-series]`;standalone fast-path = 近空 brief;沿用 `## Enrichment` marker + rename-guard 註解);`pipeline.py` `stage_enricher`(`:763`)**條件式 tool grant**:`mode=="fiction"` 且 `research_brief.md` 含 `P3` 才給 `["WebSearch","WebFetch"]`,否則 `extra=[]`;`test_fiction_enricher.py`。
**Failing test first**:`test_enricher_grants_web_only_when_brief_has_P3` + `test_standalone_enricher_resume_safe_noop`。
**Done**:standalone → 空 brief、stage True、marker 寫、scriptwriter 不受影響;web 工具僅 P3 時授予。
**Commit**:`ops: fiction enricher — inward canon pass, conditional web grant`

### Phase 9 — Doc sync + smoke(閉環,鐵律 6 + CLAUDE.md scope)
**Files**:`.claude/skills/podcast-pipeline/SKILL.md`(`--mode`/`--spoiler-mode`/`triage.py` 路由);`docs/sop/podcast_pipeline.md`(註冊 `SPOILER_VIOLATION` 第 5 gate、triage 前置步、archetype registry、截斷機制);`docs/reference/product_surface.md`(archetype-mode bullet);`docs/reference/testing/smoke_checklist.md`(fiction smoke);跑 `ops/docs_lint.sh`。
**Smoke**:《The Yellow Wallpaper》(單弧 ~12 章)`--mode fiction --spoiler-mode readalong` → TTS-valid script、零 `SPOILER_VIOLATION`;負向 smoke:手改植入前洩 → gate **必須** fail。
**Commit**:`ops: archetype-mode docs sync + fiction smoke`

### Phase 10 —(可選)Triage 自動接管 + monitor ingest UX
`triage.py --auto` 直接 exec pipeline;monitor dashboard 加 "ingest" 鈕 → triage → 顯示 profile + 一鍵確認 → spawn pipeline。把「只挑書」做成真正的端到端 UX。
**Commit**:`ops: triage auto-handoff + monitor ingest flow`

### Phase 11+ —(獨立 epic,延後)更多 archetype + hybrid + series
- `practical` / `deep_study` archetype:append registry + 對應 prompt 變體(零 pipeline code)。
- `hybrid` spoiler mode:scriptwriter `**Host:**` fence + reviewer fence-anchor。
- `saga`(多書系列):需 `setup_workspace` saga-grouping(`WORKSPACES_DIR/<saga>/<book>_<hash>/`)+ `--series-bible <path>` + `series_polish_fiction.md` 的 cross-book sweep。workflow D8 確認此為獨立 epic。

---

## 7. Test 策略

**Unit**(`scripts/test_*.py`):resolver variant-preference + nonfiction golden(P0);sidecar 三路徑 + conflict-guard(P1);triage 分類 fixture(P2);Spoiler Ladder split-anchor(P3);`ep_NN.md` horizon round-trip(P5);scriptwriter source-view 排除 post-horizon / reviewer 含全書(P4);植入前洩 → `SPOILER_VIOLATION`(P7);enricher 條件 web + standalone no-op resume(P8);fail-closed:缺 horizon 不退化 retrospective(P6/P7)。
**E2E smoke**(P9):短公版小說全 13 stage;Voice Mapping/speaker tag/`END_OF_SCRIPT`/skip-line set 全過;正向零 violation + 負向 gate fail;**nonfiction smoke 仍過(回歸)**。

---

## 8. 仍屬「人」的決策(其餘我自決)

1. **triage confidence 低於閾值時的行為**:強制人選 vs 預設保守 archetype?(產品取捨,Phase 2 前需定)
2. **`SPOILER_VIOLATION` false-negative 容忍度**:LLM 判斷漏掉細微伏筆 = 洩漏(對聽眾不可逆)。v1 以截斷為主防線是否足夠,或現在就投資 deterministic 補強(proper-noun cross-check:script 出現但只存在於 horizon 後的人名)?成本 vs 信任取捨。

— 其餘(web-context cap、archetype 命名、各 prompt 細節)依工程最佳實踐自決。
