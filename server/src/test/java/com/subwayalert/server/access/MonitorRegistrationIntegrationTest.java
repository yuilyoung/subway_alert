package com.subwayalert.server.access;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

/**
 * Spring's actual bean wiring must retain both API access and registration capability validation.
 */
@SpringBootTest(
    properties = {
      "SUBWAY_API_TOKENS=abcdefghijklmnopqrstuvwxyzABCDEF",
      "monitor.poll-interval-ms=3600001"
    })
@AutoConfigureMockMvc
class MonitorRegistrationIntegrationTest {
  @Autowired MockMvc mvc;

  @Test
  void bootFilterAndControllerRequireExactlyOneRegistrationIdentityAndSecret() throws Exception {
    String auth = "Bearer abcdefghijklmnopqrstuvwxyzABCDEF",
        id = "ee818ddc-2939-4bb3-9259-bd803b1aba1d",
        secret = "c".repeat(64);
    String body =
        "{\"lineId\":\"2\",\"trainId\":\"0202\",\"direction\":\"INNER\",\"previousStation\":\"선릉\",\"destinationStation\":\"삼성\",\"fcmToken\":\"context-test-token\",\"mode\":\"TEST\"}";
    mvc.perform(
            post("/api/monitor-sessions")
                .header("Authorization", auth)
                .contentType("application/json")
                .content(body))
        .andExpect(status().isBadRequest());
    mvc.perform(
            post("/api/monitor-sessions")
                .header("Authorization", auth)
                .header("Idempotency-Key", id, id)
                .header("X-Session-Token", secret)
                .contentType("application/json")
                .content(body))
        .andExpect(status().isBadRequest());
    mvc.perform(
            post("/api/monitor-sessions")
                .header("Authorization", auth)
                .header("Idempotency-Key", id)
                .header("X-Session-Token", secret)
                .contentType("application/json")
                .content(body))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.id").value(id))
        .andExpect(jsonPath("$.sessionToken").value(secret));
    mvc.perform(get("/api/monitor-sessions/" + id).header("X-Session-Token", secret))
        .andExpect(status().isUnauthorized());
    mvc.perform(get("/api/monitor-sessions/" + id).header("Authorization", auth))
        .andExpect(status().isNotFound());
    mvc.perform(
            get("/api/monitor-sessions/" + id)
                .header("Authorization", auth)
                .header("X-Session-Token", secret))
        .andExpect(status().isOk());
  }
}
