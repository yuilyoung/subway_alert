package com.subwayalert.server.push;

import com.google.firebase.messaging.AndroidConfig;
import com.google.firebase.messaging.AndroidNotification;
import com.google.firebase.messaging.FirebaseMessaging;
import com.google.firebase.messaging.Message;
import com.google.firebase.messaging.Notification;
import java.util.Objects;

/** FCM transport, enabled only when a trusted server administrator configures credentials. */
public final class FirebaseNotificationGateway implements NotificationGateway {
  static final long TTL_MILLIS = 30_000L;
  static final String CHANNEL = "subway-alerts";
  static final String ANDROID_PACKAGE = "com.yuilyoung.subwayalert";
  record Envelope(String token, String title, String body, String channel, long ttlMillis, String priority, String mode) { }
  @FunctionalInterface interface Sender { void send(Envelope envelope) throws Exception; }

  private final Sender sender;
  FirebaseNotificationGateway(Sender sender) { this.sender = sender; }
  public static FirebaseNotificationGateway disabled() { return new FirebaseNotificationGateway(null); }
  static FirebaseNotificationGateway using(FirebaseMessaging messaging) {
    Objects.requireNonNull(messaging);
    return new FirebaseNotificationGateway(envelope -> messaging.send(toMessage(envelope)));
  }
  @Override public boolean available() { return sender != null; }

  @Override public Result send(String token, String previousStation, String destinationStation, String mode) {
    if (!available()) return Result.UNAVAILABLE;
    if (!valid(token, 4096) || !valid(previousStation, 80) || !valid(destinationStation, 80)
        || !("TEST".equals(mode) || "LIVE".equals(mode))) return Result.FAILED;
    boolean test = "TEST".equals(mode);
    String title = test ? "[시험] 지하철 하차 알림" : "하차 준비 알림";
    String body = test
        ? "시험 알림: " + previousStation.strip() + " → " + destinationStation.strip() + ". 실제 열차 위치와 무관합니다."
        : previousStation.strip() + "에서 출발했습니다. 다음 역 " + destinationStation.strip() + "에서 하차할 준비를 하세요.";
    Envelope envelope = new Envelope(token, title, body, CHANNEL, TTL_MILLIS, "HIGH", mode);
    try {
      sender.send(envelope);
      return Result.ACCEPTED;
    } catch (Exception e) {
      // The exception may contain an API response or device token. Never log or expose it.
      return Result.FAILED;
    }
  }

  static Message toMessage(Envelope envelope) {
    Notification notification = Notification.builder().setTitle(envelope.title()).setBody(envelope.body()).build();
    AndroidNotification androidNotification = AndroidNotification.builder().setChannelId(envelope.channel()).setSound("default").build();
    AndroidConfig android = AndroidConfig.builder().setPriority(AndroidConfig.Priority.HIGH)
        .setTtl(envelope.ttlMillis()).setRestrictedPackageName(ANDROID_PACKAGE).setNotification(androidNotification).build();
    return Message.builder().setToken(envelope.token()).setNotification(notification).setAndroidConfig(android)
        .putData("mode", envelope.mode()).build();
  }

  private static boolean valid(String value, int max) {
    return value != null && !value.isBlank() && value.length() <= max && value.chars().noneMatch(Character::isISOControl);
  }
}
