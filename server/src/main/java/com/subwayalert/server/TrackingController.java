package com.subwayalert.server;

import com.subwayalert.server.domain.TrackingEngine;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api")
public final class TrackingController {
  private final TrackingEngine engine = new TrackingEngine();
  private final Map<UUID, byte[]> tokenHashes = new ConcurrentHashMap<>();
  private final SecureRandom random = new SecureRandom();
  public record TrackRequest(String lineId, String direction, String boardingStation, String destinationStation, String trainId) { }
  public record StartResponse(UUID id, String status, String previousStation, String sessionToken, String dataMode) { }
  public record DemoEvent(String lineId, String direction, String trainId, String station, String state, Instant observedAt) { }

  @GetMapping("/health") public Map<String, Object> health() { return Map.of("status", "ok", "mode", "DEMO", "pushEnabled", false); }
  @GetMapping("/lines") public List<Map<String, String>> lines() { return List.of(Map.of("id", "2", "name", "2호선 샘플", "dataMode", "DEMO")); }
  @GetMapping("/stations/{lineId}") public List<String> stations(@PathVariable String lineId) {
    if (!"2".equals(lineId)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "데모 노선이 아닙니다.");
    return TrackingEngine.DEMO_STATIONS;
  }
  @PostMapping("/track") public StartResponse start(@RequestBody TrackRequest request) {
    try {
      var s = engine.start(request.lineId(), request.direction(), request.boardingStation(), request.destinationStation(), request.trainId());
      byte[] secret = new byte[32]; random.nextBytes(secret);
      String token = Base64.getUrlEncoder().withoutPadding().encodeToString(secret);
      tokenHashes.put(s.id(), digest(token));
      return new StartResponse(s.id(), s.status(), s.previousStation(), token, "DEMO");
    } catch (IllegalArgumentException ex) { throw new ResponseStatusException(HttpStatus.BAD_REQUEST, ex.getMessage()); }
  }
  @GetMapping("/track/{id}/status") public TrackingEngine.Session status(@PathVariable UUID id, @RequestHeader(value="X-Session-Token", required=false) String token) {
    authorize(id, token); return engine.get(id);
  }
  @DeleteMapping("/track/{id}") public Map<String, String> cancel(@PathVariable UUID id, @RequestHeader(value="X-Session-Token", required=false) String token) {
    authorize(id, token);
    engine.cancel(id);
    return Map.of("status", engine.get(id).status());
  }
  /** Manually advances a demo session; it does not call TOPIS or send an Android notification. */
  @PostMapping("/track/{id}/demo-event") public Map<String, Object> demo(@PathVariable UUID id, @RequestHeader(value="X-Session-Token", required=false) String token, @RequestBody DemoEvent event) {
    authorize(id, token);
    boolean matched = engine.accept(id, new TrackingEngine.Position(event.lineId(), event.direction(), event.trainId(), event.station(), event.state(), event.observedAt()), Instant.now());
    return Map.of("matched", matched, "status", engine.get(id).status(), "dataMode", "DEMO");
  }
  private void authorize(UUID id, String token) {
    byte[] expected = tokenHashes.get(id);
    if (expected == null || token == null || !MessageDigest.isEqual(expected, digest(token))) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "세션을 찾을 수 없습니다.");
  }
  private byte[] digest(String value) {
    try { return MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)); }
    catch (java.security.NoSuchAlgorithmException ex) { throw new IllegalStateException(ex); }
  }
}
