package com.subwayalert.server.monitor;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.subwayalert.server.live.SeoulTrainProvider;
import com.subwayalert.server.push.NotificationGateway;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class MonitorDurabilityTest {
  static final UUID ID = UUID.fromString("e4018ddc-2939-4bb3-9259-bd803b1aba1d");
  static final String SECRET = "0123456789abcdef".repeat(4);
  static final MonitorService.StartRequest REQUEST =
      new MonitorService.StartRequest(
          "2", "0202", "INNER", "선릉", "삼성", "private-fcm-token", "TEST");

  static final class MutableClock extends Clock {
    Instant now = Instant.parse("2026-10-27T12:00:00Z");

    public ZoneId getZone() {
      return ZoneOffset.UTC;
    }

    public Clock withZone(ZoneId zone) {
      return this;
    }

    public Instant instant() {
      return now;
    }

    void advance(long seconds) {
      now = now.plusSeconds(seconds);
    }
  }

  /** Simulated durable disk; only restart normalization is shared with the real store. */
  static final class Disk implements MonitorReceiptStore {
    final Map<UUID, MonitorReceipt> rows = new HashMap<>();
    final List<MonitorReceipt> writes = new ArrayList<>();
    boolean fail, failSave, failDelete;

    public List<MonitorReceipt> restore(Instant now) {
      checkAvailable();
      rows.values().removeIf(r -> !now.isBefore(r.expiresAt().plusSeconds(3600)));
      rows.replaceAll((id, r) -> r.afterRestart(now));
      return List.copyOf(rows.values());
    }

    public void save(MonitorReceipt receipt) {
      checkAvailable();
      if (failSave) throw new MonitorReceiptStore.Unavailable();
      rows.put(receipt.id(), receipt);
      writes.add(receipt);
    }

    public void delete(UUID id) {
      checkAvailable();
      if (failDelete) throw new MonitorReceiptStore.Unavailable();
      rows.remove(id);
    }

    public void checkAvailable() {
      if (fail) throw new MonitorReceiptStore.Unavailable();
    }

    public void close() {}
  }

  static final class Fixture {
    final Disk disk = new Disk();
    final MutableClock clock = new MutableClock();
    final AtomicInteger sends = new AtomicInteger();
    final NotificationGateway gateway =
        new NotificationGateway() {
          public boolean available() {
            return true;
          }

          public Result send(String t, String p, String d, String m) {
            assertEquals(
                "SENDING",
                disk.rows.get(ID).deliveryStatus(),
                "delivery claim must be durable before gateway invocation");
            sends.incrementAndGet();
            return Result.ACCEPTED;
          }
        };

    MonitorService create() {
      return new MonitorService(gateway, clock, 600, disk);
    }

    SeoulTrainProvider.Result event() {
      return new SeoulTrainProvider.Result(
          "SAMPLE",
          List.of(
              new SeoulTrainProvider.Train(
                  "2", "선릉", "0202", "INNER", "DEPARTED", clock.instant(), false, true)),
          "sample");
    }
  }

  @Test
  void restartStopsTrackingKeepsOriginalIdentityExpiryAndNeverRestoresLiveInputs() {
    var f = new Fixture();
    var first = f.create().start(ID, SECRET, REQUEST);
    f.clock.advance(60);
    var restored = f.create();
    var replay = restored.start(ID, SECRET, REQUEST);
    assertEquals("CANCELLED", replay.status());
    assertEquals(first.expiresAt(), replay.expiresAt());
    assertEquals(ID, replay.id());
    assertThrows(
        MonitorService.Conflict.class,
        () -> restored.start(ID, "abcdef0123456789".repeat(4), REQUEST));
    assertThrows(
        MonitorService.Conflict.class,
        () ->
            restored.start(
                ID,
                SECRET,
                new MonitorService.StartRequest(
                    "2", "0203", "INNER", "선릉", "삼성", "private-fcm-token", "TEST")));
    restored.process(f.event());
    var polls = new AtomicInteger();
    restored.poll(
        () -> {
          polls.incrementAndGet();
          return f.event();
        });
    assertEquals(0, polls.get());
    assertEquals(0, f.sends.get());
    var receipt = f.disk.rows.get(ID);
    assertEquals(64, receipt.sessionHash().length());
    assertEquals(64, receipt.fingerprintHash().length());
    assertFalse(receipt.toString().contains(SECRET));
    assertFalse(receipt.toString().contains("private-fcm-token"));
  }

  @Test
  void restartExpiresTrackingAtOriginalDeadlineAndPrunesAfterRetention() {
    var f = new Fixture();
    var initial = f.create().start(ID, SECRET, REQUEST);
    f.clock.advance(7200);
    var restored = f.create();
    var replay = restored.start(ID, SECRET, REQUEST);
    assertEquals("EXPIRED", replay.status());
    assertEquals(initial.expiresAt(), replay.expiresAt());
    f.clock.advance(3600);
    var next = f.create().start(ID, SECRET, REQUEST);
    assertEquals("TRACKING", next.status());
    assertEquals(f.clock.instant().plusSeconds(7200), next.expiresAt());
  }

  @Test
  void cancelBeforeRegisterAndRepeatedCancelSurviveRestartWithoutExtendingExpiry() {
    var f = new Fixture();
    var original = f.create().cancel(ID, SECRET);
    f.clock.advance(100);
    var restored = f.create();
    assertEquals("CANCELLED", restored.start(ID, SECRET, REQUEST).status());
    assertEquals(original.expiresAt(), restored.cancel(ID, SECRET).expiresAt());
    assertNull(f.disk.rows.get(ID).fingerprintHash());
    assertThrows(MonitorService.NotFound.class, () -> restored.cancel(ID, "bad-secret"));
  }

  @Test
  void failedCreationAndCancellationNeverAcknowledgeAndPermanentlyCloseAllApis() {
    var f = new Fixture();
    var service = f.create();
    f.disk.failSave = true;
    assertThrows(MonitorService.Unavailable.class, () -> service.start(ID, SECRET, REQUEST));
    f.disk.failSave = false;
    assertThrows(MonitorService.Unavailable.class, () -> service.start(ID, SECRET, REQUEST));
    assertThrows(MonitorService.Unavailable.class, () -> service.status(ID, SECRET));
    assertThrows(MonitorService.Unavailable.class, () -> service.cancel(ID, SECRET));
    assertThrows(MonitorService.Unavailable.class, () -> service.test(ID, SECRET));
    var other = new Fixture();
    var active = other.create();
    active.start(ID, SECRET, REQUEST);
    other.disk.failSave = true;
    assertThrows(MonitorService.Unavailable.class, () -> active.cancel(ID, SECRET));
  }

  @Test
  void failedSendingClaimBlocksPushAndLaterPollsEvenAfterDiskRecovers() {
    var f = new Fixture();
    var service = f.create();
    service.start(ID, SECRET, REQUEST);
    f.clock.advance(1);
    f.disk.failSave = true;
    assertThrows(MonitorService.Unavailable.class, () -> service.test(ID, SECRET));
    f.disk.failSave = false;
    service.process(f.event());
    var polls = new AtomicInteger();
    service.poll(
        () -> {
          polls.incrementAndGet();
          return f.event();
        });
    assertEquals(0, f.sends.get());
    assertEquals(0, polls.get());
  }

  @Test
  void sendingClaimIsPersistedBeforePushAndUnfinishedSendRestoresUnknown() {
    var f = new Fixture();
    var service = f.create();
    service.start(ID, SECRET, REQUEST);
    service.test(ID, SECRET);
    assertEquals(1, f.sends.get());
    assertEquals("FCM_ACCEPTED", f.disk.rows.get(ID).deliveryStatus());
    var row = f.disk.rows.get(ID);
    f.disk.rows.put(
        ID,
        new MonitorReceipt(
            row.id(),
            row.sessionHash(),
            row.fingerprintHash(),
            row.expiresAt(),
            "TRACKING",
            "SENDING"));
    var restored = f.create();
    var status = restored.status(ID, SECRET);
    assertEquals("CANCELLED", status.status());
    assertEquals("UNKNOWN", status.deliveryStatus());
    restored.process(f.event());
    assertEquals(1, f.sends.get());
  }

  @Test
  void initialExpiryUsesDatabasePrecisionSoReplayIsExactlyEqualAfterRestart() {
    var f = new Fixture();
    f.clock.now = f.clock.now.plusNanos(123456789);
    var initial = f.create().start(ID, SECRET, REQUEST);
    assertEquals(0, initial.expiresAt().getNano() % 1000);
    assertEquals(initial.expiresAt(), f.create().start(ID, SECRET, REQUEST).expiresAt());
    var tombstoneId = UUID.randomUUID();
    var tombstone = f.create().cancel(tombstoneId, SECRET);
    assertEquals(0, tombstone.expiresAt().getNano() % 1000);
    assertEquals(tombstone.expiresAt(), f.create().status(tombstoneId, SECRET).expiresAt());
  }

  @Test
  void failedDeliveryResultWriteLeavesDurableSendingAndRestartMarksUnknown() {
    var f = new Fixture();
    NotificationGateway gateway =
        new NotificationGateway() {
          public boolean available() {
            return true;
          }

          public Result send(String t, String p, String d, String m) {
            assertEquals("SENDING", f.disk.rows.get(ID).deliveryStatus());
            f.sends.incrementAndGet();
            f.disk.failSave = true;
            return Result.ACCEPTED;
          }
        };
    var service = new MonitorService(gateway, f.clock, 600, f.disk);
    service.start(ID, SECRET, REQUEST);
    assertThrows(MonitorService.Unavailable.class, () -> service.test(ID, SECRET));
    assertEquals(1, f.sends.get());
    assertEquals("SENDING", f.disk.rows.get(ID).deliveryStatus());
    f.disk.failSave = false;
    assertThrows(MonitorService.Unavailable.class, () -> service.status(ID, SECRET));
    assertEquals("UNKNOWN", f.create().status(ID, SECRET).deliveryStatus());
  }

  @Test
  void failedRetentionDeleteClosesApiAndCannotReuseTheIdentity() {
    var f = new Fixture();
    var service = f.create();
    service.cancel(ID, SECRET);
    f.clock.advance(10800);
    f.disk.failDelete = true;
    assertThrows(MonitorService.Unavailable.class, () -> service.start(ID, SECRET, REQUEST));
    assertEquals("CANCELLED", f.disk.rows.get(ID).state());
    f.disk.failDelete = false;
    assertThrows(MonitorService.Unavailable.class, () -> service.start(ID, SECRET, REQUEST));
  }

  @Test
  void finishedMatchedSessionKeepsOutcomeAndUnfinishedMatchedSendBecomesUnknown() {
    var f = new Fixture();
    var service = f.create();
    service.start(ID, SECRET, REQUEST);
    f.clock.advance(1);
    service.process(f.event());
    assertEquals("SAMPLE_MATCHED", f.disk.rows.get(ID).state());
    assertEquals("FCM_ACCEPTED", f.create().status(ID, SECRET).deliveryStatus());
    var row = f.disk.rows.get(ID);
    f.disk.rows.put(
        ID,
        new MonitorReceipt(
            row.id(),
            row.sessionHash(),
            row.fingerprintHash(),
            row.expiresAt(),
            row.state(),
            "SENDING"));
    var recovered = f.create();
    assertEquals("SAMPLE_MATCHED", recovered.status(ID, SECRET).status());
    assertEquals("UNKNOWN", recovered.status(ID, SECRET).deliveryStatus());
    recovered.process(f.event());
    assertEquals(1, f.sends.get());
  }

  @Test
  void corruptedNonRandomReceiptIdentityIsRejectedBeforeRestoring() {
    assertThrows(
        IllegalArgumentException.class,
        () ->
            new MonitorReceipt(
                UUID.fromString("e4018ddc-2939-1bb3-9259-bd803b1aba1d"),
                "a".repeat(64),
                null,
                Instant.now(),
                "CANCELLED",
                "NONE"));
  }

  @Test
  void httpStorageFailureIsSanitized503ForEveryMonitorOperation() throws Exception {
    var f = new Fixture();
    var service = f.create();
    service.start(ID, SECRET, REQUEST);
    f.disk.fail = true;
    var mvc = MockMvcBuilders.standaloneSetup(new MonitorController(service)).build();
    mvc.perform(get("/api/monitor-sessions/" + ID).header("X-Session-Token", SECRET))
        .andExpect(status().isServiceUnavailable());
    mvc.perform(delete("/api/monitor-sessions/" + ID).header("X-Session-Token", SECRET))
        .andExpect(status().isServiceUnavailable());
    mvc.perform(post("/api/monitor-sessions/" + ID + "/test").header("X-Session-Token", SECRET))
        .andExpect(status().isServiceUnavailable());
    mvc.perform(
            post("/api/monitor-sessions")
                .header("Idempotency-Key", ID)
                .header("X-Session-Token", SECRET)
                .contentType("application/json")
                .content(MonitorRegistrationRecoveryTest.BODY))
        .andExpect(status().isServiceUnavailable());
  }
}
