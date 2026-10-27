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
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/** In-memory TEST sessions only; neither the sample route nor provider times are verified. */
@Service
public final class MonitorService {
  private static final int MAX_SESSIONS=500, MAX_DELIVERIES_PER_POLL=10, MANUAL_TESTS_PER_MINUTE=30;
  private static final Duration SESSION_LIFETIME=Duration.ofHours(2), RETENTION=Duration.ofHours(1);
  private static final ZoneId SEOUL=ZoneId.of("Asia/Seoul");
  private final NotificationGateway gateway;
  private final Clock clock;
  private final int dailyLimit;
  private final Map<UUID, Session> sessions=new HashMap<>();
  private final SecureRandom random=new SecureRandom();
  private final ReentrantLock pollLock=new ReentrantLock();
  private final java.util.ArrayDeque<Instant> manualAttempts=new java.util.ArrayDeque<>();
  private LocalDate budgetDate;
  private int budgetUsed;
  private volatile String pollStatus="NOT_POLLED";

  public record StartRequest(String lineId,String trainId,String direction,String previousStation,
                             String destinationStation,String fcmToken,String mode) {
    @Override public String toString(){return "StartRequest[redacted]";}
  }
  public record StartResponse(UUID id,String sessionToken,String status,String mode,Instant expiresAt) {
    @Override public String toString(){return "StartResponse[id="+id+", sessionToken=redacted, status="+status+"]";}
  }
  public record StatusResponse(UUID id,String status,String mode,Instant expiresAt,
                               String deliveryStatus,String pollStatus) { }
  public static final class NotFound extends RuntimeException { }
  public static final class Conflict extends RuntimeException { public Conflict(String msg){super(msg);} }

  private static final class Session {
    final UUID id; final byte[] tokenHash; final String previous,destination; final Instant expires;
    final LiveTrainMatcher matcher;
    String fcmToken; volatile String status="TRACKING"; String delivery="NONE";
    Instant lastManualTest; boolean inFlight;
    Session(UUID id,byte[] tokenHash,String previous,String destination,Instant expires,
            String fcmToken,LiveTrainMatcher matcher) {
      this.id=id;this.tokenHash=tokenHash;this.previous=previous;this.destination=destination;
      this.expires=expires;this.fcmToken=fcmToken;this.matcher=matcher;
    }
  }

  @Autowired
  public MonitorService(NotificationGateway gateway){this(gateway,Clock.systemUTC(),600);}
  MonitorService(NotificationGateway gateway,Clock clock,int dailyLimit){
    if(gateway==null||clock==null||dailyLimit<1)throw new IllegalArgumentException("Invalid configuration");
    this.gateway=gateway;this.clock=clock;this.dailyLimit=dailyLimit;
  }

  public synchronized StartResponse start(StartRequest req) {
    Instant now=clock.instant(); prune(now);
    if(req==null||!"TEST".equals(req.mode())||!"2".equals(req.lineId())||
       !("INNER".equals(req.direction())||"OUTER".equals(req.direction()))||
       !clean(req.trainId(),64)||!clean(req.previousStation(),64)||!clean(req.destinationStation(),64)||
       !clean(req.fcmToken(),4096)||req.previousStation().strip().equals(req.destinationStation().strip()))
      throw new IllegalArgumentException("Only an explicitly configured TEST session is supported");
    if(sessions.size()>=MAX_SESSIONS)throw new Conflict("Session capacity reached");
    String train=req.trainId().strip(), previous=req.previousStation().strip(), destination=req.destinationStation().strip();
    UUID id=UUID.randomUUID();byte[] bytes=new byte[32];random.nextBytes(bytes);
    String secret=Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    Instant expires=now.plus(SESSION_LIFETIME);
    LiveTrainMatcher matcher=new LiveTrainMatcher("2",train,req.direction(),previous,now,"SAMPLE",false,false);
    sessions.put(id,new Session(id,digest(secret),previous,destination,expires,req.fcmToken(),matcher));
    return new StartResponse(id,secret,"TRACKING","TEST",expires);
  }

