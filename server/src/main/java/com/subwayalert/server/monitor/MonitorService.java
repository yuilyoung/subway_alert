package com.subwayalert.server.monitor;

import com.subwayalert.server.live.LiveTrainMatcher;
import com.subwayalert.server.live.SeoulTrainProvider;
import com.subwayalert.server.push.NotificationGateway;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/** TEST sessions with optional durable receipts; no live tracking is restored. */
@Service
public final class MonitorService {
  private static final int MAX_SESSIONS = 500,
      MAX_DELIVERIES_PER_POLL = 10,
      MANUAL_TESTS_PER_MINUTE = 30;
  private static final Duration SESSION_LIFETIME = Duration.ofHours(2),
      RETENTION = Duration.ofHours(1);
  private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");
  private final NotificationGateway gateway;
  private final Clock clock;
  private final int dailyLimit;
  private final MonitorReceiptStore store;
  private volatile boolean storageFailed;
  private final Map<UUID, Session> sessions = new HashMap<>();
  private final SecureRandom random = new SecureRandom();
  private final ReentrantLock pollLock = new ReentrantLock();
  private final java.util.ArrayDeque<Instant> manualAttempts = new java.util.ArrayDeque<>();
  private LocalDate budgetDate;
  private int budgetUsed;
  private volatile String pollStatus = "NOT_POLLED";

  public record StartRequest(
      String lineId,
      String trainId,
      String direction,
      String previousStation,
      String destinationStation,
      String fcmToken,
      String mode) {
    @Override
    public String toString() {
      return "StartRequest[redacted]";
    }
  }

  public record StartResponse(
      UUID id, String sessionToken, String status, String mode, Instant expiresAt) {
    @Override
    public String toString() {
      return "StartResponse[id=" + id + ", sessionToken=redacted, status=" + status + "]";
    }
  }

  public record StatusResponse(
      UUID id,
      String status,
      String mode,
      Instant expiresAt,
      String deliveryStatus,
      String pollStatus) {}

  public static final class NotFound extends RuntimeException {}

  public static final class Conflict extends RuntimeException {
    public Conflict(String msg) {
      super(msg);
    }
  }

  public static final class CapacityExceeded extends RuntimeException {}

  public static final class Unavailable extends RuntimeException {
    public Unavailable() {
      super("Monitor storage unavailable");
    }
  }

  private static final class Session {
    final UUID id;
    final byte[] tokenHash, requestFingerprint;
    final String previous, destination;
    final Instant expires;
    final LiveTrainMatcher matcher;
    String fcmToken;
    volatile String status;
    String delivery = "NONE";
    Instant lastManualTest;
    boolean inFlight;

    private Session(
        UUID id,
        byte[] tokenHash,
        byte[] requestFingerprint,
        String previous,
        String destination,
        Instant expires,
        String fcmToken,
        LiveTrainMatcher matcher,
        String status) {
      this.id = id;
      this.tokenHash = tokenHash;
      this.requestFingerprint = requestFingerprint;
      this.previous = previous;
      this.destination = destination;
      this.expires = expires;
      this.fcmToken = fcmToken;
      this.matcher = matcher;
      this.status = status;
    }

    static Session tracking(
        UUID id, byte[] tokenHash, byte[] fingerprint, StartRequest req, Instant now) {
      return new Session(
          id,
          tokenHash,
          fingerprint,
          req.previousStation(),
          req.destinationStation(),
          now.plus(SESSION_LIFETIME).truncatedTo(java.time.temporal.ChronoUnit.MICROS),
          req.fcmToken(),
          new LiveTrainMatcher(
              "2",
              req.trainId(),
              req.direction(),
              req.previousStation(),
              now,
              "SAMPLE",
              false,
              false),
          "TRACKING");
    }

    static Session restored(MonitorReceipt receipt) {
      Session session =
          new Session(
              receipt.id(),
              HexFormat.of().parseHex(receipt.sessionHash()),
              receipt.fingerprintHash() == null
                  ? null
                  : HexFormat.of().parseHex(receipt.fingerprintHash()),
              null,
              null,
              receipt.expiresAt(),
              null,
              null,
              receipt.state());
      session.delivery = receipt.deliveryStatus();
      return session;
    }

