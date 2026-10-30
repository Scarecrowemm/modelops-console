from app import evaluation, judge


def test_judge_scores_are_used(monkeypatch, fresh_db):
    monkeypatch.setattr(judge, "available", lambda: True)
    monkeypatch.setattr(judge, "score", lambda prompt, response: 9.0)
    results = evaluation.run(["deepseek-chat"], use_judge=True)
    assert results[0]["judge_used"] is True
    assert results[0]["quality_score"] == 9.0
    assert results[0]["pass_rate"] == 1.0
