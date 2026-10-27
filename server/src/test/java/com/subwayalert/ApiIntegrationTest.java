package com.subwayalert;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.*;
import java.util.Map;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(properties={"app.scheduling=false"})
@ActiveProfiles("demo") @AutoConfigureMockMvc @Import(ApiIntegrationTest.TestClockConfig.class)
@EnabledIfEnvironmentVariable(named="RUN_DB_TESTS", matches="true")
class ApiIntegrationTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper json;
    @Autowired JdbcTemplate db;
    @Autowired TrackingService service;
    @Autowired Notifications notifications;
    @Autowired MutableClock clock;
    @BeforeEach void reset() {
        db.update("delete from app_private.tracking_sessions");
        clock.now = Instant.parse("2026-10-27T00:00:00Z");
    }
    String request(String key) throws Exception {
        return json.writeValueAsString(Map.of("lineId","DEMO", "direction","0", "boardingStationId","demo-a",
            "destinationStationId","demo-d", "fcmToken","DEMO", "idempotencyKey",key));
    }
    String start(String owner, String key) throws Exception {
        String body = mvc.perform(post("/api/track").header("X-Demo-User",owner).contentType("application/json").content(request(key)))
            .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("WAITING_BOARDING"))
            .andReturn().getResponse().getContentAsString();
        return json.readTree(body).get("id").asText();
    }
    @Test void idempotentCreationAndOwnership() throws Exception {
        String id = start("alice","request-1");
        assertEquals(id,start("alice","request-1"));
        mvc.perform(get("/api/track/"+id+"/status").header("X-Demo-User","bob")).andExpect(status().isNotFound());
        mvc.perform(delete("/api/track/"+id).header("X-Demo-User","bob")).andExpect(status().isNotFound());
        mvc.perform(post("/api/track").header("X-Demo-User","alice").contentType("application/json").content(request("request-2")))
            .andExpect(status().isConflict());
    }
    @Test void sameIdempotencyKeyCannotChangeRoute() throws Exception {
        start("alice","request-1");
        String changed = request("request-1").replace("demo-d","demo-e");
        mvc.perform(post("/api/track").header("X-Demo-User","alice").contentType("application/json").content(changed))
            .andExpect(status().isConflict());
    }
    @Test void rejectsUnconfirmedAndOtherTrain() throws Exception {
        String id = start("alice","request-1");
        mvc.perform(post("/api/track/"+id+"/board").header("X-Demo-User","alice").contentType("application/json").content("{\"trainNo\":\"OTHER\"}"))
            .andExpect(status().isBadRequest());
        assertEquals(0,db.queryForObject("select count(*) from app_private.alert_outbox",Integer.class));
    }
    @Test void departureProducesOneDurableAlertAndDispatcherMarksAccepted() throws Exception {
        String id = start("alice","request-1");
        mvc.perform(post("/api/track/"+id+"/board").header("X-Demo-User","alice").contentType("application/json")
                .content("{\"trainNo\":\"DEMO-"+id+"\"}"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("TRACKING"));
        clock.now = clock.now.plusSeconds(25);
        service.poll(); service.poll();
        assertEquals(1,db.queryForObject("select count(*) from app_private.alert_outbox",Integer.class));
        notifications.dispatch();
        mvc.perform(get("/api/track/"+id+"/status").header("X-Demo-User","alice"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("ALERTED"));
    }
    @Test void cancellationPreventsDispatch() throws Exception {
        String id = start("alice","request-1");
        mvc.perform(delete("/api/track/"+id).header("X-Demo-User","alice")).andExpect(status().isOk());
        clock.now = clock.now.plusSeconds(30); service.poll(); notifications.dispatch();
        assertEquals(0,db.queryForObject("select count(*) from app_private.alert_outbox where state='SENT'",Integer.class));
    }
    @Test void validatesInputAndClearlyMarksSyntheticData() throws Exception {
        mvc.perform(post("/api/track").contentType("application/json").content(request("missing-auth"))).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/health")).andExpect(status().isOk()).andExpect(jsonPath("$.mode").value("DEMO"));
        mvc.perform(get("/api/station/demo-a")).andExpect(status().isOk()).andExpect(jsonPath("$.station.source").value("SYNTHETIC_DEMO"));
        mvc.perform(post("/api/track").header("X-Demo-User","alice").contentType("application/json").content(request("bad").replace("demo-d","demo-a")))
            .andExpect(status().isBadRequest());
    }
    static class MutableClock extends Clock {
        Instant now=Instant.parse("2026-10-27T00:00:00Z");
        public ZoneId getZone(){return ZoneOffset.UTC;}
        public Clock withZone(ZoneId zone){return this;}
        public Instant instant(){return now;}
    }
    @TestConfiguration static class TestClockConfig {
        @Bean @Primary MutableClock testClock(){return new MutableClock();}
    }
}