  public StatusResponse status(UUID id,String secret){
    Session s=authorized(id,secret);synchronized(s){expire(s,clock.instant());return view(s);}
  }
  public StatusResponse cancel(UUID id,String secret){
    Session s=authorized(id,secret);synchronized(s){
      expire(s,clock.instant());
      if(s.status.equals("TRACKING") || s.status.equals("SAMPLE_MATCHED")){s.status="CANCELLED";s.fcmToken=null;}
      return view(s);
    }
  }
  /** Explicitly labelled connectivity test. FCM acceptance is not device receipt. */
  public StatusResponse test(UUID id,String secret){
    Session s=authorized(id,secret);String target;
    synchronized(s){
      Instant now=clock.instant();expire(s,now);
      if(!s.status.equals("TRACKING"))throw new Conflict("Session is not active");
      if(s.inFlight || (s.lastManualTest!=null && now.isBefore(s.lastManualTest.plusSeconds(30))))throw new Conflict("Try again later");
      synchronized(manualAttempts){
        while(!manualAttempts.isEmpty()&&!manualAttempts.peekFirst().isAfter(now.minusSeconds(60)))manualAttempts.removeFirst();
        if(manualAttempts.size()>=MANUAL_TESTS_PER_MINUTE)throw new Conflict("Test rate limit reached");
        manualAttempts.addLast(now);
      }
      s.lastManualTest=now;target=claimDelivery(s);
    }
    deliverOutsideLock(s,target);
    synchronized(s){return view(s);}
  }

  /** Each sample event is claimed once; actual network delivery runs outside locks. */
  public void process(SeoulTrainProvider.Result result){
    if(result==null || !"SAMPLE".equals(result.mode()) || result.trains()==null){pollStatus="SOURCE_BLOCKED";return;}
    pollStatus="SAMPLE_PARTIAL";
    java.util.List<Session> snapshot;
    synchronized(this){prune(clock.instant());snapshot=java.util.List.copyOf(sessions.values());}
    int deliveries=0;
    for(Session s:snapshot){
      if(deliveries>=MAX_DELIVERIES_PER_POLL)break;
      String target=null;
      synchronized(s){
        // Another delivery can be slow; re-read time before checking each candidate.
        Instant now=clock.instant();expire(s,now);
        if(!s.status.equals("TRACKING") || s.inFlight)continue;
        for(var train:result.trains()){
          if(s.matcher.consider("SAMPLE",train,now)==LiveTrainMatcher.Decision.SAMPLE_MATCH){
            target=claimDelivery(s);s.status="SAMPLE_MATCHED";s.fcmToken=null;break;
          }
        }
      }
      if(target!=null){deliveries++;deliverOutsideLock(s,target);}
    }
  }

  /** Shares one provider response between all active sessions; limit is process-local per Seoul day. */
  public void poll(Supplier<SeoulTrainProvider.Result> fetch){
    if(!pollLock.tryLock())return;
    try{
      synchronized(this){
        Instant now=clock.instant();prune(now);
        if(sessions.values().stream().noneMatch(s->s.status.equals("TRACKING") && now.isBefore(s.expires)))return;
        LocalDate today=now.atZone(SEOUL).toLocalDate();
        if(!today.equals(budgetDate)){budgetDate=today;budgetUsed=0;}
        if(budgetUsed>=dailyLimit){pollStatus="DAILY_LIMIT";return;}
        ++budgetUsed;
      }
      try{process(fetch.get());}
      catch(RuntimeException e){synchronized(this){pollStatus="PROVIDER_ERROR";}}
    }finally{pollLock.unlock();}
  }
  /** Caller holds the individual session lock. */
  private static String claimDelivery(Session s){s.inFlight=true;s.delivery="SENDING";return s.fcmToken;}
  private void deliverOutsideLock(Session s,String target){
    NotificationGateway.Result result;
    try{result=gateway.available()?gateway.send(target,s.previous,s.destination,"TEST"):NotificationGateway.Result.UNAVAILABLE;}
    catch(RuntimeException e){result=NotificationGateway.Result.FAILED;}
    synchronized(s){
      s.delivery=result==null?"FAILED":switch(result){case ACCEPTED->"FCM_ACCEPTED";case UNAVAILABLE->"UNAVAILABLE";case FAILED->"FAILED";};
      s.inFlight=false;
    }
  }
  private Session authorized(UUID id,String secret){
    Session s; synchronized(this){s=sessions.get(id);}
    if(s==null||secret==null||secret.length()>128||!MessageDigest.isEqual(s.tokenHash,digest(secret)))throw new NotFound();
    return s;
  }
  private StatusResponse view(Session s){return new StatusResponse(s.id,s.status,"TEST",s.expires,s.delivery,pollStatus);}
  private void prune(Instant now){
    for(Session s:sessions.values())synchronized(s){expire(s,now);}
    sessions.values().removeIf(s->!now.isBefore(s.expires.plus(RETENTION)));
  }
  private static void expire(Session s,Instant now){if(s.status.equals("TRACKING")&&!now.isBefore(s.expires)){s.status="EXPIRED";s.fcmToken=null;}}
  private static boolean clean(String s,int limit){return s!=null&&!s.isBlank()&&s.length()<=limit&&s.chars().noneMatch(Character::isISOControl);}
  private static byte[] digest(String s){try{return MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8));}catch(NoSuchAlgorithmException e){throw new IllegalStateException(e);}}
}
