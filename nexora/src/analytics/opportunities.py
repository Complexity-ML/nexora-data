"""Usage signals for SAM review, never a count of recoverable licences."""

from collections import defaultdict
from datetime import timedelta

from .usage import as_date


def opportunities(dataset):
    end = dataset.end
    start = end - timedelta(days=27)
    previous_start = start - timedelta(days=28)
    days_by_installation = defaultdict(set)
    for row in dataset.tables["usage_observations"]:
        days_by_installation[row["installation_id"]].add(as_date(row["observed_on"]))
    grouped = defaultdict(list)
    for installation in dataset.installations.values():
        machine = dataset.machines[installation["machine_id"]]
        grouped[(installation["software_id"], machine["organization_id"])].append(installation)
    rows, excluded = [], 0
    software = {s["id"]: s["name"] for s in dataset.software}
    organizations = {o["id"]: o["name"] for o in dataset.organizations}
    for (sid, oid), installs in sorted(grouped.items()):
        eligible = [i for i in installs if i["installed_on"] <= start]
        complete = sum(
            dataset.coverage.get((oid, start + timedelta(days=d))) == "complete" for d in range(28)
        )
        if start < dataset.start or complete != 28:
            excluded += len(eligible)
            continue
        common = {
            "software_id": sid,
            "organization_id": oid,
            "software": software[sid],
            "organization": organizations[oid],
            "start": start,
            "end": end,
            "coverage": "28 / 28 jours",
        }
        zero, low = [], []
        for installation in eligible:
            count = sum(start <= day <= end for day in days_by_installation[installation["id"]])
            if count == 0:
                zero.append(installation)
            elif count <= 2:
                low.append(installation)
        for kind, members, evidence in [
            ("Sans usage observé", zero, "Aucun jour d’usage sur les 28 derniers jours."),
            (
                "Usage occasionnel",
                low,
                "Usage observé sur 1 ou 2 jours parmi les 28 derniers jours.",
            ),
        ]:
            if members:
                rows.append(
                    {
                        **common,
                        "kind": kind,
                        "count": len(members),
                        "evidence": evidence,
                        "installations": members,
                    }
                )
        # Compare equal four-week periods on an unchanged cohort, deduplicating users.
        cohort = [i for i in installs if i["installed_on"] <= previous_start]
        if (
            previous_start < dataset.start
            or not cohort
            or any(
                dataset.coverage.get((oid, previous_start + timedelta(days=d))) != "complete"
                for d in range(56)
            )
        ):
            continue
        totals = []
        for first in (previous_start, start):
            totals.append(
                sum(
                    len(
                        {
                            dataset.machines[i["machine_id"]]["user_id"]
                            for i in cohort
                            if first + timedelta(days=d) in days_by_installation[i["id"]]
                        }
                    )
                    for d in range(28)
                )
            )
        before, after = totals
        if before > 0 and after <= before * 0.7:
            rows.append(
                {
                    **common,
                    "start": previous_start,
                    "coverage": "56 / 56 jours",
                    "kind": "Usage en baisse",
                    "count": None,
                    "installations": [],
                    "evidence": f"Utilisateurs actifs/jour : {before / 28:.1f} puis {after / 28:.1f} ({(after / before - 1) * 100:.0f} %), à population installée constante.",
                }
            )
    order = {"Sans usage observé": 0, "Usage occasionnel": 1, "Usage en baisse": 2}
    rows.sort(
        key=lambda row: (
            order[row["kind"]],
            -(row["count"] or 0),
            row["software"],
            row["organization"],
        )
    )
    return {"rows": rows, "start": start, "end": end, "excluded": excluded}
