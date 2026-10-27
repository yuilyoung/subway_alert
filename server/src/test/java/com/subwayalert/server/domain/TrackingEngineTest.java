package com.subwayalert.server.domain;

import java.time.Instant;

public final class TrackingEngineTest {
  private static int checks;
  private static void check(boolean condition, String message) {
    checks++;
    if (!condition) throw new AssertionError(message);
  }
  public static void main(String[] args) {
    Instant now = Instant.parse("2026-10-27T00:00:00Z");
    TrackingEngine e = new TrackingEngine(java.time.Clock.fixed(now, java.time.ZoneOffset.UTC));
    var s = e.start("2", "UP", "강남", "삼성", "1234");
    check(s.previousStation().equals("선릉"), "previous station is direction aware");
    check(!e.accept(s.id(), new TrackingEngine.Position("2", "UP", "other", "선릉", "DEPARTED", now), now), "other train must not alert");
    check(!e.accept(s.id(), new TrackingEngine.Position("2", "DOWN", "1234", "선릉", "DEPARTED", now), now), "wrong direction must not alert");
    check(!e.accept(s.id(), new TrackingEngine.Position("2", "UP", "1234", "선릉", "DEPARTED", now.minusSeconds(61)), now), "stale event must not alert");
    check(!e.accept(s.id(), new TrackingEngine.Position("2", "UP", "1234", "선릉", "DEPARTED", now.minusSeconds(1)), now), "events before tracking started must not alert");
    check(!e.accept(s.id(), new TrackingEngine.Position("2", "UP", "1234", "선릉", "ARRIVED", now), now), "arrival is not departure");
    check(!e.accept(s.id(), new TrackingEngine.Position("2", "UP", "1234", "선릉", "DEPARTED", now.plusSeconds(6)), now), "future event must not alert");
    check(e.accept(s.id(), new TrackingEngine.Position("2", "UP", "1234", "선릉", "DEPARTED", now), now), "matched fresh departure alerts");
    check(!e.accept(s.id(), new TrackingEngine.Position("2", "UP", "1234", "선릉", "DEPARTED", now), now), "duplicate ignored");
    var reverse = e.start("2", "DOWN", "삼성", "강남", "2345");
    check(reverse.previousStation().equals("역삼"), "reverse route computes previous");
    e.cancel(reverse.id());
    check(!e.accept(reverse.id(), new TrackingEngine.Position("2", "DOWN", "2345", "역삼", "DEPARTED", now), now), "cancelled session ignored");
    boolean rejected = false;
    try { e.start("2", "DOWN", "강남", "삼성", "1234"); } catch (IllegalArgumentException expected) { rejected = true; }
    check(rejected, "invalid direction rejected");
    rejected = false;
    try { e.start("2", "UP", "강남", "삼성", " "); } catch (IllegalArgumentException expected) { rejected = true; }
    check(rejected, "train identity required");
    rejected = false;
    try { e.start("2", "UP", null, "삼성", "1234"); } catch (IllegalArgumentException expected) { rejected = true; }
    check(rejected, "missing station rejected as invalid input");
    System.out.println("TrackingEngineTest: " + checks + " checks passed");
  }
}
