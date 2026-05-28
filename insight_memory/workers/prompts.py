from __future__ import annotations


IDENTITY_PROFILE_RULES = """
Shared identity_profile rules:
- First decide which named stable subject owns the input or query.
- If the input or query can be assigned to one concrete stable subject, extract an identity_profile for that
  subject. Do not run a second value/type gate over the statement content.
- Reject identity extraction only when no concrete stable subject owns the input or query.
- A stable subject is a named thing that can be referred to again later, such as a system, document, project,
  team, workflow object, market object, person, or other named object.
- If a name is only a missing item, attachment, evidence, prerequisite, reason, or detail inside another
  subject's statement, do not create a separate subject for it.
- If a name is only mentioned in passing and the input or query does not belong to that name, do not create a
  subject for it. Create it only when the same input or query also contains a separate statement owned by that
  name.
- identity_profile describes only who the subject is, not what happened to it.
- `schema_version` must be exactly 2.
- `who` must be a short stable label for the same subject.
- `entity_type` must be one of: person, organization, market_object, system, document, artifact, project,
  work_item, workflow, event, decision, strategy, concept, unknown.
- Use `unknown` when the entity type is not clear. Do not invent a narrow type outside the enum.
- `surface_forms` must come from the input or query text directly.
- `stable_qualifiers` must contain only short stable qualifiers that distinguish same-name subjects. Do
  not write prose.
- `evidence` may contain short identity extraction evidence, but it is only for audit and must not contain
  current state, result, blocker, owner value, or other memory facts.
- Do not include current state, blocker, owner value, requirement content, conclusion, metric, time change, or
  any other memory fact in identity_profile.
- Record markers such as round, stage, date, session, or version are not identity. Keep them in memory content,
  query_text, or record_markers.
- Repeated historical or current records about the same named review, plan, document, workflow, or artifact
  must keep the same identity_profile. Distinguish rounds and time in content or record_markers.
- Generic record wording such as "this record", "latest note", "analysis note", "history", or "report content"
  is usually retrieval intent, not identity. If the query names an underlying stable subject, keep the
  underlying subject as identity and keep the generic record wording in query_text or memory content.
- A named report, handbook, policy, plan, checklist, or other artifact can still be identity when the artifact
  itself has a stable name. Do not confuse that with generic wording that only describes the stored record type.
- When one input or query contains several different subjects with the same prefix, keep the stable qualifier
  that separates them instead of collapsing them into a bare name.

Example 1: normal subject statement
Input:
`Gateway 是项目，当前主阻塞是数据库迁移失败。`
Correct identity_profile:
`{"who":"Gateway 项目","surface_forms":["Gateway","Gateway 项目"],"stable_qualifiers":["项目"]}`
Explanation:
`项目` is a stable identity qualifier. `数据库迁移失败` is memory content, not identity_profile.

Example 2: multiple subjects with the same prefix
Input:
`Radian 运营组 计划本周完成切换；Radian 运行手册 还缺回滚章节。`
Expected drafts:
`[
  {"who":"Radian 运营组","surface_forms":["Radian","Radian 运营组"],"stable_qualifiers":["运营组"]},
  {"who":"Radian 运行手册","surface_forms":["Radian","Radian 运行手册"],"stable_qualifiers":["运行手册"]}
]`
Explanation:
The input belongs to two different subjects, so extract two identity_profile drafts.

Example 3: record round is not identity
Input:
`Cobalt launch review round 1 supported the existing launch slot.`
Correct identity_profile:
`{"who":"Cobalt launch review","surface_forms":["Cobalt launch review"],"stable_qualifiers":["launch review"]}`
Wrong identity_profile:
`{"who":"Cobalt launch review round 1","surface_forms":["Cobalt launch review round 1"],"stable_qualifiers":["launch review"]}`
Explanation:
`round 1` is a record marker, not part of the subject identity.

Example 4: a missing item is not a separate subject
Input:
`Harborlane rollout 不能进入 cutover，因为 quay memo 还没补齐。`
Correct identity_profile:
`{"who":"Harborlane rollout","surface_forms":["Harborlane rollout","Harborlane"],"stable_qualifiers":["rollout"]}`
Explanation:
`quay memo` is the missing reason for Harborlane rollout, not the owner subject of this input.

Example 5: named governing artifact
Input:
`Harborlane checklist 要求所有 rollout 在 cutover 前补齐 quay memo。`
Correct identity_profile:
`{"who":"Harborlane checklist","surface_forms":["Harborlane checklist","Harborlane"],"stable_qualifiers":["checklist"]}`
Explanation:
The input belongs to `Harborlane checklist`. `quay memo` is requirement content, not a separate subject.

Example 6: passing mention is not a separate subject
Input:
`周会里顺手提到 Trellis service，但主结论是 Bastion rollout 当前主阻塞是审批链说明缺失。`
Correct identity_profile:
`{"who":"Bastion rollout","surface_forms":["Bastion rollout","Bastion"],"stable_qualifiers":["rollout"]}`
Explanation:
The input belongs to Bastion rollout. Trellis service is only mentioned in passing.

Example 7: passing mention plus its own statement
Input:
`周会里顺手提到 Trellis service，另外确认 Trellis service 当前负责人是 Nia Chen。`
Correct identity_profile:
`{"who":"Trellis service","surface_forms":["Trellis service","Trellis"],"stable_qualifiers":["service"]}`
Explanation:
The second clause gives Trellis service its own statement, so extract it.

Example 8: extract identity when the statement has an owner subject
Input:
`Release calendar records candidate windows; approval still comes from the change board.`
Correct identity_profile:
`{"who":"Release calendar","surface_forms":["Release calendar"],"stable_qualifiers":["calendar"]}`
Explanation:
The input belongs to Release calendar. Identity extraction does not need to classify the statement into a fact
type first.

Example 9: generic record wording is not identity
Input:
`BRK.A 这条 analyst note 里的主要取舍是什么？`
Correct identity_profile:
`{"who":"BRK.A","surface_forms":["BRK.A"],"stable_qualifiers":["market object"]}`
Wrong identity_profile:
`{"who":"BRK.A analyst note","surface_forms":["BRK.A","BRK.A analyst note"],"stable_qualifiers":["analyst note"]}`
Explanation:
The query asks about a stored note for BRK.A. The stable subject is BRK.A; `analyst note` is retrieval intent,
not a separate identity.

Example 10: named artifact remains identity
Input:
`Aurora risk handbook 这条记录里要求哪些审查？`
Correct identity_profile:
`{"who":"Aurora risk handbook","surface_forms":["Aurora risk handbook"],"stable_qualifiers":["risk handbook"]}`
Explanation:
The named handbook is the stable subject. `这条记录` only says which stored memory the query wants to inspect.

Example 11: independent sub-artifacts within a parent context
Input:
`Product Division 同时运营两条产品线：Line A 本季度聚焦企业客户，负责人是 Wang Lin；Line B 本季度聚焦个人用户，负责人是 Chen Hua。`
Expected drafts:
`[
  {"who":"Product Division","surface_forms":["Product Division"],"stable_qualifiers":["division"]},
  {"who":"Line A","surface_forms":["Line A"],"stable_qualifiers":["line","A"]},
  {"who":"Line B","surface_forms":["Line B"],"stable_qualifiers":["line","B"]}
]`
Explanation:
Each named product line has its own independent durable facts (target segment and owner), so they must be extracted as separate subjects even though they are mentioned within Product Division's context.
""".strip()


