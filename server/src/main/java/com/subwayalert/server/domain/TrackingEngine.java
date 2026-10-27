package com.subwayalert.server.domain;

import java.time.Instant;
import java.time.Clock;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/** Demo-only, in-memory tracking logic. Input positions are not a real provider. */
public final class TrackingEngine {
  public static final List<String> DEMO_STATIONS = List.of("강남", "역삼", "선릉", "삼성");
  private final Map<UUID, Session> sessions = new ConcurrentHashMap<>();
  private final Clock clock;
  public TrackingEngine() { this(Clock.systemUTC()); }
  public TrackingEngine(Clock clock) { this.clock = java.util.Objects.requireNonNull(clock); }
  public record Position(String lineId, String direction, String trainId, String station, String state, Instant observedAt) { }
  public record Session(UUID id, String lineId, String direction, String trainId, String boardingStation,
                        String destinationStation, String previousStation, String status, Instant createdAt) { }

  public synchronized Session start(String line, String direction, String boarding, String destination, String trainId) {
    if (!"2".equals(line) || !("UP".equals(direction) || "DOWN".equals(direction)) || trainId == null || trainId.isBlank())
      throw new IllegalArgumentException("데모 2호선, 방향, 탑승 열차 번호를 입력하세요.");
    if (boarding == null || destination == null) throw new IllegalArgumentException("출발역과 도착역을 입력하세요.");
    int from = DEMO_STATIONS.indexOf(boarding), to = DEMO_STATIONS.indexOf(destination);
    if (from < 0 || to < 0 || from == to || ("UP".equals(direction) ? from > to : from < to))
      throw new IllegalArgumentException("샘플 역과 이동 방향을 확인하세요.");
    String previous = DEMO_STATIONS.get(to + ("UP".equals(direction) ? -1 : 1));
    Session s = new Session(UUID.randomUUID(), line, direction, trainId.strip(), boarding, destination, previous, "TRACKING", clock.instant());
    sessions.put(s.id(), s);
    return s;
  }
  public Session get(UUID id) { return sessions.get(id); }
  public synchronized boolean cancel(UUID id) {
    Session s = sessions.get(id);
    if (s == null || !s.status().equals("TRACKING")) return false;
    sessions.put(id, withStatus(s, "CANCELLED"));
    return true;
  }
  public synchronized boolean accept(UUID id, Position p, Instant now) {
    Session s = sessions.get(id);
    if (s == null || p == null || now == null || p.observedAt() == null || !"TRACKING".equals(s.status())) return false;
    if (p.observedAt().isBefore(s.createdAt())) return false;
    if (p.observedAt().isBefore(now.minusSeconds(60)) || p.observedAt().isAfter(now.plusSeconds(5))) return false;
    if (!s.lineId().equals(p.lineId()) || !s.direction().equals(p.direction()) || !s.trainId().equals(p.trainId()) ||
        !s.previousStation().equals(p.station()) || !"DEPARTED".equals(p.state())) return false;
    sessions.put(id, withStatus(s, "ALERTED"));
    return true;
  }
  private static Session withStatus(Session s, String status) {
    return new Session(s.id(), s.lineId(), s.direction(), s.trainId(), s.boardingStation(), s.destinationStation(), s.previousStation(), status, s.createdAt());
  }
}
