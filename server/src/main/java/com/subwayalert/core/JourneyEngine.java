package com.subwayalert.core;

import java.time.Duration;
import java.time.Instant;
import java.util.*;

/** Pure tracking rules. Never estimate station movement from elapsed wall-clock time. */
public final class JourneyEngine {
    private JourneyEngine() {}
    public record Observation(String trainNo, String lineId, String direction, String stationId,
                              String state, Instant observedAt, boolean express, String terminalId) {}
    public record Journey(String trainNo, String lineId, String direction, List<String> stops,
                          int lastIndex, Instant lastSeen, boolean alerted, Instant expiresAt) {
        public Journey {
            stops = List.copyOf(stops);
            if (stops.size() < 2 || new HashSet<>(stops).size() != stops.size()
                || stops.stream().anyMatch(s -> s == null || s.isBlank())
                || lastIndex < 0 || lastIndex >= stops.size() || expiresAt == null)
                throw new IllegalArgumentException("Invalid journey");
        }
    }
    public record Decision(String action, int index, Instant observedAt, String reason) {}
    public record Edge(String from, String to, String lineId, String direction) {}

    public static boolean fresh(Instant observed, Instant now) {
        if (observed == null) return false;
        long age = Duration.between(observed, now).toMillis();
        return age >= -10_000 && age <= 90_000;
    }

    public static Decision evaluate(Journey j, Observation o, Instant now) {
        if (j.alerted()) return ignored(j, "ALREADY_ALERTED");
        if (!now.isBefore(j.expiresAt())) return new Decision("EXPIRED", j.lastIndex(), j.lastSeen(), "SESSION_EXPIRED");
        if (!Objects.equals(j.trainNo(), o.trainNo()) || !Objects.equals(j.lineId(), o.lineId())
            || !Objects.equals(j.direction(), o.direction())) return ignored(j, "OTHER_TRAIN");
        if (o.express()) return ignored(j, "UNSUPPORTED_EXPRESS");
        if (!fresh(o.observedAt(), now)) return ignored(j, "STALE_OR_FUTURE");
        if (j.lastSeen() != null && !o.observedAt().isAfter(j.lastSeen())) return ignored(j, "OUT_OF_ORDER");
        if (!Set.of("ENTERING", "ARRIVED", "DEPARTED").contains(o.state())) return ignored(j, "UNKNOWN_STATE");
        int index = j.stops().indexOf(o.stationId());
        if (index < j.lastIndex()) return ignored(j, index < 0 ? "OFF_ROUTE" : "BACKWARDS");
        if (index == j.stops().size() - 2 && "DEPARTED".equals(o.state()))
            return new Decision("ALERT", index, o.observedAt(), "PREVIOUS_STATION_DEPARTURE");
        if (index == j.stops().size() - 1)
            return new Decision("LATE", index, o.observedAt(), "DESTINATION_ALREADY_REACHED");
        return new Decision("PROGRESS", index, o.observedAt(), "OBSERVED");
    }

    private static Decision ignored(Journey j, String reason) {
        return new Decision("IGNORE", j.lastIndex(), j.lastSeen(), reason);
    }

    /** Directed connections handle circular lines and branches without numeric station-ID arithmetic. */
    public static List<String> path(List<Edge> edges, String line, String direction, String from, String to) {
        if (from == null || to == null || from.equals(to) || !Set.of("0", "1").contains(direction))
            throw new IllegalArgumentException("출발역, 도착역과 방향을 확인하세요.");
        Map<String, List<String>> graph = new HashMap<>();
        for (Edge edge : edges) {
            if (line.equals(edge.lineId()) && direction.equals(edge.direction()))
                graph.computeIfAbsent(edge.from(), unused -> new ArrayList<>()).add(edge.to());
        }
        Deque<String> queue = new ArrayDeque<>();
        Map<String, String> parent = new HashMap<>();
        queue.add(from);
        parent.put(from, null);
        while (!queue.isEmpty()) {
            String here = queue.removeFirst();
            for (String next : graph.getOrDefault(here, List.of())) {
                if (parent.containsKey(next)) continue;
                parent.put(next, here);
                if (next.equals(to)) {
                    LinkedList<String> result = new LinkedList<>();
                    for (String at = to; at != null; at = parent.get(at)) result.addFirst(at);
                    return List.copyOf(result);
                }
                queue.addLast(next);
            }
        }
        throw new IllegalArgumentException("해당 방향의 검증된 동일 호선 경로가 없습니다.");
    }
}