    static Session cancelled(UUID id, byte[] tokenHash, Instant now) {
      return new Session(
          id,
          tokenHash,
          null,
          null,
          null,
          now.plus(SESSION_LIFETIME).truncatedTo(java.time.temporal.ChronoUnit.MICROS),
          null,
          null,
          "CANCELLED");
    }
  }

  @Autowired
  public MonitorService(NotificationGateway gateway, MonitorReceiptStore store) {
    this(gateway, Clock.systemUTC(), 600, store);
  }

  public MonitorService(NotificationGateway gateway) {
    this(gateway, Clock.systemUTC(), 600, MonitorReceiptStore.memory());
  }

  MonitorService(NotificationGateway gateway, Clock clock, int dailyLimit) {
    this(gateway, clock, dailyLimit, MonitorReceiptStore.memory());
  }

  MonitorService(
      NotificationGateway gateway, Clock clock, int dailyLimit, MonitorReceiptStore store) {
    if (gateway == null || clock == null || store == null || dailyLimit < 1)
      throw new IllegalArgumentException("Invalid configuration");
    this.gateway = gateway;
    this.clock = clock;
    this.dailyLimit = dailyLimit;
    this.store = store;
    try {
      for (MonitorReceipt receipt : store.restore(clock.instant()))
        sessions.put(receipt.id(), Session.restored(receipt));
    } catch (MonitorReceiptStore.Unavailable e) {
      storageFailed = true;
      throw new Unavailable();
    }
  }

  /** Internal convenience entry point; HTTP registrations always supply their own identity. */
  public StartResponse start(StartRequest req) {
    byte[] bytes = new byte[32];
    random.nextBytes(bytes);
    return start(UUID.randomUUID(), HexFormat.of().formatHex(bytes), req);
  }

  /** Atomic creation/replay within the bounded receipt retention window. */
  public synchronized StartResponse start(UUID id, String secret, StartRequest req) {
    ready();
    validateIdentity(id, secret);
    Instant now = clock.instant();
    prune(now);
    Session existing = sessions.get(id);
    if (existing != null)
      synchronized (existing) {
        if (!MessageDigest.isEqual(existing.tokenHash, digest(secret)))
          throw registrationConflict();
        // Cancel-before-create deliberately has no request body or matcher to recreate.
        if (existing.requestFingerprint != null) {
          byte[] requestedFingerprint;
          try {
            requestedFingerprint = fingerprint(canonical(req));
          } catch (IllegalArgumentException e) {
            throw registrationConflict();
          }
          if (!MessageDigest.isEqual(existing.requestFingerprint, requestedFingerprint))
            throw registrationConflict();
        }
        return startView(existing, secret);
      }
    StartRequest normalized = canonical(req);
    if (sessions.size() >= MAX_SESSIONS) throw new CapacityExceeded();
    Session created =
        Session.tracking(id, digest(secret), fingerprint(normalized), normalized, now);
    persist(created);
    sessions.put(id, created);
    return startView(created, secret);
  }

  public StatusResponse status(UUID id, String secret) {
    Session s = authorized(id, secret);
    synchronized (s) {
      expire(s, clock.instant());
      return view(s);
    }
  }

  /** Takes the store lock before any session lock, just like creation and pruning. */
  public synchronized StatusResponse cancel(UUID id, String secret) {
    ready();
    Instant now = clock.instant();
    prune(now);
    Session s = sessions.get(id);
    if (s == null) {
      validateIdentity(id, secret);
      if (sessions.size() >= MAX_SESSIONS) throw new CapacityExceeded();
      s = Session.cancelled(id, digest(secret), now);
      persist(s);
      sessions.put(id, s);
    } else if (!authorized(s, secret)) throw new NotFound();
    synchronized (s) {
      expire(s, now);
      if (s.status.equals("TRACKING") || s.status.equals("SAMPLE_MATCHED")) {
        s.status = "CANCELLED";
        s.fcmToken = null;
        persist(s);
      }
      return view(s);
    }
  }

