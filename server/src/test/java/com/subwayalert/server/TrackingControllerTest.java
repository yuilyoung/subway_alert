package com.subwayalert.server;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(value=TrackingController.class,properties="SUBWAY_API_TOKENS=abcdefghijklmnopqrstuvwxyzABCDEF")
@org.springframework.context.annotation.Import(TrackingControllerTest.AuthDefaults.class)
class TrackingControllerTest {
  @org.springframework.boot.test.context.TestConfiguration
  static class AuthDefaults {
    @org.springframework.context.annotation.Bean
    org.springframework.boot.test.autoconfigure.web.servlet.MockMvcBuilderCustomizer authDefaults() {
      return builder->builder.defaultRequest(get("/").header("Authorization","Bearer abcdefghijklmnopqrstuvwxyzABCDEF"));
    }
  }
  @Autowired MockMvc mvc;
  @Autowired ObjectMapper json;
  @Test void capabilityAndDemoLifecycle() throws Exception {
    String req = "{\"lineId\":\"2\",\"direction\":\"UP\",\"boardingStation\":\"강남\",\"destinationStation\":\"삼성\",\"trainId\":\"1234\"}";
    String body = mvc.perform(post("/api/track").contentType(MediaType.APPLICATION_JSON).content(req)).andExpect(status().isOk()).andExpect(jsonPath("$.dataMode").value("DEMO")).andReturn().getResponse().getContentAsString();
    JsonNode response = json.readTree(body);
    String id = response.get("id").asText(), token = response.get("sessionToken").asText();
    mvc.perform(get("/api/track/{id}/status", id)).andExpect(status().isNotFound());
    mvc.perform(get("/api/track/{id}/status", id).header("X-Session-Token", "wrong")).andExpect(status().isNotFound());
    mvc.perform(get("/api/track/{id}/status", id).header("X-Session-Token", token)).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("TRACKING"));
    String event = json.writeValueAsString(new TrackingController.DemoEvent("2", "UP", "1234", "선릉", "DEPARTED", Instant.now()));
    mvc.perform(post("/api/track/{id}/demo-event", id).header("X-Session-Token", token).contentType(MediaType.APPLICATION_JSON).content(event)).andExpect(status().isOk()).andExpect(jsonPath("$.matched").value(true));
    mvc.perform(post("/api/track/{id}/demo-event", id).header("X-Session-Token", token).contentType(MediaType.APPLICATION_JSON).content(event)).andExpect(status().isOk()).andExpect(jsonPath("$.matched").value(false));
    mvc.perform(get("/api/track/{id}/status", id).header("X-Session-Token", token)).andExpect(jsonPath("$.status").value("ALERTED"));
  }
  @Test void rejectsMissingStationAndTrain() throws Exception {
    mvc.perform(post("/api/track").contentType(MediaType.APPLICATION_JSON).content("{\"lineId\":\"2\",\"direction\":\"UP\",\"destinationStation\":\"삼성\"}"))
      .andExpect(status().isBadRequest());
  }
}
