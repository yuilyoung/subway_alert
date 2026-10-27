package com.subwayalert.server.live;

import java.time.Instant;

/**
 * Single-use observation matcher. A match is not proof that the passenger boarded
 * this train or that the caller supplied the correct prior station and route.
 * Upstream times are currently interpreted in Asia/Seoul, an unverified assumption.
 * This component does not send notifications or fetch data.
 */
public final class LiveTrainMatcher {
  public enum Decision { IGNORE, SAMPLE_MATCH, LIVE_MATCH }

  private final String lineId;
  private final String trainId;
  private final String direction;
  private final String previousStation;
  private final Instant sessionStart;
  private final String dataMode;
  private final boolean routeVerified;
  private final boolean timezoneVerified;
  private boolean consumed;

  /** Verification flags must only be true after independent validation, not just user input. */
  public LiveTrainMatcher(String lineId, String trainId, String direction, String previousStation,
                          Instant sessionStart, String dataMode, boolean routeVerified, boolean timezoneVerified) {
    if (blank(lineId) || blank(trainId) || blank(previousStation) || sessionStart == null
        || !("INNER".equals(direction) || "OUTER".equals(direction))
        || !("LIVE".equals(dataMode) || "SAMPLE".equals(dataMode))) {
      throw new IllegalArgumentException("An explicit train, line, direction, prior station, start time and source mode are required");
    }
    this.lineId = lineId.strip();
    this.trainId = trainId.strip();
    this.direction = direction;
    this.previousStation = previousStation.strip();
    this.sessionStart = sessionStart;
    this.dataMode = dataMode;
    this.routeVerified = routeVerified;
    this.timezoneVerified = timezoneVerified;
  }

  /** Match once, distinguishing sample data from live so a caller can never conflate them. */
  public synchronized Decision consider(String mode, SeoulTrainProvider.Train train, Instant now) {
    if (consumed || !dataMode.equals(mode) || ("LIVE".equals(mode) && (!routeVerified || !timezoneVerified)) || train == null || now == null
        || train.observedAt() == null || now.isBefore(sessionStart) || !train.fresh() || train.express()) return Decision.IGNORE;
    Instant observed = train.observedAt();
    if (observed.isBefore(sessionStart) || observed.isBefore(now.minusSeconds(60))
        || observed.isAfter(now.plusSeconds(5)) || !lineId.equals(train.lineId())
        || !trainId.equals(train.trainId()) || !direction.equals(train.direction())
        || !previousStation.equals(train.station()) || !"DEPARTED".equals(train.state())) return Decision.IGNORE;
    consumed = true;
    return "SAMPLE".equals(dataMode) ? Decision.SAMPLE_MATCH : Decision.LIVE_MATCH;
  }
  private static boolean blank(String value) { return value == null || value.isBlank(); }
}
