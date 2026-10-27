package com.subwayalert.server.access;

import java.time.Clock;
import java.time.Duration;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.function.LongSupplier;

/** Single-process admission budgets. All admissions are atomic; no lock spans downstream work. */
final class ApiRateLimits {
  private static final ZoneId SEOUL=ZoneId.of("Asia/Seoul");
  private final LongSupplier elapsedNanos;
  private final Clock clock;
  private final Bucket preAuth,live;
  private final Bucket[] perKey,creation;
  private LocalDate liveDate;
  private int liveUsed;

  ApiRateLimits(int keyCount,LongSupplier elapsedNanos,Clock clock) {
    this.elapsedNanos=elapsedNanos;this.clock=clock;
    long now=elapsedNanos.getAsLong();
    preAuth=new Bucket(600,now);live=new Bucket(6,now);
    perKey=new Bucket[keyCount];creation=new Bucket[keyCount];
    for(int i=0;i<keyCount;i++){perKey[i]=new Bucket(60,now);creation[i]=new Bucket(3,now);}
  }

  synchronized long preAuthentication() { return preAuth.acquire(elapsedNanos.getAsLong()); }

  synchronized long authenticated(int key,String method,String path) {
    long now=elapsedNanos.getAsLong();
    long retry=perKey[key].acquire(now);
    if(retry>0)return retry;
    if("POST".equals(method) && ("/api/track".equals(path) || "/api/monitor-sessions".equals(path))) {
      retry=creation[key].acquire(now);
      if(retry>0)return retry;
    }
    // Spring's GET mapping invokes the provider for HEAD too. Apply this to every method on the path.
    if("/api/live/trains".equals(path)) {
      var instant=clock.instant();
      LocalDate today=instant.atZone(SEOUL).toLocalDate();
      if(!today.equals(liveDate)){liveDate=today;liveUsed=0;}
      if(liveUsed>=240) {
        var midnight=today.plusDays(1).atStartOfDay(SEOUL).toInstant();
        return Math.max(1,(long)Math.ceil(Duration.between(instant,midnight).toNanos()/1_000_000_000.0));
      }
      retry=live.acquire(now);
      if(retry>0)return retry;
      liveUsed++;
    }
    return 0;
  }

  private static final class Bucket {
    private final int capacity;
    private double tokens;
    private long updated;
    Bucket(int capacity,long now){this.capacity=capacity;tokens=capacity;updated=now;}
    long acquire(long now) {
      long elapsed=now-updated;
      if(elapsed>0) {
        tokens=Math.min(capacity,tokens+elapsed*(capacity/60_000_000_000.0));
        updated=now;
      }
      if(tokens>=1){tokens--;return 0;}
      return Math.max(1,(long)Math.ceil((1-tokens)*60.0/capacity));
    }
  }
}
