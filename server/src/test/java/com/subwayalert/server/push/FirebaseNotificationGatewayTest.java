package com.subwayalert.server.push;

import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class FirebaseNotificationGatewayTest {
  @Test void unavailableWithoutExplicitFirebaseConfiguration() {
    var gateway = FirebaseNotificationGateway.disabled();
    assertFalse(gateway.available());
    assertEquals(NotificationGateway.Result.UNAVAILABLE, gateway.send("device", "역삼", "선릉", "TEST"));
  }

  @Test void testNotificationIsClearlyMarkedAndHasShortLifetime() {
    AtomicReference<FirebaseNotificationGateway.Envelope> captured = new AtomicReference<>();
    var gateway = new FirebaseNotificationGateway(envelope -> captured.set(envelope));
    assertEquals(NotificationGateway.Result.ACCEPTED, gateway.send("abc:123", "역삼", "선릉", "TEST"));
    var message = captured.get();
    assertTrue(message.title().contains("시험"));
    assertTrue(message.body().contains("시험"));
    assertTrue(message.body().contains("선릉"));
    assertEquals("subway-alerts", message.channel());
    assertEquals(30000L, message.ttlMillis());
    assertEquals("HIGH", message.priority());
  }

  @Test void neverSendsUnrecognizedSourceOrEmptyToken() {
    var calls = new java.util.concurrent.atomic.AtomicInteger();
    var gateway = new FirebaseNotificationGateway(envelope -> calls.incrementAndGet());
    assertEquals(NotificationGateway.Result.FAILED, gateway.send("valid", "역삼", "선릉", "SAMPLE"));
    assertEquals(NotificationGateway.Result.FAILED, gateway.send("  ", "역삼", "선릉", "TEST"));
    assertEquals(0, calls.get());
  }

  @Test void senderFailureIsReportedWithoutPropagatingSensitiveError() {
    var gateway = new FirebaseNotificationGateway(envelope -> { throw new IllegalStateException("token and secrets"); });
    assertEquals(NotificationGateway.Result.FAILED, gateway.send("valid", "역삼", "선릉", "TEST"));
  }

  @Test void liveHasDifferentUserVisibleText() {
    AtomicReference<FirebaseNotificationGateway.Envelope> captured = new AtomicReference<>();
    var gateway = new FirebaseNotificationGateway(captured::set);
    assertEquals(NotificationGateway.Result.ACCEPTED, gateway.send("token", "역삼", "선릉", "LIVE"));
    assertFalse(captured.get().title().contains("시험"));
    assertTrue(captured.get().body().contains("선릉"));
  }

  @Test void firebaseSdkSerializesNotificationPayloadForAndroid() throws Exception {
    var envelope = new FirebaseNotificationGateway.Envelope("device-token", "[시험] 알림", "시험입니다", "subway-alerts", 30000, "HIGH", "TEST");
    String json = com.google.api.client.json.gson.GsonFactory.getDefaultInstance().toString(FirebaseNotificationGateway.toMessage(envelope));
    var root = new com.fasterxml.jackson.databind.ObjectMapper().readTree(json);
    assertEquals("device-token", root.path("token").asText());
    assertEquals("[시험] 알림", root.path("notification").path("title").asText());
    assertEquals("high", root.path("android").path("priority").asText());
    assertEquals("30s", root.path("android").path("ttl").asText());
    assertEquals("subway-alerts", root.path("android").path("notification").path("channel_id").asText());
    assertEquals("com.yuilyoung.subwayalert", root.path("android").path("restricted_package_name").asText());
  }

  @Test void firebaseHttpHasBoundedConnectReadAndWriteTimeouts() {
    var credential = com.google.auth.oauth2.GoogleCredentials.create(
        new com.google.auth.oauth2.AccessToken("example", new java.util.Date(System.currentTimeMillis() + 60000)));
    var options = NotificationConfiguration.options(credential, "project-id");
    assertEquals(5000, options.getConnectTimeout());
    assertEquals(5000, options.getReadTimeout());
    assertEquals(5000, options.getWriteTimeout());
  }
}
