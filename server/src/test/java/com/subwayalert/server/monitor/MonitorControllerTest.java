package com.subwayalert.server.monitor;

import tools.jackson.databind.ObjectMapper;
import com.subwayalert.server.access.ApiAccessFilter;
import com.subwayalert.server.live.SeoulTrainProvider;
import com.subwayalert.server.push.NotificationGateway;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class MonitorControllerTest {
 @Test void testCooldownUsesRoundedUpRetryAfterAndAllowsExactDeadline() throws Exception {
  var clock=new MonitorServiceTest.FakeClock();
  var gateway=new MonitorServiceTest.Gateway();
  var service=new MonitorService(gateway,clock,600);
  var mvc=MockMvcBuilders.standaloneSetup(new MonitorController(service)).build();
  var session=service.start(MonitorServiceTest.request());
  var send=post("/api/monitor-sessions/{id}/test",session.id()).header("X-Session-Token",session.sessionToken());
  mvc.perform(send).andExpect(status().isOk()).andExpect(jsonPath("$.deliveryAcceptedAt").value(clock.instant().toString()));
  clock.current=clock.current.plusMillis(29_001);
  mvc.perform(send).andExpect(status().isTooManyRequests()).andExpect(header().string("Retry-After","1"))
      .andExpect(jsonPath("$.error").value("API_RATE_LIMITED"));
  clock.current=clock.current.plusMillis(999);
  mvc.perform(send).andExpect(status().isOk());
  service.cancel(session.id(),session.sessionToken());
  mvc.perform(send).andExpect(status().isConflict()).andExpect(header().doesNotExist("Retry-After"));
  org.junit.jupiter.api.Assertions.assertEquals(2,gateway.calls.get());
 }
 @Test void acceptanceTimeSurvivesStatusReadsAndClearsOnTheNextFailedAttempt() throws Exception {
  var clock=new MonitorServiceTest.FakeClock();
  var gateway=new MonitorServiceTest.Gateway();
  var service=new MonitorService(gateway,clock,600);
  var mvc=MockMvcBuilders.standaloneSetup(new MonitorController(service)).build();
  var session=service.start(MonitorServiceTest.request());
  var send=post("/api/monitor-sessions/{id}/test",session.id()).header("X-Session-Token",session.sessionToken());
  var lookup=get("/api/monitor-sessions/{id}",session.id()).header("X-Session-Token",session.sessionToken());
  String accepted=clock.instant().toString();
  mvc.perform(lookup).andExpect(jsonPath("$.deliveryAcceptedAt").doesNotExist());
  mvc.perform(send).andExpect(jsonPath("$.deliveryAcceptedAt").value(accepted));
  clock.advance(30);
  mvc.perform(lookup).andExpect(jsonPath("$.deliveryAcceptedAt").value(accepted));
  gateway.result=NotificationGateway.Result.FAILED;
  mvc.perform(send).andExpect(jsonPath("$.deliveryStatus").value("FAILED"))
      .andExpect(jsonPath("$.deliveryAcceptedAt").doesNotExist());
  clock.advance(30);
  gateway.result=NotificationGateway.Result.UNAVAILABLE;
  mvc.perform(send).andExpect(jsonPath("$.deliveryStatus").value("UNAVAILABLE"))
      .andExpect(jsonPath("$.deliveryAcceptedAt").doesNotExist());
 }
 @Test void sharedManualBudgetReportsTheLongerWaitAndRefillsAtOneMinute() throws Exception {
  var clock=new MonitorServiceTest.FakeClock();
  var gateway=new MonitorServiceTest.Gateway();
  var service=new MonitorService(gateway,clock,600);
  var mvc=MockMvcBuilders.standaloneSetup(new MonitorController(service)).build();
  var session=service.start(MonitorServiceTest.request());
  service.test(session.id(),session.sessionToken());
  for(int i=1;i<30;i++){
   var other=service.start(MonitorServiceTest.request());
   service.test(other.id(),other.sessionToken());
  }
  var send=post("/api/monitor-sessions/{id}/test",session.id()).header("X-Session-Token",session.sessionToken());
  clock.current=clock.current.plusMillis(200);
  mvc.perform(send).andExpect(status().isTooManyRequests()).andExpect(header().string("Retry-After","60"))
      .andExpect(jsonPath("$.error").value("API_RATE_LIMITED"));
  clock.current=clock.current.plusMillis(59_799);
  mvc.perform(send).andExpect(status().isTooManyRequests()).andExpect(header().string("Retry-After","1"));
  clock.current=clock.current.plusMillis(1);
  mvc.perform(send).andExpect(status().isOk());
  org.junit.jupiter.api.Assertions.assertEquals(31,gateway.calls.get());
 }
 @Test void fakeSampleProviderMatchesOneSessionAndStatusReportsTestDelivery() throws Exception {
  var sends=new java.util.concurrent.atomic.AtomicInteger();
  NotificationGateway gateway=new NotificationGateway(){public boolean available(){return true;}public Result send(String t,String p,String d,String m){sends.incrementAndGet();return Result.ACCEPTED;}};
  Instant now=Instant.parse("2026-10-27T12:00:00Z");
  var service=new MonitorService(gateway,Clock.fixed(now,ZoneOffset.UTC),600);
  var mvc=MockMvcBuilders.standaloneSetup(new MonitorController(service)).addFilters(new ApiAccessFilter("abcdefghijklmnopqrstuvwxyzABCDEF")).defaultRequest(get("/").header("Authorization","Bearer abcdefghijklmnopqrstuvwxyzABCDEF")).build();
  String body="{\"lineId\":\"2\",\"trainId\":\"0202\",\"direction\":\"INNER\",\"previousStation\":\"선릉\",\"destinationStation\":\"삼성\",\"fcmToken\":\"test-token\",\"mode\":\"TEST\"}";
  var response=mvc.perform(post("/api/monitor-sessions").header("Idempotency-Key",java.util.UUID.randomUUID().toString()).header("X-Session-Token","a".repeat(64)).contentType(MediaType.APPLICATION_JSON).content(body)).andExpect(status().isOk()).andReturn();
  var json=new ObjectMapper().readTree(response.getResponse().getContentAsString());String id=json.path("id").asText(), secret=json.path("sessionToken").asText();
  var train=new SeoulTrainProvider.Train("2","선릉","0202","INNER","DEPARTED",now,false,true);
  service.poll(()->new SeoulTrainProvider.Result("SAMPLE",List.of(train),"sample"));
  mvc.perform(get("/api/monitor-sessions/"+id).header("X-Session-Token",secret)).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("SAMPLE_MATCHED")).andExpect(jsonPath("$.deliveryStatus").value("FCM_ACCEPTED"));
  org.junit.jupiter.api.Assertions.assertEquals(1,sends.get());
 }
 @Test void apiRequiresSecretAndNeverReturnsItOrFcmTokenAfterCreation() throws Exception {
  NotificationGateway gateway=new NotificationGateway(){public boolean available(){return true;}public Result send(String t,String p,String d,String m){return Result.ACCEPTED;}};
  var service=new MonitorService(gateway,Clock.fixed(Instant.parse("2026-10-27T12:00:00Z"),ZoneOffset.UTC),600);
  var mvc=MockMvcBuilders.standaloneSetup(new MonitorController(service)).addFilters(new ApiAccessFilter("abcdefghijklmnopqrstuvwxyzABCDEF")).defaultRequest(get("/").header("Authorization","Bearer abcdefghijklmnopqrstuvwxyzABCDEF")).build();
  String request="{\"lineId\":\"2\",\"trainId\":\"0202\",\"direction\":\"INNER\",\"previousStation\":\"선릉\",\"destinationStation\":\"삼성\",\"fcmToken\":\"sensitive-token\",\"mode\":\"TEST\"}";
  var start=mvc.perform(post("/api/monitor-sessions").header("Idempotency-Key",java.util.UUID.randomUUID().toString()).header("X-Session-Token","a".repeat(64)).contentType(MediaType.APPLICATION_JSON).content(request)).andExpect(status().isOk()).andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON)).andExpect(jsonPath("$.sessionToken").isNotEmpty()).andReturn();
  var json=new ObjectMapper().readTree(start.getResponse().getContentAsString());String id=json.path("id").asText(),secret=json.path("sessionToken").asText();
  mvc.perform(get("/api/monitor-sessions/"+id)).andExpect(status().isNotFound());
  mvc.perform(get("/api/monitor-sessions/"+id).header("X-Session-Token","wrong")).andExpect(status().isNotFound());
  mvc.perform(get("/api/monitor-sessions/"+id).header("X-Session-Token",secret)).andExpect(status().isOk()).andExpect(jsonPath("$.sessionToken").doesNotExist()).andExpect(jsonPath("$.fcmToken").doesNotExist());
  mvc.perform(post("/api/monitor-sessions/"+id+"/test").header("X-Session-Token",secret)).andExpect(status().isOk()).andExpect(jsonPath("$.deliveryStatus").value("FCM_ACCEPTED")).andExpect(jsonPath("$.fcmToken").doesNotExist());
  mvc.perform(delete("/api/monitor-sessions/"+id).header("X-Session-Token",secret)).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("CANCELLED"));
  mvc.perform(post("/api/monitor-sessions").header("Idempotency-Key",java.util.UUID.randomUUID().toString()).header("X-Session-Token","a".repeat(64)).contentType(MediaType.APPLICATION_JSON).content(request.replace("TEST","LIVE"))).andExpect(status().isBadRequest());
 }
}
