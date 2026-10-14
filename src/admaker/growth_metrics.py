"""Operator-only SQL report: python -m admaker.growth_metrics. No public endpoint."""
import json
import os
import psycopg


def growth_metrics(database_url):
    with psycopg.connect(database_url) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        stages = dict(c.execute("SELECT name,count(DISTINCT account_id) FROM app.growth_events WHERE day>=CURRENT_DATE-30 GROUP BY name"))
        stages["uploaded"] = c.execute("SELECT count(DISTINCT owner_id) FROM app.assets WHERE verification_state='verified'").fetchone()[0]
        stages["generated"] = c.execute("SELECT count(DISTINCT owner_id) FROM app.jobs WHERE state='delivered'").fetchone()[0]
        stages["publishedSelfReported"] = c.execute("SELECT count(DISTINCT account_id) FROM app.campaign_outcomes WHERE result->>'published'='true'").fetchone()[0]
        stages["repeatCampaign"] = c.execute("SELECT count(*) FROM (SELECT owner_id FROM app.campaigns GROUP BY owner_id HAVING count(*)>=2) a").fetchone()[0]
        retention = c.execute("""WITH completed AS (
            SELECT j.owner_id,g.campaign_id,min(e.occurred_at) AS finished
            FROM app.campaign_generations g JOIN app.jobs j ON j.id=g.job_id
            JOIN app.job_events e ON e.job_id=j.id AND e.detail->>'state'='delivered'
            GROUP BY j.owner_id,g.campaign_id
        ), ranked AS (
            SELECT *,row_number() OVER(PARTITION BY owner_id ORDER BY finished,campaign_id) AS sequence,
                min(finished) OVER(PARTITION BY owner_id) AS first_finished FROM completed
        ) SELECT count(*) FILTER(WHERE sequence=1),
            count(*) FILTER(WHERE sequence=2 AND finished<=first_finished+interval '28 days')
            FROM ranked WHERE first_finished<=now()-interval '28 days'""").fetchone()
        costs = c.execute("SELECT g.campaign_id,count(a.id),coalesce(sum(a.actual_cost_microusd),0),count(a.id) FILTER(WHERE a.actual_cost_microusd IS NULL),coalesce(sum(a.estimated_cost_microusd),0) FROM app.campaign_generations g JOIN app.job_runs r ON r.job_id=g.job_id LEFT JOIN app.job_attempts a ON a.run_id=r.id GROUP BY g.campaign_id").fetchall()
        reviews = dict(c.execute("SELECT g.campaign_id,coalesce(sum(b.amount_microusd),0) FROM app.campaign_generations g JOIN app.job_runs r ON r.job_id=g.job_id JOIN app.media_review_budget b ON b.run_id=r.id GROUP BY g.campaign_id"))
        reports = dict(c.execute("SELECT g.campaign_id,count(*) FROM app.result_reports x JOIN app.campaign_generations g ON g.job_id=x.job_id GROUP BY g.campaign_id"))
        allocated = c.execute("SELECT campaign_id,storage_microusd,support_microusd,payment_fees_microusd FROM app.campaign_operating_costs").fetchall()
    return {"stages": stages, "retention28Days": {"maturedAccounts": retention[0], "secondDistinctCompletedCampaign": retention[1]}, "interpretation": "Opt-in events: distinct accounts in last 30 days. Operational stages: all-time, not a conversion cohort. Retention uses accounts whose first completed campaign was at least 28 days ago. Export means handoff, not publication. Outcomes are self-reported.",
            "campaignCosts": [{"campaignId": str(r[0]), "providerAttempts": r[1], "knownActualMicrousd": int(r[2]), "unknownActualAttempts": r[3], "estimatedProviderMicrousd": int(r[4]), "reviewBudgetMicrousd": int(reviews.get(r[0], 0)), "supportReports": reports.get(r[0], 0)} for r in costs],
            "allocatedOperatingCosts": [{"campaignId": str(r[0]), "storageMicrousd": r[1], "supportMicrousd": r[2], "paymentFeesMicrousd": r[3]} for r in allocated],
            "costLimitations": "Estimates are not invoices. Null operating costs are unknown, not zero; supportReports is workload, not money. Operator-entered allocations must be reconciled to actual invoices/time records."}


if __name__ == "__main__":
    print(json.dumps(growth_metrics(os.environ["DATABASE_URL"])))