  /** Explicitly labelled connectivity test. FCM acceptance is not device receipt. */
  public StatusResponse test(UUID id, String secret) {
    Session s = authorized(id, secret);
    String target;
    synchronized (s) {
      Instant now = clock.instant();
      expire(s, now);
      if (!s.status.equals("TRACKING")) throw new Conflict("Session is not active");
      if (s.inFlight
          || (s.lastManualTest != null && now.isBefore(s.lastManualTest.plusSeconds(30))))
        throw new Conflict("Try again later");
      synchronized (manualAttempts) {
        while (!manualAttempts.isEmpty()
            && !manualAttempts.peekFirst().isAfter(now.minusSeconds(60)))
          manualAttempts.removeFirst();
        if (manualAttempts.size() >= MANUAL_TESTS_PER_MINUTE)
          throw new Conflict("Test rate limit reached");
        manualAttempts.addLast(now);
      }
      s.lastManualTest = now;
      target = claimDelivery(s);
    }
    deliverOutsideLock(s, target);
    synchronized (s) {
      return view(s);
    }
  }

  /** Each sample event is claimed once; actual network delivery runs outside locks. */
  public void process(SeoulTrainProvider.Result result) {
    if (storageFailed) return;
    try {
      ready();
    } catch (Unavailable e) {
      return;
    }
    if (result == null || !"SAMPLE".equals(result.mode()) || result.trains() == null) {
      pollStatus = "SOURCE_BLOCKED";
      return;
    }
    pollStatus = "SAMPLE_PARTIAL";
    java.util.List<Session> snapshot;
    synchronized (this) {
      prune(clock.instant());
      snapshot = java.util.List.copyOf(sessions.values());
    }
    int deliveries = 0;
    for (Session s : snapshot) {
      if (deliveries >= MAX_DELIVERIES_PER_POLL) break;
      String target = null;
      synchronized (s) {
        // Another delivery can be slow; re-read time before checking each candidate.
        Instant now = clock.instant();
        expire(s, now);
        if (!s.status.equals("TRACKING") || s.inFlight) continue;
        for (var train : result.trains()) {
          if (s.matcher.consider("SAMPLE", train, now) == LiveTrainMatcher.Decision.SAMPLE_MATCH) {
            s.status = "SAMPLE_MATCHED";
            target = claimDelivery(s);
            s.fcmToken = null;
            break;
          }
        }
      }
      if (target != null) {
        deliveries++;
        deliverOutsideLock(s, target);
      }
    }
  }

  /**
   * Shares one provider response between all active sessions; limit is process-local per Seoul day.
   */
  public void poll(Supplier<SeoulTrainProvider.Result> fetch) {
    if (storageFailed || !pollLock.tryLock()) return;
    try {
      synchronized (this) {
        try {
          ready();
        } catch (Unavailable e) {
          return;
        }
        Instant now = clock.instant();
        prune(now);
        if (sessions.values().stream()
            .noneMatch(s -> s.status.equals("TRACKING") && now.isBefore(s.expires))) return;
        LocalDate today = now.atZone(SEOUL).toLocalDate();
        if (!today.equals(budgetDate)) {
          budgetDate = today;
          budgetUsed = 0;
        }
        if (budgetUsed >= dailyLimit) {
          pollStatus = "DAILY_LIMIT";
          return;
        }
        ++budgetUsed;
      }
      try {
        process(fetch.get());
      } catch (RuntimeException e) {
        synchronized (this) {
          pollStatus = "PROVIDER_ERROR";
        }
      }
    } finally {
      pollLock.unlock();
    }
  }

  /** Caller holds the individual session lock. */
  private String claimDelivery(Session s) {
    ready();
    s.inFlight = true;
    s.delivery = "SENDING";
    persist(s);
    return s.fcmToken;
  }

  private void deliverOutsideLock(Session s, String target) {
    if (storageFailed) throw new Unavailable();
    NotificationGateway.Result result;
    try {
      result =
          gateway.available()
              ? gateway.send(target, s.previous, s.destination, "TEST")
              : NotificationGateway.Result.UNAVAILABLE;
    } catch (RuntimeException e) {
      result = NotificationGateway.Result.FAILED;
    }
    synchronized (s) {
      s.delivery =
          result == null
              ? "FAILED"
              : switch (result) {
                case ACCEPTED -> "FCM_ACCEPTED";
                case UNAVAILABLE -> "UNAVAILABLE";
                case FAILED -> "FAILED";
              };
      s.inFlight = false;
      persist(s);
    }
  }

