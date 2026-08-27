"""Deterministic synthetic data for an offline first-run experience."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from importlib.resources import files

from job_radar.db.store import RadarStore
from job_radar.models import OfferFact, RawOffer, ScoreBreakdown, ScoredOffer

_DEMO_RESOURCE = files("job_radar").joinpath("data/demo_offers.json")


def seed_demo(store: RadarStore, now: datetime) -> int:
    """Materialize the bundled fixture with every date relative to ``now``."""

    if now.tzinfo is None:
        raise ValueError("demo clock must include a timezone")
    rows = json.loads(_DEMO_RESOURCE.read_text(encoding="utf-8"))
    if len(rows) != 42:
        raise ValueError("demo fixture must contain exactly 42 offers")

    clock = now.astimezone(UTC)
    for row in rows:
        relevance = row["relevance"]
        role_points = relevance // 2
        skills = row["skills"]
        published_at = clock - timedelta(days=row["published_offset_days"])
        offer = RawOffer(
            external_id=row["id"],
            source=row["source"],
            url=f"https://{row['source']}.example/offers/{row['id']}",
            title=row["title"],
            company=row["company"],
            location=row["location"],
            contract=row["contract"],
            remote=row["remote"],
            description=(
                f"{row['title']} at {row['company']} in {row['location']}. "
                f"Skills: {', '.join(skills)}."
            ),
            published_at=published_at,
        )
        facts = [
            OfferFact(
                name="skill",
                value=skill,
                citation=f"The synthetic offer mentions {skill}.",
                confidence=row["confidence"],
            )
            for skill in skills
        ]
        store.save_scored_offer(
            ScoredOffer(
                offer=offer,
                facts=facts,
                axes=[
                    ScoreBreakdown(name="role", points=role_points, explanation="Synthetic role match."),
                    ScoreBreakdown(
                        name="skills",
                        points=relevance - role_points,
                        explanation="Synthetic skills match.",
                    ),
                ],
                relevance=relevance,
                confidence=row["confidence"],
                freshness_days=row["published_offset_days"],
                decision=row["decision"],
                score_version="demo-v1",
                blocker=row.get("blocker"),
            ),
            processed_at=clock,
        )
    return len(rows)
