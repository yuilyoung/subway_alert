package com.subwayalert.server.domain;

import java.time.Instant;
import java.time.Clock;
import java.time.Duration;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Demo-only, in-memory tracking logic. Input positions are not a real provider. */
public final class TrackingEngine {
  public static final List<String> DEMO_STATIONS = List.of("강남", "역삼", "선릉", "삼성");
  private static final int MAX_SESSIONS = 500;
  private static final Duration LIFETIME = Duration.ofHours(2);
  private final Map<UUID, Entry> sessions = new HashMap<>();
  private record Entry(Session session, byte[] tokenHash) {
    boolean expired(Instant now) { return !now.isBefore(session.createdAt().plus(LIFETIME)); }
    Entry withStatus(String status) { return new Entry(TrackingEngine.withStatus(session, status), tokenHash); }
  }
  public static final class CapacityExceeded extends IllegalStateException { }
  private final Clock clock;
  public TrackingEngine() { this(Clock.systemUTC()); }
  public TrackingEngine(Clock clock) { this.clock = java.util.Objects.requireNonNull(clock); }
  public record Position(String lineId, String direction, String trainId, String station, String state, Instant observedAt) { }
  public record Session(UUID id, String lineId, String direction, String trainId, String boardingStation,
                        String destinationStation, String previousStation, String status, Instant createdAt) { }

  public Session start(String line, String direction, String boarding, String destination, String trainId) {
    return start(line, direction, boarding, destination, trainId, null);
  }
  public synchronized Session start(String line, String direction, String boarding, String destination, String trainId, byte[] tokenHash) {
    if (!"2".equals(line) || !("UP".equals(direction) || "DOWN".equals(direction)) || trainId == null || trainId.isBlank()
        || trainId.length() > 64 || trainId.chars().anyMatch(Character::isISOControl))
      throw new IllegalArgumentException("데모 2호선, 방향, 탑승 열차 번호를 입력하세요.");
    if (boarding == null || destination == null) throw new IllegalArgumentException("출발역과 도착역을 입력하세요.");
    int from = DEMO_STATIONS.indexOf(boarding), to = DEMO_STATIONS.indexOf(destination);
    if (from < 0 || to < 0 || from == to || ("UP".equals(direction) ? from > to : from < to))
      throw new IllegalArgumentException("샘플 역과 이동 방향을 확인하세요.");
    String previous = DEMO_STATIONS.get(to + ("UP".equals(direction) ? -1 : 1));
    Instant now = clock.instant();
    sessions.values().removeIf(entry -> entry.expired(now));
    if (sessions.size() >= MAX_SESSIONS) throw new CapacityExceeded();
    Session s = new Session(UUID.randomUUID(), line, direction, trainId.strip(), boarding, destination, previous, "TRACKING", now);
    sessions.put(s.id(), new Entry(s, tokenHash == null ? null : tokenHash.clone()));
    return s;
  }
  private Entry retained(UUID id) {
    Entry entry = sessions.get(id);
    if (entry != null && entry.expired(clock.instant())) {
      sessions.remove(id);
      return null;
    }
    return entry;
  }
  public synchronized Session get(UUID id) {
    Entry entry = retained(id);
    return entry == null ? null : entry.session();
  }
  public synchronized Session owned(UUID id, byte[] tokenHash) {
    Entry entry = retained(id);
    return entry != null && entry.tokenHash() != null && tokenHash != null && MessageDigest.isEqual(entry.tokenHash(), tokenHash)
        ? entry.session() : null;
  }
  public synchronized boolean cancel(UUID id) {
    Entry entry = retained(id);
    if (entry == null || !entry.session().status().equals("TRACKING")) return false;
    sessions.put(id, entry.withStatus("CANCELLED"));
    return true;
  }
  public synchronized boolean accept(UUID id, Position p, Instant now) {
    Entry entry = retained(id);
    if (entry == null || p == null || now == null || p.observedAt() == null) return false;
    Session s = entry.session();
    if (!"TRACKING".equals(s.status())) return false;
    if (p.observedAt().isBefore(s.createdAt())) return false;
    if (p.observedAt().isBefore(now.minusSeconds(60)) || p.observedAt().isAfter(now.plusSeconds(5))) return false;
    if (!s.lineId().equals(p.lineId()) || !s.direction().equals(p.direction()) || !s.trainId().equals(p.trainId()) ||
        !s.previousStation().equals(p.station()) || !"DEPARTED".equals(p.state())) return false;
    sessions.put(id, entry.withStatus("ALERTED"));
    return true;
  }
  private static Session withStatus(Session s, String status) {
    return new Session(s.id(), s.lineId(), s.direction(), s.trainId(), s.boardingStation(), s.destinationStation(), s.previousStation(), status, s.createdAt());
  }
}
