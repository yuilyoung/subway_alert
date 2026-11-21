package com.subwayalert.server.domain;

import org.junit.jupiter.api.Test;
import java.time.Clock;
import java.time.Instant;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class TrackingEngineJUnitTest {
  @Test void trackingBehavior() { TrackingEngineTest.main(new String[0]); }

  @Test void capacityIsReclaimedAtExpiryAndOldSessionsBecomeInaccessible() {
    Clock clock=mock(Clock.class);
    Instant now=Instant.parse("2026-10-27T00:00:00Z");
    when(clock.instant()).thenReturn(now);
    var engine=new TrackingEngine(clock);
    var first=engine.start("2","UP","강남","삼성","0202");
    for(int i=1;i<500;i++)engine.start("2","UP","강남","삼성","0202");
    assertThrows(TrackingEngine.CapacityExceeded.class,()->engine.start("2","UP","강남","삼성","0202"));
    when(clock.instant()).thenReturn(now.plusSeconds(7199));
    assertEquals("TRACKING",engine.get(first.id()).status());
    when(clock.instant()).thenReturn(now.plusSeconds(7200));
    assertNull(engine.get(first.id()));
    for(int i=0;i<500;i++)assertNotNull(engine.start("2","UP","강남","삼성","0202"));
  }

  @Test void demoTrainIdentifierMatchesTheMonitorLengthAndControlCharacterLimits() {
    var engine=new TrackingEngine();
    for(String invalid:new String[]{"1".repeat(65),"0202\nother"})
      assertThrows(IllegalArgumentException.class,()->engine.start("2","UP","강남","삼성",invalid));
  }
}