WORKER_INSTRUCTIONS: dict[str, str] = {
    "write_gate": f"""
Decide whether the raw input should be accepted for long-term memory ingest.
Return identity_profile drafts only; do not create candidate memories.
Rules:
- identity_profile drafts must use only fields defined by schema.
- {IDENTITY_PROFILE_RULES}
- If no stable subject can be identified, return rejected_no_identity_profile.
- Use short opaque refs for `draft_id`, such as `d1`, `d2`.
""".strip(),
    "extractor": f"""
From the raw input, extract one or more identity_profile drafts and candidate memories.
Rules:
- identity_profile drafts must use only fields defined by schema.
- {IDENTITY_PROFILE_RULES}
- If no stable subject can be identified, return rejected_no_identity_profile and no candidates.
- Use short opaque refs for `draft_id` and `candidate_id`, such as `d1`, `d2`, `c1`, and `c2`.
- Every candidate `owner_draft_id` must copy one emitted draft ref exactly.
- candidate memories must describe the input's statement about the owner subject, not raw copies of unrelated context.
- Every candidate memory must reference a valid owner_draft_id.
- If the input can be assigned to a named stable subject under the shared identity rules, create a candidate memory for the statement assigned to that subject.
- If the input primarily belongs to one subject and only incidentally mentions another subject, do not create a separate candidate memory for the incidental subject unless the input also contains a separate statement owned by that incidental subject.
- Named sub-projects, sub-systems, sub-components, or sub-artifacts that have their own independent durable facts (such as timeline, owner, status, or requirements) should be extracted as separate subjects even when they are mentioned within a parent subject's context.
- Mere presence in a meeting note, side mention, surrounding chatter, or contextual aside is not by itself a durable memory worth storing as a separate candidate.
  Example: `周会里顺手提到 Trellis service，但主结论是 Bastion rollout 当前主阻塞是审批链说明缺失。`
  Preferred: keep one candidate memory for `Bastion rollout 当前主阻塞是审批链说明缺失`, and do not create a separate memory like `Trellis service 在周会中被提到`.
  Example: `周会里顺手提到 Trellis service，另外确认 Trellis service 当前负责人是 Nia Chen。`
  Preferred: creating a memory for `Trellis service 当前负责人是 Nia Chen` is valid, because the side subject now has its own durable fact.
- If a phrase is only a detail inside another subject's statement, keep it inside that subject's candidate memory instead of creating a separate identity_profile or candidate memory for the phrase.
- For patterns like `X cannot proceed/confirm/launch/complete because Y is missing/incomplete/not submitted/not signed`, create a candidate memory for X that includes Y as the reason. Do not create Y as a separate subject unless the input also gives Y its own durable owner, rule, status, decision, requirement, lifecycle, version, or tracking state.
- If another named policy, protocol, checklist, manual, handbook, rule, or guide says X must provide Y, that named governing artifact can be a separate subject, while Y is still just the required item unless it has its own independent durable fact.
  Example: `Harborlane rollout 不能进入 cutover，因为 quay memo 还没补齐。`
  Preferred: create one draft and one candidate memory for `Harborlane rollout`; keep `quay memo` as the missing reason inside that memory, not as its own subject.
  Example: `Harborlane checklist 要求所有 rollout 在 cutover 前补齐 quay memo。`
  Preferred: create one draft and one candidate memory for `Harborlane checklist`; keep `quay memo` as the required item inside the checklist memory.
  Example: `Harborlane quay memo 当前负责人是 Ivo Tan。`
  Preferred: creating a separate `Harborlane quay memo` subject is valid, because the memo now has its own durable owner fact.
- If one message, email, table, checklist, or bullet list contains multiple clearly separate durable conclusions about different stable artifacts that share a prefix, keep each full subject phrase separate instead of collapsing them into one shared prefix subject.
- Different role or artifact nouns such as `docket`, `manual`, `review`, `plan`, `bulletin`, or `register` can mark different stable subjects when the text gives each one its own durable blocker, owner, requirement, decision, or target.
  Example email: `Opal pier follow-up: Opal pier docket 当前缺 mooring appendix；Opal pier manual 当前要求补 mooring appendix 和 slip witness note；Opal pier review 当前负责人是 Selene Sol；Opal pier plan 当前目标是周五前补完 berth packet。`
  Preferred: create four separate drafts and four candidate memories, because `docket`, `manual`, `review`, and `plan` are four different stable artifact subjects with different durable claims.
- If the input uses structured field-style formatting such as `record: ...`, `phase: ...`, `entity=...`, `rule: ...`, `state=...`, or `owner: ...`, treat those fields as strong structure rather than as formatting noise.
- A short structured record can still be a durable memory when it names a stable subject and a durable rule, blocker, owner, state, or requirement.
  Example fields: `record: Coronet handover notice`, `phase: history`, `rule: teams could attach seal note within 24 hours after shift`.
  Preferred: keep this as an earlier durable rule memory for `Coronet handover notice`, not as disposable formatting noise.
- If the input is a time-bounded or session-bounded historical record about a concrete subject, keep the subject in the draft and summarize the record as a candidate memory instead of collapsing it into a generic event.
- If the input includes explicit session, stage, round, date, or version markers, keep those markers inside the candidate memory title, summary, or content so later historical records remain distinguishable.
- If the input includes explicit session, stage, round, or date markers, populate record_markers so later resolution can distinguish historical records without guessing.
- Preserve important detail in each candidate memory, but do not emit repeated, near-duplicate, or trivially rephrased candidate memories.
- Preserve the original language of the input when writing title, summary, and content. Do not silently translate Chinese into English or English into Chinese unless the source itself is bilingual.
- Keep critical concrete phrases visible in memory content, such as blockers, dates, times, document names, explicit requirements, and operational conditions.
- For one long report, long history, or long debate record about one subject, default to one detailed primary memory.
- Long historical or review records can be durable even when they describe tradeoffs, rationale, conditions, open questions, recovery plans, pause reasons, or decision constraints instead of a simple blocker, owner, or rule.
- Do not reject a named long historical/review record merely because it is analytical or balanced; extract the concrete durable conclusion, tradeoff, conditions, or unresolved points that would answer a future query about that record.
  Example long review: `Meridian portal refresh` weighs accepting short-term migration and review effort in exchange for one entry point and lower duplicate maintenance.
  Preferred: emit one detailed memory preserving both sides of the tradeoff, because a future query may ask what tradeoff the review recorded.
- Only emit multiple candidate memories when the source contains multiple clearly separate claims that would answer materially different future queries.
- Different sections, headings, bullets, or supporting arguments of the same conclusion must stay inside one memory content instead of being split into separate memories.
- If one long document contains an earlier rule, a current rule, and an appendix/amendment/addendum that only adds another still-valid requirement to that same current rule, emit one earlier historical candidate plus one current candidate that already includes the additive requirement. Do not emit a second separate current candidate that merely repeats the stricter rule before adding the supplement.
- If a correction note, appendix, addendum, follow-up attachment note, or supplement only tightens or extends the same current named artifact rule, fold that detail into the same current candidate memory during extraction instead of splitting it into another parallel current candidate.
  Example long document: `Grayshore bulletin` earlier allowed berth note filing within 14 hours after release, the current section now requires filing before release, and an appendix adds `quay owner signature`.
  Preferred: emit one earlier historical candidate plus one current candidate that already includes both `before release` and `quay owner signature`, not three separate candidates.
""".strip(),
    "linker": f"""
Decide whether the identity_profile draft can be uniquely bound to one of the provided entity candidates.
Rules:
- {IDENTITY_PROFILE_RULES}
- Only choose from provided entity candidates.
- Compare the draft against identity_profile, display_name, and representative memory summaries together.
- Use `who`, `surface_forms`, and `stable_qualifiers` together as identity signals. Do not treat stable_qualifiers as the only place where stable qualifiers can appear.
- Return link_existing only when one candidate is clearly the same subject and the binding is specific enough to exclude the other candidates.
- For write mode, prefer link_existing whenever one candidate is still the best match after using stable_qualifiers and representative memories.
- If the draft and the best candidate share the same surface form but clearly differ in stable identity or function, do not merge them into one entity.
- In write mode, when the surface form matches but the role-like identity differs, prefer create_new over forcing link_existing.
  Example: draft `Meridian 项目`, candidate A `Meridian 项目`, candidate B `Meridian 知识文档`.
  Preferred: in write mode, create a new entity for the document if the new draft clearly refers to the document rather than the project.
- In write mode, if the draft and the best candidate share the same named subject or artifact and the only meaningful difference is temporal wording such as `之前`, `当前`, `现在`, `later`, `already changed`, or `已经变成`, treat them as the same entity. Temporal state changes are not stable identity differences.
  Example: earlier draft `Saffron portfolio review 之前主风险是 duration mismatch。`; later draft `Saffron portfolio review 当前主风险已经变成 liquidity buffer drawdown。`
  Preferred: link both drafts to the same `Saffron portfolio review` entity. The risk changed, but the subject identity did not.
- For write mode, return create_new only when all provided candidates clearly refer to different subjects.
- For query mode, if no candidate clearly matches, return cannot_resolve.
- For query mode, return ambiguous only when multiple candidates remain genuinely plausible after using all provided context.
- In query mode, use any stable identity qualifier in the draft to exclude candidates with a conflicting identity or function.
- In query mode, if the stable identity qualifier in the draft matches exactly one candidate and conflicts with the others, return link_existing for that candidate instead of ambiguous.
- In query mode, if the draft's `who` or one of its surface_forms already carries a stable type qualifier that matches one candidate and excludes the others, return link_existing instead of ambiguous.
- In query mode, a broader stable type qualifier in the draft can still match a candidate with a more specific subtype when that qualifier rules out the conflicting candidates.
  Example: query draft `Verdigris rollout`, candidate A `Verdigris rollout`, candidate B `Verdigris checklist`.
  Preferred: link the rollout candidate. `rollout` and `checklist` are stable identity qualifiers, not cosmetic wording differences.
  Example: query draft `Summit plan`, candidate A `Summit plan`, candidate B `Summit project`, candidate C `Summit checklist`.
  Preferred: link the plan candidate. `plan`, `project`, and `checklist` are stable identity qualifiers and should not collapse into one another.
- A named policy, handbook, rule, guideline, report, project, document, or plan can itself be a stable subject when the query is asking about that named artifact's requirements, decisions, gaps, or constraints.
- A named checklist, rollout, service, or runbook can also be a stable subject, and its role noun should be treated as part of stable identity when it distinguishes the subject from another same-surface artifact.
- If two candidates share the same short surface form but one is a project/system and the other is a document/report/policy/plan/checklist artifact, treat that role difference as a stable identity difference rather than a cosmetic wording difference.
- When the draft names a concrete artifact and asks what it requires, says, or mandates, do not reject the query just because the stable_qualifiers is sparse.
  Example: query draft `Gateway policy`, query `Gateway policy 有什么要求？`
  Preferred: treat `Gateway policy` as a stable subject and link it to the named policy entity instead of cannot_resolve.
""".strip(),
    "resolver": """
Compare all candidate memories to existing memories under the same entity.
Return one resolution item per candidate memory.
Rules:
- In candidate_memories, candidate_id is an opaque short ref like `c1`.
- In existing_memories, memory_id is an opaque short ref like `m1`.
- In your output, candidate_id must copy one provided candidate ref exactly.
- In your output, target_memory_id must copy one provided existing-memory ref exactly.
- Never invent refs, rewrite refs, or output raw internal ids.
- refresh means the candidate restates and strengthens an existing memory.
- replace means the candidate supersedes an older memory with a newer one.
- coexist means both memories can stand together.
- stale means an existing target should be marked stale.
- If no existing memory clearly matches, use create.
- Use record_markers when they are provided.
- If the candidate is a time-bounded or session-specific record that is not a near-duplicate of an existing memory, prefer coexist over refresh.
- If the candidate and an existing memory have different session, stage, round, or date markers, prefer coexist unless the new record explicitly says it supersedes or replaces the older one.
- If there are no meaningful historical markers and the new candidate clearly updates the same standing fact, prefer replace over coexist.
- If an existing memory has explicit record_markers and the new candidate does not, do not refresh the bounded historical record into the new candidate just because they overlap. Keep the bounded historical record unless the new candidate explicitly says it is the same bounded record.
- If the new candidate states the newer current state, current blocker, current owner, latest decision, or settled conclusion for the same tracked subject, and an existing memory describes an earlier state of that same tracked subject, prefer replace so the earlier state becomes superseded via updates.
- If one memory says the subject previously had blocker or state A, and a newer memory says the subject now has blocker or state B, treat that as one tracked subject state changing over time. Prefer replace so the earlier state becomes superseded via updates, unless the input clearly presents the two states as parallel alternatives that should remain simultaneously active.
- When an earlier memory is phrased as `之前卡在 A` and a newer memory is phrased as `当前主阻塞已经变成 B`, treat that as the same tracked blocker chain changing over time. Prefer replace so the earlier blocker becomes superseded via updates rather than leaving both states active.
- Prefer replace for earlier/current or before/now transitions when both memories answer the same practical question about the subject's tracked blocker, owner, requirement, or standing status, even if the older memory is phrased as history and the newer one is phrased as the current situation.
  Example: existing `Cedar review 之前卡在 database migration timeout。`; new `Cedar review 当前主阻塞已经变成 rollback approval missing。`
  Preferred: replace the earlier blocker with the newer current blocker, because the tracked blocker changed over time.
  Example: existing `Cedar review 之前卡在 schema freeze mismatch。`; new `Cedar review 当前主阻塞已经变成 approval packet missing。`
  Preferred: replace, because both memories describe the same tracked blocker chain at different times rather than two simultaneously active blockers.
- When one bounded historical record is later followed by an unbounded current summary of what the subject has now settled on, keep both memories instead of collapsing the historical record into the current summary.
- When earlier bounded records present alternative positions inside a session or review, keep those historical alternatives even if a later current summary states what the subject finally settled on.
  Example: existing bounded record `Session review-9 Round 1: 可以先按原窗口上线。`; new bounded record `Session review-9 Round 2: 必须先补回滚说明。`
  Preferred: coexist, because these are historical alternatives inside one bounded review.
  Example: existing bounded historical record `Round 2: 必须先补回滚说明。`; new current summary `当前决定已经变成先补回滚说明再排期上线。`
  Preferred: keep both, because the later summary states the settled conclusion while the bounded record remains useful history.
- If one candidate is a standing conclusion and another record is primarily evidence, explanation, or supporting detail for that conclusion, keep them as separate memories instead of collapsing them into one refresh.
- If one memory states the standing blocker, requirement, owner, or current state and another memory gives logs, observations, rationale, or supporting detail for that same state, keep both memories so later edge construction can connect them.
  Example: existing `Subject 当前主阻塞是配置漂移。`; new `部署日志显示配置漂移导致签名校验失败。`
  Preferred: keep both memories instead of refresh or replace, because the first memory is the standing blocker and the second memory is direct evidence explaining that blocker.
- If the new text explicitly says the current owner, blocker, requirement, or standing state has changed, prefer replace.
- If a newer memory adds another still-valid current requirement, condition, attachment, or prerequisite for the same handbook/checklist/policy/document rule without revoking the earlier requirement, prefer refresh instead of replace, and keep both the earlier requirement and the new supplement in the refreshed memory text.
- When the newer text is a supplement such as `最新补充`, `还必须`, `另外要求`, or a clearly additive current rule, treat it as cumulative unless the text explicitly says the earlier requirement no longer applies.
- If a correction note, amendment, appendix, addendum, or follow-up attachment note adds another still-valid requirement for the same current named artifact rule, treat it as cumulative current-state detail rather than a separate parallel standing rule. Prefer refresh so the current active rule memory accumulates the additive requirement.
  Example: existing `Heliotrope handbook 当前要求 fallback schedule 变更必须先经 incident lead 审批。`; new `Heliotrope handbook 最新补充：所有审批记录还必须附在 change packet 中。`
  Preferred: refresh the current-rule memory and preserve both `incident lead 审批` and `change packet` in the updated memory, because the newer note adds a complementary requirement instead of replacing the earlier one.
  Example: existing `Morrowfield register 当前要求每个 quay note 必须在 release 前提交。`; new `Appendix to Morrowfield register: every quay note must also include berth owner signature.`
  Preferred: refresh the current rule memory so the current active rule keeps both `before release` and `berth owner signature`, while the earlier looser rule remains a separate superseded historical memory.
- If a later current summary follows earlier bounded rounds or review alternatives, do not let the current summary delete those bounded historical records unless the new text explicitly says those bounded records were duplicate restatements of the same round.
- If two memories answer the same practical question in the same unbounded subject context, and the newer memory explicitly says the tracked blocker, requirement, owner, or standing state has changed from one concrete value to another, prefer replace even when both states are still useful history.
- For tracked blockers or tracked owners, `当前...已经变成...` should usually mean the earlier standing fact is superseded by the newer one.
  Example: existing `Summit rollout 当前主阻塞是数据库迁移失败。`; new `Summit rollout 当前主阻塞已经变成签名校验失败。`
  Preferred: replace, because both memories answer the same current-blocker question for the same subject, and the newer memory explicitly says the blocker changed.
- If structured records explicitly mark `phase: history` or another earlier-rule marker, keep that earlier rule/state queryable instead of dropping it as redundant.
- If structured records explicitly mark `phase: current` and a later `phase: supplement` for the same standing rule, prefer refresh so the current rule memory accumulates the supplement while the earlier historical rule remains separate.
  Example structured records: `record: Falconer handover notice`, `phase: history`, `rule: teams could attach seal note within 24 hours after shift`; then `phase: current`, `rule: every seal note must be completed before handover`; then `phase: supplement`, `rule: every seal note must also be attached to dispatch packet`.
  Preferred: keep one earlier historical rule memory plus one current active rule memory refreshed with the supplement.
- If an earlier unbounded document, handbook, charter, manual, bulletin, guide, or rule memory says the subject previously allowed action A, and a newer unbounded memory for the same artifact says the subject now requires approval, attachment, signoff, or another gate for that same action, treat that as one artifact's rule evolving over time. Prefer replace so the earlier rule becomes superseded via updates.
- If the older memory describes an earlier allowance or looser rule and the newer memory describes the current stricter rule for the same named artifact and same operational action, prefer replace even when the older rule is still useful history.
  Example: existing `Morrow charter 之前允许团队直接修改 transfer ledger。`; new `Morrow charter 当前要求所有 transfer ledger 变更必须先经 shift lead 审批。`
  Preferred: replace, because this is one artifact's rule evolving from an earlier allowance to the current stricter rule.
- If one long document simultaneously contains an earlier allowance, a current stricter rule, and an appendix/addendum/supplement for that same current rule, resolve it into one historical memory plus one current active memory refreshed with the additive requirement, not three separate standing memories.
- If one long document contains both an earlier allowance and a current stricter rule for the same named artifact, do not leave them as two peer active memories linked only by `contradicts`. Prefer replace so the earlier rule becomes superseded history linked by `updates`, while the current stricter rule remains the active head.
  Example long document: `Grayshore bulletin` says it earlier allowed berth note filing within 14 hours after release, the current section now requires filing before release, and an appendix adds `quay owner signature`.
  Preferred: keep one earlier superseded historical memory plus one current active memory refreshed with `quay owner signature`, linked by `updates`; if there is no existing persisted memory yet, let the newer current candidate target the earlier candidate_id from the same batch so the batch still resolves into superseded history plus one active head.
- Preserve important detail from the candidate memory instead of aggressively shortening it.
- Preserve critical concrete phrases from the source rather than replacing them with more generic rephrasings.
- Keep the memory in the same primary language as the input whenever possible.
- Do not emit repeated or near-duplicate resolution items for the same underlying claim.
- If multiple candidate memories from the same input are overlapping, keep only the most complete one and omit the near-duplicate ones from the output.
- One long report or one long debate record should usually resolve to one final memory unless there are clearly separate retrievable claims.
- target_memory_id may point either to an existing memory_id or to an earlier candidate_id from the same batch when the newer candidate should replace, refresh, or stale that earlier same-batch candidate.
- When using an earlier candidate_id from the same batch as target_memory_id, only do so for a clearly overlapping tracked subject where the later candidate is the newer current head or the more complete current version.
- If one batch contains an earlier historical candidate and a newer current candidate for the same named artifact or tracked blocker chain, prefer letting the newer candidate replace the earlier candidate directly inside the batch instead of leaving both as peer active memories.
- For same-batch earlier/current evolution, do not emit two `create` items that would leave both memories active when the newer candidate is clearly the current head.
- In that situation, keep the earlier historical candidate as the predecessor and let the newer current candidate use `action=replace` with `target_memory_id=<earlier candidate_id>`.
- Never set target_memory_id to the candidate's own candidate_id.
- The examples below use symbolic ids for readability; in the actual output you must use the exact short refs from the payload.
  Example same-batch candidates:
  - `cand_earlier`: `Grayshore bulletin 之前允许团队在 release 后 14 小时内提交 berth note。`
  - `cand_current`: `Grayshore bulletin 当前要求 berth note 必须在 release 前提交，并且必须包含 quay owner signature。`
  Preferred outputs:
  - `cand_earlier -> action=create`
  - `cand_current -> action=replace, target_memory_id=cand_earlier`
  This should produce one superseded earlier memory plus one active current memory linked by `updates`, not two peer active memories.
- When existing_memories include created_at timestamps, treat them as supplementary hints for temporal ordering only. The primary basis for determining historical vs current status must always be the explicit temporal wording inside the memory content itself (e.g., `之前允许`, `当前要求`, `最新补充`, `earlier`, `current`, `supplement`). Do not rely solely on created_at order to decide logical precedence.
- When a supplement candidate (marked by phrases like `最新补充`, `还必须`, `also required`, `appendix`, `addendum`, or `follow-up attachment`) appears alongside both an earlier historical rule and a later current active rule, the supplement MUST target the current active rule (action=refresh or replace with target=current), never the earlier historical rule. The historical rule remains separate and superseded; only the current active rule accumulates supplements.
  Example same-batch candidates with timestamps:
  - `cand_history` (created_at=10:00): `Northport guide previously allowed teams to file checklist within 6 hours after cutoff.`
  - `cand_current` (created_at=10:01): `Northport guide currently requires every checklist to be submitted before cutoff.`
  - `cand_supplement` (created_at=10:02): `Northport guide addendum: every checklist must also be attached to delivery manifest.`
  Preferred outputs:
  - `cand_history -> action=create`
  - `cand_current -> action=create`
  - `cand_supplement -> action=refresh, target_memory_id=cand_current`
  The addendum targets the current active rule, not the historical predecessor.
""".strip(),
    "query_planner": f"""
Extract query identity_profile drafts and short query rewrites.
Rules:
- {IDENTITY_PROFILE_RULES}
- Each query_identity_profile_draft must also include `query_text`, which is the shortest standalone sub-query from the original query that asks only about that draft's subject.
- For a single-subject query, `query_text` should usually be the full original query.
- For a multi-subject query, split the original query into one draft per subject and give each draft its own `query_text` that omits the other subjects.
  Example: `Atlas 发布项目 当前主阻塞是什么？Atlas 文档 当前缺什么？`
  Preferred drafts:
  - `{{"who":"Atlas 发布项目","query_text":"Atlas 发布项目 当前主阻塞是什么？"}}`
  - `{{"who":"Atlas 文档","query_text":"Atlas 文档 当前缺什么？"}}`
  Do not reuse the full multi-subject query as `query_text` for every draft.
- Treat concrete names in the query as valid stable subjects whenever they refer to a bounded subject with stable identity.
- If the query already contains one concrete named subject and the rest of the query only asks for its requirements, disagreements, reasons, blockers, history, or conditions, keep that named subject as the identity target instead of rejecting the query.
- If no stable subject can be identified from the query, return rejected_no_identity_profile.
- Keep query_rewrites short and focused.
- query_focus should only summarize retrieval intent, not final answer content.
- query_focus.time_intent must be one of current, latest, history, or unspecified.
- `graph_expansion_intent` is the query_focus field that controls dynamic cross-entity graph expansion.
- query_focus.graph_expansion_intent must be one of `entity_local`, `cross_entity`, or `uncertain`.
- Use `entity_local` when the query can be answered from the target entity's own recalled memory and local
  evidence, without needing another entity's memory to explain, constrain, or extend the answer.
- Use `cross_entity` when the query asks for why/how, dependency chains, surrounding constraints, related gaps,
  external requirements, or other-entity evidence that may explain the target subject.
- Use `uncertain` when the query has a stable target but you cannot confidently decide whether other-entity
  memory may be needed.
- Set query_focus.graph_expansion_reason to one short reason for that semantic decision.
- Do not decide graph expansion with keyword matching. Judge the retrieval need from the full query intent and
  the subject relationships implied by the query.
- Use history when the query is about prior records, earlier states, or change over time.
- If the query explicitly asks both what happened earlier and what is true now, still use history so recall expands the evolution instead of collapsing to only the current state.
  Example: `Cedar review 之前卡过什么，当前又变成什么？`
  Preferred: time_intent=history, because the query explicitly asks for both earlier and current states.
- Use latest when the query is about the newest known conclusion.
- Use current when the query is about the current standing state.
- External context includes other entities, documents, rules, handbooks, workflows, checklists, protocols, memos, upstream or downstream dependencies, constraint sources, adjacent risks, supplemental requirements, or neighboring records.
  Example: `除了当前主风险外，Arbor portfolio 还需要关注什么？`
  Preferred: keep `Arbor portfolio` as the identity target, because the user is asking for relevant context outside the primary entity's own current-state memory.
  Example: `Nimbus rollout 当前阻塞之外，还有哪些外部上下文？`
  Preferred: keep `Nimbus rollout` as the identity target, because the answer may depend on another workflow, document, rule, dependency, or neighboring record.
- If the query asks about historical disagreement and also asks why the subject later settled on the current conclusion, keep the primary subject as the identity target whenever an external handbook, checklist, policy, rule, or governing artifact could explain the settlement.
  Example: `为什么 Topaz transfer review 从历史分歧收敛到现在的结论？`
  Preferred: use `time_intent=history`, because the answer may depend on an external governing artifact that explains why the later conclusion became binding.
- If the query asks why a current blocker exists and also asks for related gaps, missing prerequisites, dependencies, or surrounding conditions, preserve both the direct explanation intent and the related-context intent in the rewrites instead of collapsing everything into a single generic why question.
- If the query asks for requirements, conditions, missing items, blockers, or preconditions, keep those concrete phrases visible in the rewrites instead of replacing them with generic wording.
- A named policy, handbook, guideline, report, project, document, or plan can be the subject of the query when the user asks what it requires, says, blocks, or contains.
  Example: `Gateway policy 有什么要求？`
  Preferred: keep `Gateway policy` as the stable subject, set time_intent to unspecified or current, and rewrite toward the concrete requirement question instead of rejecting the query.
- A named team, working group, crew, committee, or operations unit can also be the subject of the query when the user asks what it plans to do, what it will do next, what it owns, or what it is blocked by.
  Example: `Palisade team 接下来准备怎么做？`
  Preferred: keep `Palisade team` as the stable subject and preserve the future-plan wording instead of rejecting the query.
- Preserve concrete role nouns such as `rollout`, `service`, `checklist`, `runbook`, `policy`, `document`, `handbook`, or `plan` inside the identity draft when those nouns distinguish one same-surface subject from another.
  Example: `为什么 Verdigris rollout 还不能切换到新流程？`
  Preferred: keep `Verdigris rollout` as the identity target. Do not collapse it to bare `Verdigris` when another subject like `Verdigris checklist` also exists in the same scope.
  Example: `为什么 Summit plan 现在不能进入审批？`
  Preferred: keep `Summit plan` as the identity target. Do not collapse it into `Summit project` or `Summit checklist`, because `plan`, `project`, and `checklist` are different stable artifact roles.
- If the query asks what a named policy, rule, handbook, or document requires, keep that named artifact as the primary subject instead of rejecting the query for lacking a person/system style subject.
- If the query asks what a named team or working group will do next, keep that group name as the primary subject instead of rejecting the query for lacking a system or artifact role noun.
""".strip(),
    "cross_entity_query_builder": """
Generate a small set of retrieval query texts for finding memories that belong to other entities but may explain, constrain, depend on, or relate to the frontier memories.
Rules:
- Use the frontier memories and frontier observations together.
- Produce short retrieval-oriented query texts, not full answers.
- Prefer concrete shared concepts, requirements, constraints, missing prerequisites, upstream/downstream dependencies, document names, policy names, and operational conditions that could appear in another entity's memory.
- If the frontier memory names a blocker and the observations explain why that blocker exists, preserve both the blocker phrase and the explanatory phrase in the retrieval queries.
  Example frontier memory: `Lantern rollout 当前仍不能上线，因为审批链说明还没有补齐。`
  Example frontier observation: `Release governance guide 要求所有生产发布在执行前必须补齐审批链说明。`
  Good queries: `审批链说明 生产发布 要求`, `release governance guide 审批链说明`, `上线 受 审批链说明 约束`
  Example frontier memory: `Verdigris rollout 当前主阻塞是依赖数据源迟迟没有恢复。`
  Example frontier observation: `Relay service 当前仍处于批量补数状态，尚未恢复稳定输出。`
  Good queries: `数据源 恢复 稳定输出`, `data sync service 批量补数 稳定输出`, `上游服务 尚未恢复 稳定输出`
- If the frontier memory refers to an external requirement, missing document, policy, checklist, approval chain, upstream service, or neighboring gap, turn that into one or more retrieval queries that another entity's memory could match directly.
  Example frontier memory: `Heliotrope rollout 当前主阻塞是配置漂移。`
  Example frontier observation: `Baseline handbook 目前还缺少配置基线校验流程。`
  Good queries: `配置漂移 配置基线校验流程`, `configuration baseline handbook 配置基线校验流程`, `相关缺口 配置基线校验流程`
- If a direct governing artifact names multiple still-required items for the same subject, preserve those sibling required items in the retrieval queries instead of searching only for the one currently mentioned blocker.
- If one of those sibling required items could itself have an upstream attachment, approver, seal, roster, or other prerequisite, include that sibling item in at least one retrieval query so another artifact can extend the chain.
  Example frontier memory: `Rookery project 当前还不能推进，因为 transfer note 缺失。`
  Example frontier observation: `Parallax checklist 要求 transfer packet 补 transfer note 和 seal ledger；Keystone manual 要求 seal ledger 附 reviewer seal。`
  Good queries: `transfer note Parallax checklist`, `seal ledger reviewer seal Keystone manual`, `transfer packet seal ledger`
- If the frontier memory asks for related gaps, neighboring missing prerequisites, or adjacent readiness issues beyond the main blocker, emit narrow retrieval queries for any explicitly named missing validation flow, guardrail, prerequisite, or readiness process.
- Do not invent external entities that are not implied by the input.
- Do not repeat near-duplicate query texts.
- Return 2-6 query texts.
- Keep the queries in the same primary language as the input evidence whenever possible.
- If the frontier memory is itself only a secondary artifact/process-gap note, do not expand broadly into all nearby operational subjects just because they share the same incident or recovery area.
- In that case, only emit cross-entity query texts when the frontier memory explicitly names an external subject, direct dependency, or direct governing artifact that it is talking about.
- If the frontier memory does not explicitly name another subject and only describes an internal gap of its own artifact, returning an empty or very narrow query set is better than pulling in loosely related surrounding entities.
  Example frontier memory: `Response runbook 当前还缺少 escalation owner。`
  Good behavior: if this memory does not explicitly name another subject, do not expand into surrounding rollout or service entities just because they belong to the same broader recovery situation.
- If the frontier observation only gives a distractor artifact and not the concrete external failing state, do not let that artifact dominate the retrieval queries.
  Example frontier memory: `Verdigris rollout 当前主阻塞是依赖数据源迟迟没有恢复。`
  Example frontier observation: `Escalation handbook 当前缺少 on-call escalation path。`
  Good behavior: do not let the handbook dominate retrieval for the upstream-impact question; prefer query texts that search for the actual external failing service or source state.
""".strip(),
    "answer_composer": """
Compose the final user-facing answer using the candidate memories, relation edges, and observations.
Rules:
- Keep the answer concise and directly responsive to the query.
- Treat every memory in `memories` as a candidate. There is no preselected answer subset.
- Choose the evidence yourself from the full candidate set and relation graph.
- First decide whether the query is asking for the target subject's own current answer, or asking for explanation chain, dependency chain,
  upstream constraints, or surrounding context.
- If the query is asking only for the target subject's own current requirement, status, goal, decision, blocker, or content, answer only with
  that direct target-level answer.
- In that narrow-query case, `supports` and `related_to` memories may help you understand the evidence, but they do not automatically belong in
  the final answer text.
- Return citations using only memory_id and observation_id values present in the input payload.
- If citations are provided in your output, use them to express evidence in natural language instead of listing raw ids.
- Keep evidence short; one short evidence sentence is enough unless the query explicitly asks for more.
- Do not invent facts outside the provided payload.
- Each memory may include `evidence_role`, `relation_types`, and `relation_edges`; use these fields to decide whether the memory is direct evidence, supporting evidence, conflicting evidence, update/history evidence, or weak background.
- Use `seed`, `updates`, and `contradicts` memories as answer evidence when they address the query.
- Treat `supports` memories as explanatory context. Use them in the answer only when the query asks for reasons, dependencies, external
  constraints, why the current answer holds, or what still needs to be satisfied beyond the direct target answer.
- For narrow target-property questions, keep the answer scoped to the requested target. Do not add a supporting memory's
  own independent state as an extra answer clause.
- Treat memories that are only `related_to` as background. Do not add facts from them to the answer unless the query explicitly asks for
  related, adjacent, surrounding, or background context.
- When a memory is `background_only` or only `related_to`, do not promote it into an answer claim just because it is semantically relevant.
- If a supporting or related memory only adds an upstream detail for one sub-item inside the target answer, do not include that upstream detail
  unless the query explicitly asks for that deeper layer.
- A governing handbook/manual/policy/checklist can be relevant without being part of the answer. Mention it only when the query actually asks
  for the governing reason, upstream rule, dependency chain, or still-required next layer.
- When the query asks for key drivers, core risks, or main reasons, enumerate the top points explicitly and keep the important evidence terms visible instead of replacing them with generic paraphrases.
- If a critical term appears in the evidence, prefer repeating that term directly in the answer.
- If the query asks for the most important, core, or main point, answer with only the 1-3 central points instead of broadening into a full summary.
- Avoid adding peripheral details when the query is narrowly focused on the top driver, top risk, or main reason.
- If the evidence gives a specific manifestation of a broader concept, name both in the answer using `broad concept (specific manifestation)` style when possible.
- Prefer a `broader concept (specific manifestation)` form only when the broader concept is genuinely supported by the evidence.
- Keep the wording aligned with the language of the evidence. Do not translate away key source phrases when they are already concise and clear.
- When the query asks for explicit requirements, conditions, missing items, blockers, or timings, preserve those concrete phrases directly in the answer.
- Example narrow query:
  Query: `Lattice checklist 当前要求补齐什么？`
  Seed evidence: `Lattice checklist requires transfer note and seal ledger.`
  Related evidence: `Lattice handbook says seal ledger must include reviewer seal.`
  Preferred answer: `Lattice checklist 当前要求补齐 transfer note 和 seal ledger。`
  Not preferred: adding `reviewer seal`, because that is a deeper upstream detail rather than the direct checklist answer.
- Example narrow query:
  Query: `Merrow plan 当前目标是什么？`
  Seed evidence: `Merrow plan aims to finish the launch packet this week.`
  Related evidence: `Merrow register requires the launch packet to include duty roster.`
  Preferred answer: `Merrow plan 当前目标是本周完成 launch packet。`
  Not preferred: adding `duty roster` unless the query asks what the packet still depends on.
- Example explanation query:
  Query: `为什么 Lattice checklist 还不满足？`
  Seed evidence: `Lattice checklist requires transfer note and seal ledger.`
  Supporting evidence: `Lattice handbook says seal ledger must include reviewer seal.`
  Preferred answer: it is valid to mention both the checklist requirement and the handbook's extra reviewer-seal requirement, because the query is asking why the requirement is still not satisfied.
- Example dependency query:
  Query: `Merrow plan 要完成目标还依赖什么？`
  Seed evidence: `Merrow plan aims to finish the launch packet this week.`
  Related evidence: `Merrow register requires the launch packet to include duty roster.`
  Preferred answer: it is valid to mention `duty roster`, because the query is explicitly asking for dependencies rather than only the plan's direct goal.
- If the answer depends on multiple linked artifacts, prefer this order:
  1. the subject's immediate blocker or missing item
  2. the direct governing artifact that requires it
  3. only then any more upstream handbook, policy, or supplement
- The linked-artifact expansion rules below apply only when the query actually needs that longer chain.
- Do not expand to the full chain for a narrow target-property query if the target-level answer is already complete without that chain.
- If the query asks for both historical disagreement and the current settled reason, include one short sentence for the disagreement and one short sentence naming the external handbook/checklist/policy when that artifact explains why the current conclusion now holds.
- If the current settled conclusion matches a named external handbook, checklist, policy, or rule in the evidence, explicitly say that the current conclusion now follows or is constrained by that artifact instead of only citing the historical round outcome.
- For history/current disagreement answers, do not rely on citations alone to imply the governing artifact. If a named handbook, decree, checklist, policy, or rule explains the settlement, say that artifact name in the answer text.
  Example evidence: `Juniper review` historically disagreed about whether it could proceed, but now requires a `variance ledger`; `Fathom handbook` also requires that ledger before release.
  Preferred answer: say both the historical split and that `Fathom handbook` is the external reason the current decision settled on the stricter requirement.
  Example evidence: `Topaz transfer review` historically split over whether it could proceed, but now requires a `ballast note`; `Harbor decree` independently requires that `ballast note`.
  Preferred answer: explicitly say that `Harbor decree` is the external reason the current decision settled on the stricter requirement.
- If an earlier historical position is represented by a short phrase such as `initial launch slot`, keep that short phrase visible in the answer when possible instead of replacing it with a broader paraphrase.
  Example evidence: `Cairn transfer review` historically supported the `initial launch slot`.
  Preferred answer: keep `initial launch slot` visible, or use a very close equivalent, rather than replacing it with a vague phrase like `the earlier approach`.
- Do not skip the direct governing artifact when it is present in the evidence.
- Do not skip the concrete upstream required item either when that item explains why the direct requirement is still incomplete.
- If the evidence contains a longer chain and each upstream memory still contributes a concrete required item, keep the full chain in compressed form instead of truncating at the middle layer.
  Example evidence: `Marble rollout` is blocked because `approval matrix` is missing; `Signal checklist` directly requires that matrix; `Charter handbook` further says the `approval matrix` must include `escalation owner`.
  Preferred answer: mention `Signal checklist` explicitly before `Charter handbook`, and keep `escalation owner` visible instead of mentioning the handbook only by name.
  Example additional layer: `Relay register` further says the `escalation owner` record must include `on-call roster`.
  Preferred answer: keep that final concrete prerequisite in the answer too instead of stopping at `Charter handbook`.
- If the evidence contains a direct missing item plus another co-required item named by the same direct checklist or manual, keep both in the answer when an upstream artifact extends the second item with another concrete prerequisite.
  Example evidence: `Sable checklist` says the subject still needs both `transfer note` and `seal ledger`; `Merrow manual` says the `seal ledger` must include `reviewer seal`.
  Preferred answer: say all of `transfer note`, `Sable checklist`, `seal ledger`, and `reviewer seal` instead of answering with only the first missing item.
- Prefer a compact `missing item -> direct artifact -> upstream requirement -> final concrete prerequisite` structure when that full chain is present and still necessary.
""".strip(),
    "answer_judge": """
Evaluate whether the provided final answer correctly answers the query and stays grounded in the supplied evidence.
Rules:
- Use only the query, required facts, required_fact_groups, forbidden facts, answer, citations, and uncertainties from the payload.
- Return pass only when the answer covers all required facts without introducing forbidden facts.
- Prefer required_fact_groups when present. Each group is satisfied when any listed variant, or a clear semantic equivalent, is expressed anywhere in the answer.
- If one required fact is written as `A || B || C`, treat it as an any-of group and count the requirement as satisfied when any listed variant is clearly covered.
- Before returning partial for a missing required-fact group, explicitly re-check the answer text itself. If any variant from that group appears verbatim, or appears as a close mixed-language phrase with the same predicate, that group is covered and must not be reported as missing.
- Do not mark an any-of group missing merely because the answer mentions it in the historical-disagreement part and then later explains a newer/current conclusion.
- Historical-position groups are covered when the answer states that historical position anywhere in the answer; they do not need to be the final current conclusion.
- If your reason says a group is missing, none of that group's variants may appear verbatim in the answer text.
- Return partial when the answer is directionally correct but incomplete, weakly grounded, or misses part of the required facts.
- Return fail when the answer is wrong, unsupported, contradictory to evidence, or contains forbidden facts.
- grounded must be false if the answer makes claims not supported by the provided citations or evidence.
- Treat close lexical variants, explicit supersets, or narrower phrasings as satisfying a required fact when they clearly express the same concept.
- Examples: `偿付能力监管标准` satisfies `偿付能力监管`; `流动性完全丧失` satisfies `流动性`.
- Treat each forbidden fact as a complete claim, not as a bag of words. Do not fail only because the answer shares an entity name,
  artifact name, item name, or topic noun with a forbidden fact.
- Fail for a forbidden fact only when the answer asserts the same forbidden predicate/status/causal claim, or an equivalent claim.
- Do not derive forbidden facts through extra-world inference. A rule about what an item record must contain does not say whether
  that item is missing, present, complete, blocking, or non-blocking unless the answer explicitly says so.
- Claims can share the same noun while saying different predicates. `X missing` is different from `X record must include Y`; the
  second claim is not forbidden unless it also says `X` is missing or blocking.
- Example: required fact `Verdigris manual 要求所有 Cobalt seal 记录附 Gateway stamp`; forbidden fact
  `Cobalt seal missing`; answer `Verdigris manual 要求所有 Cobalt seal 记录附 Gateway stamp。` is pass, because it
  says a record-content requirement and does not claim that `Cobalt seal` is missing or blocking.
- If a required fact appears inside a larger bilingual or mixed-language clause, count it as satisfied when the clause clearly preserves that fact.
- Example: `Round 1 支持按 initial launch slot 进行` satisfies the required fact `initial launch slot`.
- If the answer literally names one listed artifact, requirement, item, or role from a required-fact group, count that group as satisfied. Do not mark it missing just because the same sentence also contains a longer causal explanation.
- If the answer literally includes both a named artifact and its concrete requirement in one clause, treat both as covered even when the clause adds another consequence or implication.
- Example: `Lantern checklist 明确要求补 Trellis note 和 Bastion ledger，而 Opal manual 进一步要求所有 Bastion ledger 记录附 Selene seal。` satisfies the required groups `Lantern checklist || checklist` and `Selene seal || Opal manual || manual`.
- Extra grounded details do not reduce a pass result as long as all required facts are covered and no forbidden facts are introduced.
- Keep reason short and concrete.
""".strip(),
    "profile_writer": f"""
Rewrite the entity identity profile from current profile and recent identity signals.
Rules:
- {IDENTITY_PROFILE_RULES}
- Keep the same subject identity.
- surface_forms must stay short and concrete.
- stable_qualifiers must stay as short keywords or phrases.
- Do not promote blocker, owner value, requirement content, current state, or other salient memory facts into the identity profile just because they appear frequently in recent memories.
- Do not invent entity_key or memory ids.
""".strip(),
    "edge_judge": """
Judge whether the source memory has supports, contradicts, or related_to relations with candidate memories.
Rules:
- The payload may describe either a local entity graph or a cross-entity graph.
- If `original_query` and `query_identity_profile` are present, use them to decide what the current recall is actually trying to answer before judging relations.
- Return complete relation edges, not source-relative targets.
- Every returned relation must include:
  - from_memory_id
  - to_memory_id
  - edge_type
  - reason
  - weight
- Only return relations for memory ids present in the payload.
- Every memory includes `identity_profile`; use it to decide which stable subject the memory belongs to before judging relations.
- If `query_identity_profile` is present, treat that subject as the answer target for this recall step.
- Different identity_profile subjects with the same prefix are not related just because they share that prefix, domain, project,
  readiness theme, or similar missing-detail wording.
- Use supports only when one memory is direct evidence, direct explanation, or a direct external requirement for another memory's claim.
- In cross-entity mode with `original_query`, judge supports against the current query target, not only against abstract semantic relatedness.
- For narrow target-property questions such as asking what the target currently requires, lacks, says, decides, or aims for, prefer `none`
  or `related_to` for upstream artifact details unless that external memory is itself part of the target's direct answer.
- If a candidate memory only adds a more detailed upstream rule for one sub-item inside the frontier memory, that usually does not support
  the frontier memory for a narrow query about the frontier subject's own current requirement/status/goal.
- A governing artifact can be semantically relevant without being answer-critical for the current query. Do not turn every relevant upstream
  constraint into supports.
- If one memory states a policy, requirement, or standing rule and another memory reports concrete violations, delays, incidents, or repeated failures to satisfy that rule, the operational note usually supports why the rule matters; it does not contradict the rule unless it explicitly denies the rule itself.
- If one memory states a standing policy, checklist, bulletin, or rule and another memory is an audit note, review note, or operational note showing repeated timeout, delay, miss, or failure to satisfy that rule, prefer supports from the note to the rule-bearing memory.
- In local_graph mode, do not drop that support edge just because the note and the rule can already answer the question without it. The rule-bearing memory is the main claim, and the audit or operational note is direct support.
- If one memory states a standing rule or requirement and another memory gives the concrete observed reason the rule is emphasized, emit supports even when the pair could also be described as adjacent context. Prefer the direct support edge over omitting the relation.
  Example main rule: `Ivory access bulletin 要求所有临时权限在 24 小时内完成回收。`
  Example audit note: `Ivory access bulletin 的审计备注显示临时权限回收多次超时。`
  Preferred edge: `audit note -> main rule = supports`, because the note explains why the rule is emphasized.
  Example main rule: `Quartz retention notice 要求所有临时凭证在 12 小时内完成回收。`
  Example operational note: `Quartz retention notice 的审计补充说明显示临时凭证回收多次延迟。`
  Preferred edge: `operational note -> main rule = supports`. Do not return `none` just because the note and the rule are both already understandable on their own.
- Use contradicts only when two memories make conflicting or mutually incompatible claims.
- If two bounded records from the same session, review, or decision context present mutually incompatible alternatives, use contradicts even when both are historical.
- Use related_to when two memories are clearly about the same broader issue but neither directly supports nor directly contradicts the other.
- Example query: `Lattice checklist 当前要求补齐什么？`
  Example frontier identity: `{"who":"Lattice checklist","stable_qualifiers":["checklist"]}` with memory `Lattice checklist requires transfer note and seal ledger`.
  Example candidate identity: `{"who":"Lattice handbook","stable_qualifiers":["handbook"]}` with memory `Lattice handbook says seal ledger must include reviewer seal`.
  Preferred edge: `related_to` or `none`, because the handbook adds an upstream detail for one checklist item but is not itself the direct answer to the narrow checklist query.
- Example frontier identity: `{"who":"Driftbay map","stable_qualifiers":["map"]}` with memory `Driftbay map lacks contour markers`.
  Example candidate identity: `{"who":"Driftbay survey","stable_qualifiers":["survey"]}` with memory `Driftbay survey is blocked because field notes are missing`.
  Preferred edge: `none`, because these are sibling subjects with different missing details; same prefix and same broad documentation theme are not enough.
- Missing process, workflow, readiness, or prerequisite information should usually be related_to, not supports, unless the memory explicitly states that the missing item directly proves or directly requires the target claim.
- A missing guardrail, missing validation step, or missing readiness process should usually be related_to a blocker or failure memory when it explains adjacent context but does not itself directly observe the failure.
- In an explanation chain, direct evidence should support the main claim, while adjacent missing prerequisites or process gaps should usually be related_to.
- When one memory is direct evidence for the main claim and another memory is a neighboring missing prerequisite or missing process, preserve both relation types if both are independently useful: evidence should support the main claim, and the neighboring gap should remain related_to the main claim.
- Do not omit the main-claim related_to edge just because another memory already provides a supports edge in the same local graph.
  Example main claim: `Heliotrope rollout 当前主阻塞是配置漂移。`
  Example direct evidence: `部署日志显示配置漂移导致签名校验失败。`
  Example adjacent gap: `缺少配置基线校验流程。`
  Preferred edges: `direct evidence -> main claim = supports`; `adjacent gap <-> main claim = related_to`; do not also connect `adjacent gap` to `direct evidence` unless that second relation is independently necessary.
- When one memory is a later current conclusion and another memory is an earlier historical record from a prior round, stage, or session, do not add contradicts just because the later conclusion differs. Historical evolution should usually be represented by updates/history, not by contradicts between current and superseded records.
- Use contradicts mainly for peer alternatives that coexist as competing claims, not for an old historical position versus a newer settled position.
- If two historical records disagree with each other, contradicts is appropriate. If a newer current record replaces an older historical record, prefer no contradicts edge unless the payload clearly presents them as still-active competing positions.
- Prefer a minimal graph that preserves the strongest explanation path instead of connecting every plausible hop.
- Prefer a sparse graph.
- Prefer the smallest edge set that still answers the local question. If one direct support and one adjacent context edge already explain the situation, do not add extra second-order related_to edges between those supporting and adjacent nodes.
- Do not connect every pair just because they share topic words.
- In a local graph, first identify the main claims, then connect only the strongest direct supports or contradictions.
- When one memory directly supports a main claim and another memory is only adjacent context or a missing prerequisite, connect the adjacent context to the main claim only. Do not also connect that adjacent context to the supporting evidence unless the payload makes that second relation independently necessary.
- When several memories form a history of disagreement plus a later settled summary, keep contradicts on the bounded peer alternatives that directly disagree. Do not also connect the later settled summary to every older alternative with contradicts unless the payload clearly says the current summary remains an active competing position.
- If a later current summary resolves earlier disagreement, prefer one contradicts edge among the historical alternatives and let recall use history/current structure to explain the settlement, instead of emitting extra contradicts edges from the settled summary.
  Example historical alternative A: `Round 1: 可以先按原窗口上线。`
  Example historical alternative B: `Round 2: 必须先补回滚说明。`
  Example later summary: `当前决定已经变成先补回滚说明再排期上线。`
  Preferred edges: one `contradicts` edge between the historical alternatives; avoid adding extra `contradicts` edges from the later settled summary unless the payload clearly says the summary is still an active competing position.
- In a cross-entity graph, only connect frontier memories to external candidate memories when the external memory directly explains, constrains, or conflicts with the frontier memory.
- In cross-entity mode, every returned edge must connect one frontier memory and one candidate memory. Do not emit frontier-to-frontier edges or candidate-to-candidate edges.
- In cross-entity mode, default to `none` unless the external memory contributes a direct external explanation, direct governing requirement, direct dependency state, or direct contradiction for the frontier memory.
- In cross-entity mode with `original_query`, a direct governing requirement is still not enough for supports when the query is only asking for the
  frontier subject's own immediate current answer and the external memory merely adds another layer of detail for one sub-item.
- In cross-entity mode, do not use `contradicts` between a bounded historical round/session record and an unbounded external standing rule merely because the old historical position would not satisfy the rule. The rule should support or constrain the later/current settled requirement; the historical disagreement should be represented among peer historical alternatives.
  Example historical alternative A: `Round 1: 可以按 initial slot 转运。`
  Example historical alternative B: `Round 2: 必须先补 tow manifest。`
  Example external statute: `Harbor statute 要求所有转运决定先附 tow manifest。`
  Preferred edges: one `contradicts` edge between the two historical alternatives, and a support/constraint edge from the statute to the later/current manifest requirement when that current memory is present. Do not add a cross-entity `contradicts` edge between the statute and the older Round 1 record.
  Example frontier memory: `Cedar handbook 规定 rollback annex 还必须附 reviewer charter。`
  Example candidate memory: `Relay register 要求 reviewer charter 记录补齐 on-call roster。`
  Preferred edge: connect `Cedar handbook` to `Relay register` as a frontier-to-candidate edge, because the candidate adds the next still-required concrete prerequisite in the same requirement chain. Do not re-emit edges only among the frontier memories in cross-entity mode.
- In cross-entity mode, a named external handbook, manual, checklist, bulletin, or guide may still be related_to the frontier blocker when it states a concrete missing validation flow, readiness gate, or prerequisite that is itself the neighboring gap being asked about.
- Use related_to for that adjacent external gap when the missing process or guardrail is explicitly named and would still leave the subject unready, even if it is not the single direct blocker.
  Example frontier blocker: `Radian rollout 当前主阻塞是配置漂移。`
  Example candidate artifact gap: `Baseline handbook 目前还缺少配置基线校验流程。`
  Preferred edge: `related_to`, because the handbook memory names a concrete neighboring gap that is still relevant to rollout readiness, even though it is not the same thing as the current blocker itself.
- Mere participation in the same incident, recovery process, or surrounding workflow is not enough for a cross-entity edge.
- Prefer the smallest cross-entity explanation set. If one external memory already provides the concrete failing dependency, upstream service state, unresolved source state, or other direct operational explanation, do not also emit weaker cross-entity edges to procedural artifacts that merely describe adjacent process gaps or response materials.
- If one memory says a rollout or review is blocked by an unresolved external data source, upstream service, or dependency, and another memory describes that external service still being degraded, backfilling, unavailable, or not yet stable, prefer related_to between the blocker memory and the external service memory.
- If a handbook, checklist, document, or report is present but does not itself describe the concrete external failure or direct governing requirement, return `none` for that artifact even if it belongs to the same incident or recovery process.
- When both a concrete external service-state memory and a handbook/checklist/document memory are present, prefer the concrete service-state edge and omit the artifact edge unless the artifact itself is the thing directly constraining or causing the frontier blocker.
  Example main claim: `Verdigris rollout 当前主阻塞是依赖数据源迟迟没有恢复。`
  Example external service: `Relay service 当前仍处于批量补数状态，尚未恢复稳定输出。`
  Example distractor artifact: `Escalation handbook 当前缺少 on-call escalation path。`
  Preferred edges: `external service <-> main claim = related_to`; `distractor artifact = none`. Do not connect the handbook unless the payload explicitly says the handbook itself is the direct blocker or governing requirement. Prefer the concrete service-state edge over weaker adjacent handbook context.
  Example main claim: `Cobalt rollout 当前被上游队列恢复缓慢影响。`
  Example concrete external state: `Queue service 仍在 replay backlog，尚未恢复稳定消费。`
  Example adjacent artifact: `Response runbook 当前还缺少 escalation owner。`
  Preferred edges: only `concrete external state <-> main claim = related_to`; `adjacent artifact = none`. Omit the runbook edge because it is secondary process context, not the direct external explanation.
- If the frontier memory itself is a secondary artifact/process-gap note and a candidate memory is only a primary operational blocker or neighboring incident state, default to `none` unless the frontier note explicitly says it constrains, explains, or governs that candidate.
- Shared incident membership, shared recovery area, or shared escalation context is not enough for a cross-entity edge from a secondary artifact gap to a primary blocker.
  Example frontier artifact gap: `Response runbook 当前还缺少 escalation owner。`
  Example candidate blocker: `Cobalt rollout 当前被上游队列恢复缓慢影响。`
  Example candidate service state: `Queue service 仍在 replay backlog，尚未恢复稳定消费。`
  Preferred edges: `none`. The runbook gap is secondary artifact context; it should not create new cross-entity edges back into the primary blocker chain unless it explicitly states that the missing runbook step is itself the direct blocker or governing requirement.
- In cross-entity mode, prefer the edge to flow from the primary blocker or requirement memory toward the concrete external explanation. Do not add the reverse artifact-to-blocker edge just because the artifact is contextually nearby.
- For contradicts and related_to, do not emit both directions.
- Do not emit empty reasons.
""".strip(),
    "merge_judge": """
Decide whether two entities should merge.
Rules:
- Return merge only when they clearly refer to the same subject.
- Shared topic, shared requirement, shared blocker, shared workflow, or shared surrounding context is not enough for merge.
- Do not merge an actor/system/project/person with a document/policy/checklist/report/handbook artifact just because the artifact constrains, explains, or is mentioned by the actor.
  Example source: `Ledger service`
  Example target: `Compliance checklist`
  Preferred: keep_separate. The service is the constrained subject; the checklist is a named artifact that imposes a requirement. They are related, not the same subject.
  Example source: `Lantern rollout`
  Example target: `Release governance guide`
  Preferred: keep_separate. The rollout is governed by the guide, but the guide is not the rollout.
- Do not merge a plan with a project, or a plan with a checklist/document/policy artifact, just because they share the same short name or appear in the same approval workflow.
  Example source: `Summit plan`
  Example target: `Summit project`
  Preferred: keep_separate unless the payload explicitly shows they are two names for the exact same artifact. A plan and a project are normally different stable subjects.
- Do not merge two entities just because one entity is governed by, blocked by, or depends on the other.
- If one entity is the thing acting or being blocked, and the other is the rule, checklist, report, handbook, plan, or requirement that constrains it, keep them separate.
- If two entities have different stable identity types or different stable functions, keep_separate even when they share the same process or same issue.
- Merge only when both entities are two names, aliases, or descriptions of the same concrete subject, and their memories could be viewed as belonging to one identity without losing an important subject boundary.
  Example source: `Meridian 项目`
  Example target: `Meridian 发布项目`
  Preferred: merge if the evidence shows they are two names for the same concrete project.
- If merge, pick the better survivor_entity_key from the provided two candidates.
- If uncertain, return keep_separate.
""".strip(),
}


def get_worker_instructions(worker_type: str) -> str:
    if worker_type == "same_batch_resolver":
        return """
Resolve candidate memories against synthetic same-batch memories that represent earlier candidates from the same ingest batch.
Rules:
- Existing memories in this worker may be synthetic placeholders that represent earlier candidates from the same batch.
- Existing memories in this worker use short memory refs like `m1`; when you target an earlier same-batch placeholder, use that memory ref.
- Use those synthetic placeholders to normalize one batch of earlier/current evolution into the final persisted shape before anything is written.
- When a later candidate states the newer current rule, current blocker, or current standing state for the same artifact, it should usually target the earlier same-batch placeholder memory ref with action=replace instead of producing two peer active creates.
- Never target your own candidate ref, and never invent a memory ref.
- Prefer one superseded earlier memory plus one active current head when the batch expresses a clear earlier/current evolution for the same practical question.

""".strip() + "\n\n" + WORKER_INSTRUCTIONS["resolver"]
    return WORKER_INSTRUCTIONS[worker_type]
