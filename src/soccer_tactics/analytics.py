"""Deterministic, versioned tactical metrics with possession-level evidence."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable
from statistics import fmean

import networkx as nx

from soccer_tactics.models import (
    ANALYTICS_VERSION,
    AnalysisConfiguration,
    Event,
    EvidenceReference,
    MetricKind,
    MetricResult,
    PlayerPosition,
    Point,
    Possession,
    TeamSide,
    TrackingFrame,
)


def distance(first: Point, second: Point) -> float:
    return math.hypot(first.x - second.x, first.y - second.y)


def convex_hull(points: list[Point]) -> list[Point]:
    unique = sorted({(point.x, point.y) for point in points})
    if len(unique) <= 1:
        return [Point(x=x, y=y) for x, y in unique]

    def cross(origin: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return [Point(x=x, y=y) for x, y in lower[:-1] + upper[:-1]]


def polygon_area(points: list[Point]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(sum(a.x * b.y - b.x * a.y for a, b in zip(points, points[1:] + points[:1], strict=True))) / 2


def epv(point: Point | None, attacking_right: bool = True) -> float:
    """Transparent field-value surface: central, advanced locations carry more value."""
    if point is None:
        return 0.0
    progress = point.x / 105 if attacking_right else 1 - point.x / 105
    centrality = math.exp(-(((point.y - 34) / 22) ** 2))
    goal_proximity = 1 / (1 + math.exp(-10 * (progress - 0.72)))
    return float(0.35 * progress + 0.25 * progress**2 + 0.4 * goal_proximity * centrality)


def _team_players(frame: TrackingFrame, team: TeamSide, exclude_goalkeeper: bool = False) -> list[PlayerPosition]:
    players = [player for player in frame.players if player.team == team]
    if not exclude_goalkeeper or len(players) < 2:
        return players
    marked = [player for player in players if player.is_goalkeeper]
    if marked:
        return [player for player in players if not player.is_goalkeeper]
    # Metrica is anonymized; use the deepest player as a deterministic fallback.
    deepest = min(players, key=lambda player: min(player.position.x, 105 - player.position.x))
    return [player for player in players if player.player_id != deepest.player_id]


def _frames_for(possession: Possession, frames: list[TrackingFrame]) -> list[TrackingFrame]:
    return [
        frame
        for frame in frames
        if frame.period == possession.period and possession.start_time <= frame.timestamp <= possession.end_time + 0.2
    ]


def _event_map(events: list[Event]) -> dict[str, Event]:
    return {event.event_id: event for event in events}


def _evidence(
    metric: MetricKind,
    possession: Possession,
    team: TeamSide,
    score: float,
    supporting: bool = True,
) -> EvidenceReference:
    return EvidenceReference(
        match_id=possession.match_id,
        team=team,
        metric=metric,
        metric_version=ANALYTICS_VERSION,
        possession_id=possession.possession_id,
        period=possession.period,
        start_frame=possession.start_frame,
        end_frame=possession.end_frame,
        event_ids=possession.event_ids,
        score=round(float(score), 5),
        supporting=supporting,
    )


def _ranked_references(
    metric: MetricKind,
    possession_scores: list[tuple[Possession, float]],
    team: TeamSide,
    limit: int = 5,
) -> list[EvidenceReference]:
    if not possession_scores:
        return []
    ordered = sorted(possession_scores, key=lambda item: (item[1], item[0].possession_id), reverse=True)
    supporting = [_evidence(metric, possession, team, score, True) for possession, score in ordered[:limit]]
    contradicting = [_evidence(metric, possession, team, score, False) for possession, score in reversed(ordered[-min(2, len(ordered)) :])]
    return supporting + contradicting


def passing_network(
    team: TeamSide,
    events: list[Event],
    possessions: list[Possession],
    _frames: list[TrackingFrame],
    _configuration: AnalysisConfiguration,
) -> MetricResult:
    event_by_id = _event_map(events)
    graph = nx.DiGraph()
    possession_scores: list[tuple[Possession, float]] = []
    completed = 0
    progressive = 0
    for possession in possessions:
        if possession.team != team:
            continue
        possession_passes = []
        for event_id in possession.event_ids:
            event = event_by_id.get(event_id)
            if event is None or event.event_type != "PASS" or (event.outcome or "").lower() == "incomplete":
                continue
            sender = event.player_id or "unknown"
            receiver = (event.subtype or "").split("-")[0].strip() or "unknown"
            weight = graph.get_edge_data(sender, receiver, {}).get("weight", 0) + 1
            graph.add_edge(sender, receiver, weight=weight)
            completed += 1
            gain = (event.end.x - event.start.x) if event.start and event.end else 0.0
            progressive += int(gain >= 10)
            possession_passes.append(max(0.0, gain))
        if possession_passes:
            possession_scores.append((possession, sum(possession_passes) + 2 * len(possession_passes)))

    weighted_degree = {node: float(graph.in_degree(node, weight="weight") + graph.out_degree(node, weight="weight")) for node in graph}
    centrality = nx.betweenness_centrality(graph, weight="weight", normalized=True) if len(graph) > 1 else {}
    combinations = sorted(
        ((source, target, int(data["weight"])) for source, target, data in graph.edges(data=True)),
        key=lambda item: item[2],
        reverse=True,
    )[:8]
    references = _ranked_references(MetricKind.PASSING_NETWORK, possession_scores, team)
    return MetricResult(
        metric=MetricKind.PASSING_NETWORK,
        team=team,
        summary={
            "completed_passes": completed,
            "progressive_passes": progressive,
            "network_density": round(float(nx.density(graph)) if len(graph) > 1 else 0.0, 4),
            "most_connected": sorted(weighted_degree.items(), key=lambda item: item[1], reverse=True)[:5],
            "highest_betweenness": sorted(centrality.items(), key=lambda item: item[1], reverse=True)[:5],
            "top_combinations": combinations,
        },
        evidence=references,
        caveats=["Receiver identity is inferred from Metrica event labels when explicit receiver fields are unavailable."],
    )


def defensive_compactness(
    team: TeamSide,
    _events: list[Event],
    possessions: list[Possession],
    frames: list[TrackingFrame],
    _configuration: AnalysisConfiguration,
) -> MetricResult:
    records: list[dict[str, float]] = []
    possession_scores: list[tuple[Possession, float]] = []
    for possession in possessions:
        if possession.team == team:
            continue
        local = []
        for frame in _frames_for(possession, frames):
            points = [player.position for player in _team_players(frame, team, exclude_goalkeeper=True)]
            if len(points) < 3:
                continue
            length = max(point.x for point in points) - min(point.x for point in points)
            width = max(point.y for point in points) - min(point.y for point in points)
            area = polygon_area(convex_hull(points))
            center_x = fmean(point.x for point in points)
            center_y = fmean(point.y for point in points)
            records.append({"length": length, "width": width, "area": area, "center_x": center_x, "center_y": center_y})
            local.append(area)
        if local:
            # Low area is stronger compactness, represented as an intuitive 0..1 score.
            score = 1 / (1 + fmean(local) / 500)
            possession_scores.append((possession, score))
    summary = {
        "mean_length_m": round(fmean(record["length"] for record in records), 2) if records else 0.0,
        "mean_width_m": round(fmean(record["width"] for record in records), 2) if records else 0.0,
        "mean_hull_area_m2": round(fmean(record["area"] for record in records), 2) if records else 0.0,
        "mean_centroid": {
            "x": round(fmean(record["center_x"] for record in records), 2) if records else 0.0,
            "y": round(fmean(record["center_y"] for record in records), 2) if records else 0.0,
        },
        "sampled_frames": len(records),
    }
    return MetricResult(
        metric=MetricKind.COMPACTNESS,
        team=team,
        summary=summary,
        evidence=_ranked_references(MetricKind.COMPACTNESS, possession_scores, team),
        caveats=["The goalkeeper is excluded; when role metadata is absent, the deepest player is treated as goalkeeper."],
    )


def _closing_speed(defender: PlayerPosition, target: Point) -> float:
    delta_x = target.x - defender.position.x
    delta_y = target.y - defender.position.y
    magnitude = math.hypot(delta_x, delta_y)
    if magnitude == 0:
        return math.hypot(defender.velocity_x, defender.velocity_y)
    return (defender.velocity_x * delta_x + defender.velocity_y * delta_y) / magnitude


def pressing_patterns(
    team: TeamSide,
    _events: list[Event],
    possessions: list[Possession],
    frames: list[TrackingFrame],
    configuration: AnalysisConfiguration,
) -> MetricResult:
    possession_scores: list[tuple[Possession, float]] = []
    total_pressure_frames = coordinated_frames = successful = 0
    ordered = sorted(possessions, key=lambda possession: (possession.period, possession.start_time))
    for index, possession in enumerate(ordered):
        if possession.team == team:
            continue
        local_pressure = 0
        local_coordinated = 0
        for frame in _frames_for(possession, frames):
            if frame.ball is None:
                continue
            pressers = [
                player
                for player in _team_players(frame, team)
                if distance(player.position, frame.ball) <= configuration.pressure_radius_m
                and _closing_speed(player, frame.ball) >= configuration.pressure_closing_speed_mps
            ]
            if pressers:
                local_pressure += 1
            if len(pressers) >= configuration.coordinated_pressure_players:
                local_coordinated += 1
        regained = False
        if index + 1 < len(ordered):
            following = ordered[index + 1]
            regained = (
                following.team == team
                and following.period == possession.period
                and following.start_time - possession.end_time <= configuration.regain_window_seconds
            )
        successful += int(regained and local_pressure > 0)
        total_pressure_frames += local_pressure
        coordinated_frames += local_coordinated
        if local_pressure:
            score = local_pressure + 2 * local_coordinated + (10 if regained else 0)
            possession_scores.append((possession, score))
    return MetricResult(
        metric=MetricKind.PRESSING,
        team=team,
        summary={
            "pressure_frames": total_pressure_frames,
            "coordinated_pressure_frames": coordinated_frames,
            "pressures_leading_to_regain": successful,
            "pressure_radius_m": configuration.pressure_radius_m,
            "closing_speed_threshold_mps": configuration.pressure_closing_speed_mps,
            "regain_window_seconds": configuration.regain_window_seconds,
        },
        evidence=_ranked_references(MetricKind.PRESSING, possession_scores, team),
        caveats=["Pressure is an inferred proximity-and-velocity proxy, not a provider-tagged pressure event."],
    )


def time_to_intercept(player: PlayerPosition, target: Point, configuration: AnalysisConfiguration) -> float:
    reaction = Point(
        x=min(105.0, max(0.0, player.position.x + player.velocity_x * configuration.reaction_time_seconds)),
        y=min(68.0, max(0.0, player.position.y + player.velocity_y * configuration.reaction_time_seconds)),
    )
    return configuration.reaction_time_seconds + distance(reaction, target) / configuration.max_player_speed_mps


def pitch_control_probability(
    frame: TrackingFrame,
    target: Point,
    team: TeamSide,
    configuration: AnalysisConfiguration,
) -> float:
    attackers = _team_players(frame, team)
    defenders = _team_players(frame, TeamSide.AWAY if team == TeamSide.HOME else TeamSide.HOME)
    if not attackers or not defenders:
        return 0.5
    attacking_time = min(time_to_intercept(player, target, configuration) for player in attackers)
    defending_time = min(time_to_intercept(player, target, configuration) for player in defenders)
    # Logistic approximation of the competing-arrival model used for pitch control.
    return float(1 / (1 + math.exp(4.3 * (attacking_time - defending_time))))


def pitch_control(
    team: TeamSide,
    events: list[Event],
    possessions: list[Possession],
    frames: list[TrackingFrame],
    configuration: AnalysisConfiguration,
) -> MetricResult:
    event_by_id = _event_map(events)
    frame_list = sorted(frames, key=lambda frame: (frame.period, frame.timestamp))
    possession_scores: list[tuple[Possession, float]] = []
    pass_probabilities: list[float] = []
    for possession in possessions:
        if possession.team != team:
            continue
        local = []
        for event_id in possession.event_ids:
            event = event_by_id.get(event_id)
            if event is None or event.event_type != "PASS" or event.end is None:
                continue
            candidates = [frame for frame in frame_list if frame.period == event.period]
            if not candidates:
                continue
            frame = min(candidates, key=lambda candidate: abs(candidate.timestamp - event.timestamp))
            probability = pitch_control_probability(frame, event.end, team, configuration)
            local.append(probability)
            pass_probabilities.append(probability)
        if local:
            possession_scores.append((possession, fmean(local)))
    return MetricResult(
        metric=MetricKind.PITCH_CONTROL,
        team=team,
        summary={
            "evaluated_passes": len(pass_probabilities),
            "mean_target_control": round(fmean(pass_probabilities), 4) if pass_probabilities else 0.0,
            "risky_completed_passes": sum(probability < 0.5 for probability in pass_probabilities),
            "reaction_time_seconds": configuration.reaction_time_seconds,
            "max_player_speed_mps": configuration.max_player_speed_mps,
        },
        evidence=_ranked_references(MetricKind.PITCH_CONTROL, possession_scores, team),
        caveats=["Pitch control is a probabilistic arrival model and is sensitive to reaction-time and speed assumptions."],
    )


def space_creation(
    team: TeamSide,
    _events: list[Event],
    possessions: list[Possession],
    frames: list[TrackingFrame],
    configuration: AnalysisConfiguration,
) -> MetricResult:
    contributions: Counter[str] = Counter()
    possession_scores: list[tuple[Possession, float]] = []
    for possession in possessions:
        if possession.team != team:
            continue
        local_frames = _frames_for(possession, frames)
        if len(local_frames) < 2:
            continue
        score = 0.0
        for previous, current in zip(local_frames, local_frames[1:], strict=False):
            current_by_id = {player.player_id: player for player in _team_players(current, team)}
            for old in _team_players(previous, team):
                new = current_by_id.get(old.player_id)
                if new is None:
                    continue
                movement = distance(old.position, new.position)
                if movement < 0.2:
                    continue
                before = epv(old.position)
                after = epv(new.position)
                control = pitch_control_probability(current, new.position, team, configuration)
                contribution = movement * max(0.0, after - before + 0.03) * control
                contributions[old.player_id] += contribution
                score += contribution
        if score:
            possession_scores.append((possession, score))
    return MetricResult(
        metric=MetricKind.SPACE_CREATION,
        team=team,
        summary={
            "top_space_creators": [(player, round(value, 4)) for player, value in contributions.most_common(8)],
            "total_control_value_created": round(sum(contributions.values()), 4),
            "evaluated_possessions": len(possession_scores),
        },
        evidence=_ranked_references(MetricKind.SPACE_CREATION, possession_scores, team),
        caveats=["Space creation is a control-weighted player-influence delta, not causal credit for the subsequent action."],
    )


def transition_opportunities(
    team: TeamSide,
    _events: list[Event],
    possessions: list[Possession],
    frames: list[TrackingFrame],
    configuration: AnalysisConfiguration,
) -> MetricResult:
    possession_scores: list[tuple[Possession, float]] = []
    components: list[dict[str, float]] = []
    ordered = sorted(possessions, key=lambda possession: (possession.period, possession.start_time))
    for index, possession in enumerate(ordered):
        if possession.team != team or index == 0 or ordered[index - 1].team == team:
            continue
        local = [
            frame
            for frame in frames
            if frame.period == possession.period
            and possession.start_time <= frame.timestamp <= possession.start_time + configuration.transition_window_seconds
            and frame.ball is not None
        ]
        if len(local) < 2:
            continue
        start, end = local[0], local[-1]
        progression = max(0.0, (end.ball.x - start.ball.x) if end.ball and start.ball else 0.0)
        duration = max(0.2, end.timestamp - start.timestamp)
        speed = progression / duration
        control_start = pitch_control_probability(start, start.ball, team, configuration) if start.ball else 0.5
        control_end = pitch_control_probability(end, end.ball, team, configuration) if end.ball else 0.5
        value_gain = epv(end.ball) - epv(start.ball)
        score = max(0.0, 0.08 * progression + 0.5 * speed + 2 * (control_end - control_start) + 4 * value_gain)
        components.append(
            {
                "progression_m": progression,
                "speed_mps": speed,
                "control_change": control_end - control_start,
                "epv_gain": value_gain,
            }
        )
        possession_scores.append((possession, score))
    return MetricResult(
        metric=MetricKind.TRANSITIONS,
        team=team,
        summary={
            "transition_count": len(components),
            "mean_progression_m": round(fmean(item["progression_m"] for item in components), 3) if components else 0.0,
            "mean_speed_mps": round(fmean(item["speed_mps"] for item in components), 3) if components else 0.0,
            "mean_control_change": round(fmean(item["control_change"] for item in components), 4) if components else 0.0,
            "mean_epv_gain": round(fmean(item["epv_gain"] for item in components), 4) if components else 0.0,
            "window_seconds": configuration.transition_window_seconds,
        },
        evidence=_ranked_references(MetricKind.TRANSITIONS, possession_scores, team),
        caveats=["Transition value uses a transparent control-weighted EPV surface rather than a trained outcome model."],
    )


ANALYTICS: dict[MetricKind, Callable[..., MetricResult]] = {
    MetricKind.PASSING_NETWORK: passing_network,
    MetricKind.COMPACTNESS: defensive_compactness,
    MetricKind.PRESSING: pressing_patterns,
    MetricKind.PITCH_CONTROL: pitch_control,
    MetricKind.SPACE_CREATION: space_creation,
    MetricKind.TRANSITIONS: transition_opportunities,
}


def analyze_match(
    team: TeamSide,
    events: list[Event],
    possessions: list[Possession],
    frames: list[TrackingFrame],
    configuration: AnalysisConfiguration | None = None,
) -> list[MetricResult]:
    config = configuration or AnalysisConfiguration()
    return [function(team, events, possessions, frames, config) for function in ANALYTICS.values()]


def validate_evidence(results: Iterable[MetricResult], possessions: Iterable[Possession]) -> None:
    known = {possession.possession_id: possession for possession in possessions}
    for result in results:
        for evidence in result.evidence:
            possession = known.get(evidence.possession_id)
            if possession is None:
                raise ValueError(f"unknown possession in evidence: {evidence.possession_id}")
            if possession.match_id != evidence.match_id:
                raise ValueError(f"evidence match mismatch: {evidence.evidence_id}")
