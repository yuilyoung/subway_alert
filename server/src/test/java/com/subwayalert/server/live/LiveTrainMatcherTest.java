package com.subwayalert.server.live;

import static org.junit.jupiter.api.Assertions.*;
import java.time.Instant;
import org.junit.jupiter.api.Test;

class LiveTrainMatcherTest {
  private static final Instant START = Instant.parse("2026-10-27T12:00:00Z");
  private static final Instant NOW = START.plusSeconds(30);
  private static SeoulTrainProvider.Train train(String line, String station, String number,
      String direction, String state, Instant observed, boolean express, boolean fresh) {
    return new SeoulTrainProvider.Train(line, station, number, direction, state, observed, express, fresh);
  }
  private static SeoulTrainProvider.Train correct() {
    return train("2", "선릉", "0202", "INNER", "DEPARTED", NOW, false, true);
  }
  private static LiveTrainMatcher matcher(String mode) {
    return new LiveTrainMatcher("2", "0202", "INNER", "선릉", START, mode, true, true);
  }

  @Test void matchesAConfirmedLiveTrainDepartureOnlyOnce() {
    var matcher = matcher("LIVE");
    assertEquals(LiveTrainMatcher.Decision.LIVE_MATCH, matcher.consider("LIVE", correct(), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", correct(), NOW));
  }

  @Test void sampleMatchIsExplicitlyDifferentFromLiveAndModesDoNotCross() {
    var matcher = matcher("SAMPLE");
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", correct(), NOW));
    assertEquals(LiveTrainMatcher.Decision.SAMPLE_MATCH, matcher.consider("SAMPLE", correct(), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("SAMPLE", correct(), NOW));
  }

  @Test void matchesExactLeadingZeroIdentityLineDirectionStationAndState() {
    var matcher = matcher("LIVE");
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("2","선릉","202","INNER","DEPARTED",NOW,false,true), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("1","선릉","0202","INNER","DEPARTED",NOW,false,true), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("2","선릉","0202","OUTER","DEPARTED",NOW,false,true), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("2","삼성","0202","INNER","DEPARTED",NOW,false,true), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("2","선릉","0202","INNER","ARRIVED",NOW,false,true), NOW));
    assertEquals(LiveTrainMatcher.Decision.LIVE_MATCH, matcher.consider("LIVE", correct(), NOW));
  }

  @Test void rejectsUnreliableStaleFuturePreSessionAndExpressObservations() {
    var matcher = matcher("LIVE");
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("2","선릉","0202","INNER","DEPARTED",START.minusSeconds(1),false,true), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("2","선릉","0202","INNER","DEPARTED",NOW.minusSeconds(61),false,true), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("2","선릉","0202","INNER","DEPARTED",NOW.plusSeconds(6),false,true), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("2","선릉","0202","INNER","DEPARTED",NOW,false,false), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("2","선릉","0202","INNER","DEPARTED",NOW,true,true), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", train("2","선릉","0202","INNER","DEPARTED",null,false,true), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", null, NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", correct(), null));
    assertEquals(LiveTrainMatcher.Decision.LIVE_MATCH, matcher.consider("LIVE", correct(), NOW));
  }

  @Test void rejectsStaleEventsEvenWhenTheyOccurAfterSessionStart() {
    var matcher = new LiveTrainMatcher("2", "0202", "INNER", "선릉", NOW.minusSeconds(300), "LIVE", true, true);
    var stale = train("2", "선릉", "0202", "INNER", "DEPARTED", NOW.minusSeconds(61), false, true);
    assertEquals(LiveTrainMatcher.Decision.IGNORE, matcher.consider("LIVE", stale, NOW));
    assertEquals(LiveTrainMatcher.Decision.LIVE_MATCH, matcher.consider("LIVE", correct(), NOW));
  }

  @Test void unverifiedRouteOrSourceTimeNeverMatchesInLiveMode() {
    var routeUnknown = new LiveTrainMatcher("2", "0202", "INNER", "선릉", START, "LIVE", false, true);
    var timezoneUnknown = new LiveTrainMatcher("2", "0202", "INNER", "선릉", START, "LIVE", true, false);
    assertEquals(LiveTrainMatcher.Decision.IGNORE, routeUnknown.consider("LIVE", correct(), NOW));
    assertEquals(LiveTrainMatcher.Decision.IGNORE, timezoneUnknown.consider("LIVE", correct(), NOW));
  }

  @Test void twoConcurrentCallsProduceOnlyOneMatch() throws Exception {
    var matcher = matcher("LIVE");
    var executor = java.util.concurrent.Executors.newFixedThreadPool(2);
    try {
      var ready = new java.util.concurrent.CountDownLatch(1);
      java.util.concurrent.Callable<LiveTrainMatcher.Decision> call = () -> {
        ready.await();
        return matcher.consider("LIVE", correct(), NOW);
      };
      var first = executor.submit(call);
      var second = executor.submit(call);
      ready.countDown();
      var decisions = java.util.List.of(first.get(), second.get());
      assertEquals(1, decisions.stream().filter(d -> d == LiveTrainMatcher.Decision.LIVE_MATCH).count());
      assertEquals(1, decisions.stream().filter(d -> d == LiveTrainMatcher.Decision.IGNORE).count());
    } finally {
      executor.shutdownNow();
    }
  }

  @Test void rejectsAmbiguousSessionConfiguration() {
    assertThrows(IllegalArgumentException.class, () -> new LiveTrainMatcher("2", " ", "INNER", "선릉", START, "LIVE", true, true));
    assertThrows(IllegalArgumentException.class, () -> new LiveTrainMatcher("2", "0202", "UP", "선릉", START, "LIVE", true, true));
    assertThrows(IllegalArgumentException.class, () -> new LiveTrainMatcher("2", "0202", "INNER", "", START, "LIVE", true, true));
    assertThrows(IllegalArgumentException.class, () -> new LiveTrainMatcher("2", "0202", "INNER", "선릉", null, "LIVE", true, true));
    assertThrows(IllegalArgumentException.class, () -> new LiveTrainMatcher("2", "0202", "INNER", "선릉", START, "UNKNOWN", true, true));
  }
}
