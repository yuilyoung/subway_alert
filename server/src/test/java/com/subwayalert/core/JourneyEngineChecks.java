package com.subwayalert.core;

import java.time.Instant;
import java.util.List;
import static com.subwayalert.core.JourneyEngine.*;

/** Dependency-free executable tests, also invoked by JUnit in the Maven build. */
public final class JourneyEngineChecks {
    private static int checks;
    private static final Instant NOW = Instant.parse("2026-10-27T00:00:00Z");
    private static Journey journey(int index, Instant seen, boolean alerted) {
        return new Journey("T1", "1002", "0", List.of("A", "B", "C", "D"), index, seen, alerted, NOW.plusSeconds(7200));
    }
    private static Observation at(String station, String state, Instant time) {
        return new Observation("T1", "1002", "0", station, state, time, false, "D");
    }
    private static void equal(Object expected, Object actual) {
        checks++;
        if (!expected.equals(actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }
    private static void rejects(Runnable action) {
        checks++;
        try { action.run(); } catch (IllegalArgumentException e) { return; }
        throw new AssertionError("Expected invalid input to be rejected");
    }
    public static int run() {
        checks = 0;
        Journey j = journey(0, NOW.minusSeconds(20), false);
        equal("PROGRESS", evaluate(j, at("B", "ARRIVED", NOW), NOW).action());
        equal("ALERT", evaluate(j, at("C", "DEPARTED", NOW), NOW).action());
        equal("PROGRESS", evaluate(j, at("C", "ARRIVED", NOW), NOW).action());
        equal("LATE", evaluate(j, at("D", "ARRIVED", NOW), NOW).action());
        equal("IGNORE", evaluate(j, new Observation("OTHER", "1002", "0", "C", "DEPARTED", NOW, false, "D"), NOW).action());
        equal("IGNORE", evaluate(j, new Observation("T1", "1003", "0", "C", "DEPARTED", NOW, false, "D"), NOW).action());
        equal("IGNORE", evaluate(j, new Observation("T1", "1002", "1", "C", "DEPARTED", NOW, false, "D"), NOW).action());
        equal("IGNORE", evaluate(j, new Observation("T1", "1002", "0", "C", "DEPARTED", NOW, true, "D"), NOW).action());
        equal("IGNORE", evaluate(j, at("C", "DEPARTED", NOW.minusSeconds(91)), NOW).action());
        equal("IGNORE", evaluate(j, at("C", "DEPARTED", NOW.plusSeconds(11)), NOW).action());
        equal("IGNORE", evaluate(j, at("C", "DEPARTED", NOW.minusSeconds(20)), NOW).action());
        equal("IGNORE", evaluate(j, at("C", "DEPARTED", NOW.minusSeconds(21)), NOW).action());
        equal("IGNORE", evaluate(journey(2, NOW.minusSeconds(1), false), at("B", "DEPARTED", NOW), NOW).action());
        equal("IGNORE", evaluate(j, at("OUTSIDE", "DEPARTED", NOW), NOW).action());
        equal("IGNORE", evaluate(journey(2, NOW.minusSeconds(10), true), at("C", "DEPARTED", NOW), NOW).action());
        equal("IGNORE", evaluate(j, at("C", "UNKNOWN", NOW), NOW).action());
        equal("EXPIRED", evaluate(j, at("C", "DEPARTED", NOW.plusSeconds(7200)), NOW.plusSeconds(7200)).action());
        Journey single = new Journey("T1", "1002", "0", List.of("A", "B"), 0, null, false, NOW.plusSeconds(100));
        equal("ALERT", evaluate(single, at("A", "DEPARTED", NOW), NOW).action());
        List<Edge> graph = List.of(new Edge("A","B","1002","0"), new Edge("B","C","1002","0"),
            new Edge("C","A","1002","0"), new Edge("B","X","1002","0"), new Edge("B","A","1002","1"));
        equal(List.of("C","A","B"), path(graph,"1002","0","C","B"));
        equal(List.of("A","B","X"), path(graph,"1002","0","A","X"));
        equal(List.of("B","A"), path(graph,"1002","1","B","A"));
        rejects(() -> path(graph,"1002","1","A","B"));
        rejects(() -> path(graph,"1002","0","A","A"));
        rejects(() -> path(graph,"1003","0","A","B"));
        rejects(() -> new Journey("T1","1002","0", List.of("A","A"),0,null,false,NOW));
        return checks;
    }
    public static void main(String[] args) { System.out.println("JourneyEngine: " + run() + " checks passed"); }
}
