package com.subwayalert.server.monitor;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.subwayalert.server.access.ApiAccessFilter;
import com.subwayalert.server.live.SeoulTrainProvider;
import com.subwayalert.server.push.NotificationGateway;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

/** Real service/controller/filter boundary; only the external notification gateway is replaced. */
class MonitorRegistrationRecoveryTest {
  static final String API_KEY = "abcdefghijklmnopqrstuvwxyzABCDEF";
  static final String ID = "e4018ddc-2939-4bb3-9259-bd803b1aba1d";
  static final String SECRET = "0123456789abcdef".repeat(4),
      OTHER_SECRET = "abcdef0123456789".repeat(4);
  static final String BODY =
      "{\"lineId\":\"2\",\"trainId\":\"0202\",\"direction\":\"INNER\",\"previousStation\":\"선릉\",\"destinationStation\":\"삼성\",\"fcmToken\":\"sensitive-fcm-token\",\"mode\":\"TEST\"}";
  static final ObjectMapper JSON = new ObjectMapper();

  static final class MutableClock extends Clock {
    volatile Instant now = Instant.parse("2026-10-27T12:00:00Z");

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

  static final class Fixture {
    final MutableClock clock = new MutableClock();
    final AtomicLong elapsed = new AtomicLong();
    final AtomicInteger sends = new AtomicInteger();
    final MonitorService service =
        new MonitorService(
            new NotificationGateway() {
              public boolean available() {
                return true;
              }

              public Result send(String token, String previous, String destination, String mode) {
                sends.incrementAndGet();
                return Result.ACCEPTED;
              }
            },
            clock,
            600);
    final MockMvc mvc =
        MockMvcBuilders.standaloneSetup(new MonitorController(service))
            .setMessageConverters(
                new org.springframework.http.converter.json.MappingJackson2HttpMessageConverter(
                    new ObjectMapper()
                        .findAndRegisterModules()
                        .disable(
                            com.fasterxml.jackson.databind.SerializationFeature
                                .WRITE_DATES_AS_TIMESTAMPS)))
            .addFilters(new ApiAccessFilter(API_KEY, elapsed::get, clock))
            .build();

    ResultActions perform(MockHttpServletRequestBuilder request) throws Exception {
      // Keep the real quota filter, moving only its elapsed-time input between ordinary requests.
      elapsed.addAndGet(TimeUnit.SECONDS.toNanos(20));
      return mvc.perform(request.header("Authorization", "Bearer " + API_KEY));
    }

    ResultActions start(String id, String secret, String body) throws Exception {
      return perform(
          post("/api/monitor-sessions")
              .header("Idempotency-Key", id)
              .header("X-Session-Token", secret)
              .contentType("application/json")
              .content(body));
    }

    ResultActions cancel(String id, String secret) throws Exception {
      return perform(delete("/api/monitor-sessions/" + id).header("X-Session-Token", secret));
    }

    ResultActions lookup(String id, String secret) throws Exception {
      return perform(get("/api/monitor-sessions/" + id).header("X-Session-Token", secret));
    }

    JsonNode created() throws Exception {
      return json(start(ID, SECRET, BODY).andExpect(status().isOk()));
    }

    void fill(int count) {
      for (int i = 0; i < count; i++) service.start(request());
    }

    void process() {
      service.process(
          new SeoulTrainProvider.Result(
              "SAMPLE",
              List.of(
                  new SeoulTrainProvider.Train(
                      "2", "선릉", "0202", "INNER", "DEPARTED", clock.instant(), false, true)),
              "sample"));
    }
  }

  static MonitorService.StartRequest request() {
    return new MonitorService.StartRequest(
        "2", "0202", "INNER", "선릉", "삼성", "sensitive-fcm-token", "TEST");
  }

  static JsonNode json(ResultActions result) throws Exception {
    return JSON.readTree(result.andReturn().getResponse().getContentAsString());
  }