  private Session authorized(UUID id, String secret) {
    ready();
    Session s;
    synchronized (this) {
      s = sessions.get(id);
    }
    if (s == null || !authorized(s, secret)) throw new NotFound();
    return s;
  }

  private static boolean authorized(Session s, String secret) {
    return secret != null
        && secret.length() <= 128
        && MessageDigest.isEqual(s.tokenHash, digest(secret));
  }

  private StartResponse startView(Session s, String secret) {
    ensureNotFailed();
    return new StartResponse(s.id, secret, s.status, "TEST", s.expires);
  }

  private static Conflict registrationConflict() {
    return new Conflict("Registration conflicts with an existing session");
  }

  private static void validateIdentity(UUID id, String secret) {
    if (id == null
        || id.version() != 4
        || id.variant() != 2
        || secret == null
        || !secret.matches("[0-9a-f]{64}"))
      throw new IllegalArgumentException("Invalid registration identity");
  }

  private static StartRequest canonical(StartRequest req) {
    if (req == null
        || !"TEST".equals(req.mode())
        || !"2".equals(req.lineId())
        || !("INNER".equals(req.direction()) || "OUTER".equals(req.direction()))
        || !clean(req.trainId(), 64)
        || !clean(req.previousStation(), 64)
        || !clean(req.destinationStation(), 64)
        || !clean(req.fcmToken(), 4096)
        || req.previousStation().strip().equals(req.destinationStation().strip()))
      throw new IllegalArgumentException("Only an explicitly configured TEST session is supported");
    return new StartRequest(
        req.lineId(),
        req.trainId().strip(),
        req.direction(),
        req.previousStation().strip(),
        req.destinationStation().strip(),
        req.fcmToken(),
        req.mode());
  }

  private static byte[] fingerprint(StartRequest req) {
    // All fields exclude control characters, making this separator unambiguous. The FCM token is
    // exact.
    return digest(
        String.join(
            "\u0000",
            req.lineId(),
            req.trainId(),
            req.direction(),
            req.previousStation(),
            req.destinationStation(),
            req.fcmToken(),
            req.mode()));
  }

  private StatusResponse view(Session s) {
    ensureNotFailed();
    return new StatusResponse(s.id, s.status, "TEST", s.expires, s.delivery, pollStatus);
  }

  private void prune(Instant now) {
    for (Session s : sessions.values())
      synchronized (s) {
        expire(s, now);
      }
    var iterator = sessions.values().iterator();
    while (iterator.hasNext()) {
      Session s = iterator.next();
      if (!now.isBefore(s.expires.plus(RETENTION))) {
        try {
          store.delete(s.id);
        } catch (MonitorReceiptStore.Unavailable e) {
          storageFailed = true;
          throw new Unavailable();
        }
        iterator.remove();
      }
    }
  }

  private void expire(Session s, Instant now) {
    if (s.status.equals("TRACKING") && !now.isBefore(s.expires)) {
      s.status = "EXPIRED";
      s.fcmToken = null;
      persist(s);
    }
  }

  private void ready() {
    ensureNotFailed();
    try {
      store.checkAvailable();
    } catch (MonitorReceiptStore.Unavailable e) {
      storageFailed = true;
      throw new Unavailable();
    }
  }

  private void ensureNotFailed() {
    if (storageFailed) throw new Unavailable();
  }

  private void persist(Session s) {
    if (storageFailed) throw new Unavailable();
    try {
      store.save(
          new MonitorReceipt(
              s.id,
              HexFormat.of().formatHex(s.tokenHash),
              s.requestFingerprint == null ? null : HexFormat.of().formatHex(s.requestFingerprint),
              s.expires,
              s.status,
              s.delivery));
    } catch (MonitorReceiptStore.Unavailable e) {
      storageFailed = true;
      throw new Unavailable();
    }
  }

  private static boolean clean(String s, int limit) {
    return s != null
        && !s.isBlank()
        && s.length() <= limit
        && s.chars().noneMatch(Character::isISOControl);
  }

  private static byte[] digest(String s) {
    try {
      return MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8));
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException(e);
    }
  }
}
