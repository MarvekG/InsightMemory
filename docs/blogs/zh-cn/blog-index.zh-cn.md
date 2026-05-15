# InsightMemory 技术博客草稿索引

[返回 README](../../../README.zh-cn.md)

这些文章是面向外部技术博客、社区帖子和项目推广的发布草稿。写法上不再是 README 的补充说明，而是围绕一个更强的判断展开：

> AI Agent 真正的护城河，不只是模型能力，而是能不能持续形成、维护和解释长期记忆。

InsightMemory 要表达的核心定位是：它不是“向量库 + prompt”的又一次封装，而是一套面向 LLM 应用的 entity-centered、evolvable、traceable memory layer。换句话说，它试图把 memory 从“检索插件”推进到 AI 应用的持续认知层。

## 推荐发布顺序

1. [为什么只靠向量检索做不好长期记忆](./blog-why-vector-memory-fails.zh-cn.md)
2. [从 chunk 到 entity：LLM 应用为什么需要以主体为中心的记忆](./blog-entity-centered-memory.zh-cn.md)
3. [让 AI 记住“现在”和“过去”：长期记忆里的演进建模](./blog-memory-evolution.zh-cn.md)
4. [为什么长期记忆必须能解释答案：带证据链的 why/how 召回](./blog-evidence-backed-recall.zh-cn.md)

## 发布策略

第一篇适合做项目首发，用来打破“memory 等于向量检索”的默认认知。标题要强，正文要直接指出现有方案的痛点。

第二篇适合发给做 Agent、Copilot、知识库和企业 RAG 的开发者，重点讲“这条记忆属于谁”为什么是长期记忆的第一性问题。

第三篇适合讲深一点，突出 current vs historical、update、conflict、support 这些能力，让项目看起来不只是 demo，而是在解决长期运行后的真实问题。

第四篇适合面向企业 AI、知识管理和审计场景，强调 grounded answer、citation、observation trace 和可调试性。

## 发布时建议附带的信息

仓库链接：

```text
GitHub: https://github.com/MarvekW/InsightMemory
```

项目一句话：

```text
InsightMemory 是一个 LLM-native 长期记忆系统，用 entity、memory、observation 和 edge 把 AI 的长期记忆
从相似检索升级为可演进、可追溯、可关联推理的持续认知层。
```

支持方式：

```text
项目仍在快速迭代中。如果你愿意提供 LLM API-KEY、调用额度、评测 case 或真实接入反馈，欢迎联系作者。
请不要在公开评论区粘贴 API Key。
```