  @Test
  void clientIdentityAndCanonicalRequestReplayKeepOriginalExpiry() throws Exception {
    var f = new Fixture();
    var first = f.created();
    assertEquals(ID, first.path("id").asText());
    assertEquals(SECRET, first.path("sessionToken").asText());
    assertEquals("2026-10-27T14:00:00Z", first.path("expiresAt").asText());
    f.clock.advance(60);
    var replay =
        json(
            f.start(
                    ID,
                    SECRET,
                    BODY.replace("0202", " 0202 ").replace("선릉", " 선릉 ").replace("삼성", " 삼성 "))
                .andExpect(status().isOk()));
    assertEquals(first, replay);
    assertEquals(0, f.sends.get());
    // Leading zeros are part of the train identity, not a numeric conversion.
    f.start(ID, SECRET, BODY.replace("0202", "202")).andExpect(status().isConflict());
  }

  @Test
  void changedSecretAndEachMeaningfulBodyFieldConflictWithoutDisclosingTokens() throws Exception {
    var f = new Fixture();
    f.created();
    for (String body :
        new String[] {
          BODY.replace("0202", "0203"),
          BODY.replace("INNER", "OUTER"),
          BODY.replace("선릉", "강남"),
          BODY.replace("삼성", "역삼"),
          BODY.replace("sensitive-fcm-token", "replacement-fcm-token")
        })
      f.start(ID, SECRET, body)
          .andExpect(status().isConflict())
          .andExpect(
              content()
                  .string(
                      org.hamcrest.Matchers.not(
                          org.hamcrest.Matchers.containsString("fcm-token"))));
    f.start(ID, OTHER_SECRET, BODY)
        .andExpect(status().isConflict())
        .andExpect(
            content()
                .string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString(SECRET))));
    f.lookup(ID, SECRET)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("TRACKING"));
  }

  @Test
  void changedInvalidBodyForExistingIdentityConflictsWhileFreshInvalidBodyIsBadRequest()
      throws Exception {
    var f = new Fixture();
    f.created();
    for (String body :
        new String[] {
          BODY.replace("\"2\"", "\"3\""),
          BODY.replace("TEST", "LIVE"),
          BODY.replace("sensitive-fcm-token", "")
        }) {
      f.start(ID, SECRET, body).andExpect(status().isConflict());
      f.start(UUID.randomUUID().toString(), SECRET, body).andExpect(status().isBadRequest());
    }
  }

  @Test
  void missingMalformedNonCanonicalAndDuplicateCreationHeadersAreBadRequests() throws Exception {
    for (String id :
        new String[] {
          "", ID.toUpperCase(), "e4018ddc-2939-1bb3-9259-bd803b1aba1d", "1-1-4-8-1", ID + "," + ID
        }) {
      var f = new Fixture();
      var req =
          post("/api/monitor-sessions")
              .header("X-Session-Token", SECRET)
              .contentType("application/json")
              .content(BODY);
      if (!id.isEmpty()) req.header("Idempotency-Key", id);
      f.perform(req).andExpect(status().isBadRequest());
    }
    for (String secret :
        new String[] {
          "", SECRET.toUpperCase(), SECRET.substring(1), SECRET + "0", SECRET + "," + SECRET
        }) {
      var f = new Fixture();
      var req =
          post("/api/monitor-sessions")
              .header("Idempotency-Key", ID)
              .contentType("application/json")
              .content(BODY);
      if (!secret.isEmpty()) req.header("X-Session-Token", secret);
      f.perform(req).andExpect(status().isBadRequest());
    }
    for (String header : new String[] {"Idempotency-Key", "X-Session-Token"}) {
      var f = new Fixture();
      String duplicate = header.equals("Idempotency-Key") ? ID : SECRET;
      f.perform(
              post("/api/monitor-sessions")
                  .header("Idempotency-Key", ID)
                  .header("X-Session-Token", SECRET)
                  .header(header, duplicate)
                  .contentType("application/json")
                  .content(BODY))
          .andExpect(status().isBadRequest());
    }
  }

  @Test
  void cancelledReplayNeverResurrectsOrNotifies() throws Exception {
    var f = new Fixture();
    var first = f.created();
    f.cancel(ID, SECRET)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("CANCELLED"));
    f.clock.advance(1);
    f.start(ID, SECRET, BODY)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("CANCELLED"))
        .andExpect(jsonPath("$.expiresAt").value(first.path("expiresAt").asText()));
    f.process();
    assertEquals(0, f.sends.get());
  }

  @Test
  void matchedReplayKeepsConsumedMatcherAndDoesNotResend() throws Exception {
    var f = new Fixture();
    f.created();
    f.clock.advance(1);
    f.process();
    assertEquals(1, f.sends.get());
    f.start(ID, SECRET, BODY)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("SAMPLE_MATCHED"));
    f.process();
    assertEquals(1, f.sends.get());
  }

  @Test
  void expiredReplayDoesNotExtendLifetimeAndRetentionEventuallyAllowsNewRegistration()
      throws Exception {
    var f = new Fixture();
    f.created();
    f.clock.advance(7200);
    f.start(ID, SECRET, BODY)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("EXPIRED"))
        .andExpect(jsonPath("$.expiresAt").value("2026-10-27T14:00:00Z"));
    f.clock.advance(3599);
    f.start(ID, SECRET, BODY)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("EXPIRED"));
    f.clock.advance(1);
    f.start(ID, SECRET, BODY)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("TRACKING"))
        .andExpect(jsonPath("$.expiresAt").value("2026-10-27T17:00:00Z"));
  }

  @Test
  void cancellationBeforeRegistrationCreatesAuthorizedTombstoneAndBlocksLateStart()
      throws Exception {
    var f = new Fixture();
    f.cancel(ID, SECRET)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("CANCELLED"))
        .andExpect(jsonPath("$.expiresAt").value("2026-10-27T14:00:00Z"));
    f.lookup(ID, SECRET)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("CANCELLED"));
    f.start(ID, SECRET, BODY)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("CANCELLED"));
    // A tombstone has no original request body to compare, but still binds its secret.
    f.start(ID, SECRET, BODY.replace("0202", "0203"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("CANCELLED"));
    f.cancel(ID, OTHER_SECRET).andExpect(status().isNotFound());
    f.start(ID, OTHER_SECRET, BODY).andExpect(status().isConflict());
    f.process();
    var polls = new AtomicInteger();
    f.service.poll(
        () -> {
          polls.incrementAndGet();
          return null;
        });
    assertEquals(0, f.sends.get());
    assertEquals(0, polls.get());
  }

  @Test
  void tombstoneRetentionUsesOriginalLifetimeAndIsNotExtendedByRepeatedCancel() throws Exception {
    var f = new Fixture();
    f.cancel(ID, SECRET).andExpect(status().isOk());
    f.clock.advance(7199);
    f.cancel(ID, SECRET)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.expiresAt").value("2026-10-27T14:00:00Z"));
    f.clock.advance(3600);
    f.start(ID, SECRET, BODY)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("CANCELLED"));
    f.clock.advance(1);
    f.start(ID, SECRET, BODY)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("TRACKING"));
  }

  @Test
  void missingGetRemainsNotFoundAndCannotCreateOrCancelASession() throws Exception {
    var f = new Fixture();
    f.lookup(ID, SECRET).andExpect(status().isNotFound());
    f.created();
    f.perform(get("/api/monitor-sessions/" + ID)).andExpect(status().isNotFound());
    f.lookup(ID, OTHER_SECRET).andExpect(status().isNotFound());
    f.perform(get("/api/monitor-sessions/" + ID).header("X-Session-Token", SECRET, OTHER_SECRET))
        .andExpect(status().isNotFound());
    f.lookup(ID, SECRET)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.sessionToken").doesNotExist())
        .andExpect(jsonPath("$.fcmToken").doesNotExist());
    f.cancel(ID, OTHER_SECRET).andExpect(status().isNotFound());
    f.lookup(ID, SECRET)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("TRACKING"));
  }

  @Test
  void fullCapacityStillReplaysAndCancelsExistingSessionButRejectsNewEntries() throws Exception {
    var f = new Fixture();
    f.created();
    f.fill(499);
    f.start(ID, SECRET, BODY).andExpect(status().isOk());
    f.start(ID, OTHER_SECRET, BODY).andExpect(status().isConflict());
    f.start(UUID.randomUUID().toString(), SECRET, BODY).andExpect(status().isServiceUnavailable());
    f.cancel(UUID.randomUUID().toString(), SECRET).andExpect(status().isServiceUnavailable());
    f.cancel(ID, SECRET)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("CANCELLED"));
  }

  @Test
  void tombstonesCountTowardTheSameFiveHundredEntryCapacity() throws Exception {
    var f = new Fixture();
    f.fill(499);
    f.cancel(ID, SECRET).andExpect(status().isOk());
    f.start(UUID.randomUUID().toString(), SECRET, BODY).andExpect(status().isServiceUnavailable());
    f.cancel(UUID.randomUUID().toString(), SECRET).andExpect(status().isServiceUnavailable());
    f.start(ID, SECRET, BODY)
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("CANCELLED"));
    f.cancel(ID, SECRET).andExpect(status().isOk());
  }

  @Test
  void simultaneousSameIdentityStartsUseOneCapacityEntryAndNeverSendFromPost() throws Exception {
    var f = new Fixture();
    var pool = Executors.newFixedThreadPool(2);
    var gate = new CountDownLatch(1);
    try {
      var a =
          pool.submit(
              () -> {
                gate.await();
                return json(f.start(ID, SECRET, BODY).andExpect(status().isOk()));
              });
      var b =
          pool.submit(
              () -> {
                gate.await();
                return json(f.start(ID, SECRET, BODY).andExpect(status().isOk()));
              });
      gate.countDown();
      assertEquals(ID, a.get(3, TimeUnit.SECONDS).path("id").asText());
      assertEquals(ID, b.get(3, TimeUnit.SECONDS).path("id").asText());
      f.fill(499);
      f.start(UUID.randomUUID().toString(), SECRET, BODY)
          .andExpect(status().isServiceUnavailable());
      assertEquals(0, f.sends.get());
    } finally {
      pool.shutdownNow();
    }
  }

  @Test
  void competingStartAndCancellationAlwaysFinishCancelled() throws Exception {
    var pool = Executors.newFixedThreadPool(2);
    try {
      for (int i = 0; i < 12; i++) {
        var f = new Fixture();
        var gate = new CountDownLatch(1);
        var start =
            pool.submit(
                () -> {
                  gate.await();
                  return f.start(ID, SECRET, BODY).andReturn().getResponse().getStatus();
                });
        var cancel =
            pool.submit(
                () -> {
                  gate.await();
                  return f.cancel(ID, SECRET).andReturn().getResponse().getStatus();
                });
        gate.countDown();
        assertEquals(200, start.get(3, TimeUnit.SECONDS));
        assertEquals(200, cancel.get(3, TimeUnit.SECONDS));
        f.lookup(ID, SECRET)
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.status").value("CANCELLED"));
        f.start(ID, SECRET, BODY)
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.status").value("CANCELLED"));
        f.process();
        assertEquals(0, f.sends.get());
      }
    } finally {
      pool.shutdownNow();
    }
  }

  @Test
  void creationReplayStillRequiresBearerAndConsumesCreationQuota() throws Exception {
    var f = new Fixture();
    f.mvc
        .perform(
            post("/api/monitor-sessions")
                .header("Idempotency-Key", ID)
                .header("X-Session-Token", SECRET)
                .contentType("application/json")
                .content(BODY))
        .andExpect(status().isUnauthorized());
    for (int i = 0; i < 3; i++)
      f.mvc
          .perform(
              post("/api/monitor-sessions")
                  .header("Authorization", "Bearer " + API_KEY)
                  .header("Idempotency-Key", ID)
                  .header("X-Session-Token", SECRET)
                  .contentType("application/json")
                  .content(BODY))
          .andExpect(status().isOk())
          .andExpect(jsonPath("$.id").value(ID));
    f.mvc
        .perform(
            post("/api/monitor-sessions")
                .header("Authorization", "Bearer " + API_KEY)
                .header("Idempotency-Key", ID)
                .header("X-Session-Token", SECRET)
                .contentType("application/json")
                .content(BODY))
        .andExpect(status().isTooManyRequests());
  }
}
