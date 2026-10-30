# LLM-as-judge（可选）

默认评估用的是“模拟质量分”（模型目录里的 `quality_score` 加噪声）。
配置一个 judge 模型后，评估会改成让 judge 按 rubric 打分。

## 配置

```bash
$env:MODELOPS_JUDGE_BASE_URL="https://api.siliconflow.cn/v1"
$env:MODELOPS_JUDGE_API_KEY="sk-..."
$env:MODELOPS_JUDGE_MODEL="Qwen/Qwen2.5-72B-Instruct"
```

然后：

```bash
python scripts/eval_demo.py --judge
```

或者走 API：

```bash
curl -X POST http://127.0.0.1:8080/api/evaluations/run \
  -H "X-Admin-Token: admin-demo" \
  -H "Content-Type: application/json" \
  -d '{"judge": true}'
```

## Rubric

`app/judge.py` 里的提示词要求从三个维度打分：

- 准确性
- 完整性
- 格式

输出 1–10 的整数，脚本用正则取第一个数字。

## 回退

- 没配环境变量 → 用模拟分。
- judge 调用失败 / 返回解析不出数字 → 用模拟分，不中断评估。
- 报告里会写“评分方式：LLM-as-judge”或“模拟质量分”。

## 注意

- judge 本身也有偏差，真实项目要做双人标注校准。
- judge 调用会产生费用；20 条 prompt × N 个模型，成本可控，但别跑 1,000 条。
- judge 的分数不应该直接当“绝对质量”，更适合做相对比较。
