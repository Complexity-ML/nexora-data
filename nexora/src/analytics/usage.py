"""Aggregate one coherent snapshot, keeping missing coverage distinct from zero use."""

from collections import defaultdict
from datetime import date, timedelta

from ..forecasting.statistical import backtest, predict


def as_date(value):
    return value if isinstance(value, date) else date.fromisoformat(value)


class UsageDataset:
    def __init__(self, tables, manifest):
        self.tables, self.manifest = tables, manifest
        self.software = sorted(tables["software"], key=lambda row: row["name"])
        self.organizations = tables["organizations"]
        self.machines = {m["id"]: m for m in tables["machines"]}
        self.installations = {
            i["id"]: {**i, "installed_on": as_date(i["installed_on"])}
            for i in tables["installations"]
        }
        self.coverage = {
            (c["organization_id"], as_date(c["observed_on"])): c["status"]
            for c in tables["collection_coverage"]
        }
        self.start = min(day for _, day in self.coverage)
        self.end = max(day for _, day in self.coverage)
        self.activity = defaultdict(set)
        for row in tables["usage_observations"]:
            installation = self.installations[row["installation_id"]]
            machine = self.machines[installation["machine_id"]]
            day = as_date(row["observed_on"])
            if day < installation["installed_on"] or row["active_minutes"] <= 0:
                raise ValueError("Observation incohérente")
            if self.coverage.get((machine["organization_id"], day)) != "complete":
                raise ValueError("Observation sans couverture complète")
            self.activity[(installation["software_id"], machine["organization_id"], day)].add(
                machine["user_id"]
            )

    def series(self, software_id, organization_id, start, end):
        orgs = {organization_id} if organization_id else {o["id"] for o in self.organizations}
        if software_id not in {s["id"] for s in self.software} or not orgs.issubset(
            {o["id"] for o in self.organizations}
        ):
            raise ValueError("Périmètre inconnu")
        start, end = as_date(start), as_date(end)
        if not self.start <= start <= end <= self.end:
            raise ValueError("Période hors des observations disponibles")
        result = []
        for offset in range((end - start).days + 1):
            day = start + timedelta(days=offset)
            complete = all(self.coverage.get((org, day)) == "complete" for org in orgs)
            active = set().union(
                *(self.activity.get((software_id, org, day), set()) for org in orgs)
            )
            result.append({"date": day, "active_users": len(active) if complete else None})
        return result

    def analyze(self, software_id, organization_id, start, end):
        history = self.series(software_id, organization_id, start, end)
        end = as_date(end)
        installs = [
            i
            for i in self.installations.values()
            if i["software_id"] == software_id
            and i["installed_on"] <= end
            and (
                not organization_id
                or self.machines[i["machine_id"]]["organization_id"] == organization_id
            )
        ]
        population = len({self.machines[i["machine_id"]]["user_id"] for i in installs})
        forecast = predict(history, population=population)
        populations = {
            point["date"]: len(
                {
                    self.machines[i["machine_id"]]["user_id"]
                    for i in installs
                    if i["installed_on"] <= point["date"]
                }
            )
            for point in history
        }
        observed = [p["active_users"] for p in history if p["active_users"] is not None]
        return {
            "history": history,
            "forecast": forecast,
            "tree_forecast": predict(history, population=population, tree=True),
            "evaluation": backtest(history, populations),
            "installations": len(installs),
            "population": population,
            "latest": history[-1]["active_users"],
            "peak": max(observed) if observed else None,
            "complete_days": len(observed),
            "missing_days": len(history) - len(observed),
        }
