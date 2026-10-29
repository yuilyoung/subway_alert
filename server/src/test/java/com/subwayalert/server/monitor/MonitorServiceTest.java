package com.subwayalert.server.monitor;

import static org.junit.jupiter.api.Assertions.*;

import com.subwayalert.server.live.SeoulTrainProvider;
import com.subwayalert.server.push.NotificationGateway;
import java.time.*;
import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class MonitorServiceTest {
  static final class FakeClock extends Clock {
    Instant current = Instant.parse("2026-10-27T12:00:00Z");

    public ZoneId getZone() {
      return ZoneOffset.UTC;
    }

    public Clock withZone(ZoneId z) {
      return this;
    }

    public Instant instant() {
      return current;
    }

    void advance(long seconds) {
      current = current.plusSeconds(seconds);
    }
  }

  static final class Gateway implements NotificationGateway {
    AtomicInteger calls = new AtomicInteger();
    Result result = Result.ACCEPTED;

    public boolean available() {
      return result != Result.UNAVAILABLE;
    }

    public Result send(String token, String previous, String destination, String mode) {
      assertEquals("TEST", mode);
      calls.incrementAndGet();
      return result;
    }
  }

  private static MonitorService.StartRequest request() {
    return new MonitorService.StartRequest("2", "0202", "INNER", "선릉", "삼성", "token-123", "TEST");
  }

  private static SeoulTrainProvider.Train train(Instant at, String id) {
    return new SeoulTrainProvider.Train("2", "선릉", id, "INNER", "DEPARTED", at, false, true);
  }

  private static SeoulTrainProvider.Result sample(SeoulTrainProvider.Train t) {
    return new SeoulTrainProvider.Result("SAMPLE", List.of(t), "partial");
  }

  @Test
  void testModeOnlyAndAuthenticatedStatusHasNoSecret() {
    FakeClock clock = new FakeClock();
    Gateway g = new Gateway();
    MonitorService s = new MonitorService(g, clock, 600);
    var result = s.start(request());
    assertEquals("TRACKING", result.status());
    assertEquals("TEST", result.mode());
    assertFalse(request().toString().contains("token-123"));
    assertFalse(result.toString().contains(result.sessionToken()));
    var status = s.status(result.id(), result.sessionToken());
    assertEquals("NONE", status.deliveryStatus());
    assertThrows(MonitorService.NotFound.class, () -> s.status(result.id(), "wrong"));
    assertThrows(
        IllegalArgumentException.class,
        () ->
            s.start(
                new MonitorService.StartRequest(
                    "2", "0202", "INNER", "선릉", "삼성", "token", "LIVE")));
    assertThrows(
        IllegalArgumentException.class,
        () ->
            s.start(
                new MonitorService.StartRequest(
                    "2", "0202", "INNER", "선릉", "선릉", "token", "TEST")));
  }

  @Test
  void matchedSampleSendsOneClearlyTestNotificationButDoesNotAssertDeviceDelivery() {
    FakeClock clock = new FakeClock();
    Gateway g = new Gateway();
    MonitorService s = new MonitorService(g, clock, 600);
    var a = s.start(request());
    clock.advance(1);
    s.process(sample(train(clock.instant(), "9999")));
    assertEquals(0, g.calls.get());
    s.process(sample(train(clock.instant(), "0202")));
    s.process(sample(train(clock.instant(), "0202")));
    assertEquals(1, g.calls.get());
    assertEquals("FCM_ACCEPTED", s.status(a.id(), a.sessionToken()).deliveryStatus());
    assertEquals("SAMPLE_MATCHED", s.status(a.id(), a.sessionToken()).status());
    AtomicInteger nextPolls = new AtomicInteger();
    s.poll(
        () -> {
          nextPolls.incrementAndGet();
          return sample(train(clock.instant(), "0202"));
        });
    assertEquals(0, nextPolls.get());
  }

  @Test
  void cancellationAndExpiredDataNeverSend() {
    FakeClock clock = new FakeClock();
    Gateway g = new Gateway();
    MonitorService s = new MonitorService(g, clock, 600);
    var a = s.start(request());
    s.cancel(a.id(), a.sessionToken());
    clock.advance(1);
    s.process(sample(train(clock.instant(), "0202")));
    assertEquals(0, g.calls.get());
    assertEquals("CANCELLED", s.status(a.id(), a.sessionToken()).status());
    var b = s.start(request());
    clock.advance(61);
    s.process(sample(train(clock.instant().minusSeconds(61), "0202")));
    assertEquals(0, g.calls.get());
    clock.advance(7200);
    assertEquals("EXPIRED", s.status(b.id(), b.sessionToken()).status());
  }

  @Test
  void manualTestSeparatesUnavailableFromAcceptedAndRequiresAuth() {
    FakeClock clock = new FakeClock();
    Gateway g = new Gateway();
    g.result = NotificationGateway.Result.UNAVAILABLE;
    MonitorService s = new MonitorService(g, clock, 600);
    var a = s.start(request());
    assertThrows(MonitorService.NotFound.class, () -> s.test(a.id(), "wrong"));
    s.test(a.id(), a.sessionToken());
    assertEquals("UNAVAILABLE", s.status(a.id(), a.sessionToken()).deliveryStatus());
    assertEquals("TRACKING", s.status(a.id(), a.sessionToken()).status());
  }

  @Test
  void onlyActiveSessionsPollOnceAndDailyBudgetStopsMoreRequests() {
    FakeClock clock = new FakeClock();
    Gateway g = new Gateway();
    MonitorService s = new MonitorService(g, clock, 2);
    AtomicInteger requests = new AtomicInteger();
    s.poll(
        () -> {
          requests.incrementAndGet();
          return sample(train(clock.instant(), "none"));
        });
    assertEquals(0, requests.get());
    var a = s.start(request());
    s.start(request());
    for (int i = 0; i < 3; i++)
      s.poll(
          () -> {
            requests.incrementAndGet();
            return sample(train(clock.instant(), "none"));
          });
    assertEquals(2, requests.get());
    assertEquals("DAILY_LIMIT", s.status(a.id(), a.sessionToken()).pollStatus());
  }

  @Test
  void concurrentMatchingSendsAtMostOnce() throws Exception {
    FakeClock clock = new FakeClock();
    Gateway g = new Gateway();
    MonitorService s = new MonitorService(g, clock, 600);
    s.start(request());
    clock.advance(1);
    ExecutorService ex = Executors.newFixedThreadPool(8);
    try {
      var tasks =
          java.util.stream.IntStream.range(0, 20)
              .<Callable<Void>>mapToObj(
                  i ->
                      () -> {
                        s.process(sample(train(clock.instant(), "0202")));
                        return null;
                      })
              .toList();
      for (var future : ex.invokeAll(tasks)) future.get();
    } finally {
      ex.shutdownNow();
    }
    assertEquals(1, g.calls.get());
  }

  @Test
  void delayedSendDoesNotAllowAStaleEventToNotifyAnotherSession() {
    FakeClock clock = new FakeClock();
    AtomicInteger calls = new AtomicInteger();
    NotificationGateway g =
        new NotificationGateway() {
          public boolean available() {
            return true;
          }

          public Result send(String token, String p, String d, String mode) {
            calls.incrementAndGet();
            clock.advance(61);
            return Result.ACCEPTED;
          }
        };
    MonitorService s = new MonitorService(g, clock, 600);
    s.start(request());
    s.start(request());
    clock.advance(1);
    var event = sample(train(clock.instant(), "0202"));
    s.process(event);
    assertEquals(1, calls.get());
  }

  @Test
  void cancelDoesNotBlockWhilePushNetworkIsInFlight() throws Exception {
    FakeClock clock = new FakeClock();
    CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
    NotificationGateway g =
        new NotificationGateway() {
          public boolean available() {
            return true;
          }

          public Result send(String token, String p, String d, String mode) {
            entered.countDown();
            try {
              release.await(5, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
              Thread.currentThread().interrupt();
            }
            return Result.ACCEPTED;
          }
        };
    MonitorService s = new MonitorService(g, clock, 600);
    var a = s.start(request());
    clock.advance(1);
    ExecutorService ex = Executors.newFixedThreadPool(2);
    try {
      var delivery = ex.submit(() -> s.process(sample(train(clock.instant(), "0202"))));
      assertTrue(entered.await(3, TimeUnit.SECONDS));
      var cancelled = ex.submit(() -> s.cancel(a.id(), a.sessionToken()));
      assertEquals("CANCELLED", cancelled.get(2, TimeUnit.SECONDS).status());
      release.countDown();
      delivery.get(3, TimeUnit.SECONDS);
      assertEquals("CANCELLED", s.status(a.id(), a.sessionToken()).status());
    } finally {
      release.countDown();
      ex.shutdownNow();
    }
  }
}
