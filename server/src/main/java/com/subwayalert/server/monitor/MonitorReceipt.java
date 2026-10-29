package com.subwayalert.server.monitor;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;

/** Durable identity and outcome only. Never holds a token, station or request body. */
public record MonitorReceipt(
    UUID id,
    String sessionHash,
    String fingerprintHash,
    Instant expiresAt,
    String state,
    String deliveryStatus) {
  private static final Set<String> STATES =
      Set.of("TRACKING", "SAMPLE_MATCHED", "CANCELLED", "EXPIRED");
  private static final Set<String> DELIVERIES =
      Set.of("NONE", "SENDING", "UNKNOWN", "FCM_ACCEPTED", "UNAVAILABLE", "FAILED");

  public MonitorReceipt {
    if (id == null
        || id.version() != 4
        || id.variant() != 2
        || expiresAt == null
        || sessionHash == null
        || !sessionHash.matches("[0-9a-f]{64}")
        || (fingerprintHash != null && !fingerprintHash.matches("[0-9a-f]{64}"))
        || state == null
        || !STATES.contains(state)
        || deliveryStatus == null
        || !DELIVERIES.contains(deliveryStatus))
      throw new IllegalArgumentException("Invalid monitor receipt");
  }

  MonitorReceipt afterRestart(Instant now) {
    String stopped =
        state.equals("TRACKING") ? (now.isBefore(expiresAt) ? "CANCELLED" : "EXPIRED") : state;
    return new MonitorReceipt(
        id,
        sessionHash,
        fingerprintHash,
        expiresAt,
        stopped,
        deliveryStatus.equals("SENDING") ? "UNKNOWN" : deliveryStatus);
  }
}
