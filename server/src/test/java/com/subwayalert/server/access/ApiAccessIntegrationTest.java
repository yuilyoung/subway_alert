package com.subwayalert.server.access;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** These requests use Boot's registered filter chain and real controllers. */
@SpringBootTest(properties={"SUBWAY_API_TOKENS=abcdefghijklmnopqrstuvwxyzABCDEF", "monitor.poll-interval-ms=3600000"})
@AutoConfigureMockMvc
class ApiAccessIntegrationTest {
  private static final String AUTH="Bearer abcdefghijklmnopqrstuvwxyzABCDEF";
  @Autowired MockMvc mvc;
  @Autowired ObjectMapper json;

  @Test void healthIsTheOnlyUnauthenticatedMethodAndExactPath() throws Exception {
    mvc.perform(get("/api/health")).andExpect(status().isOk());
    for(String path:new String[]{"/api/lines","/api/health/","/api/health;ignored","/api/%68ealth","//api/health","/api/unknown","/other"})
      mvc.perform(get(path)).andExpect(status().isUnauthorized()).andExpect(jsonPath("$.error").value("API_UNAUTHORIZED"));
    mvc.perform(head("/api/health")).andExpect(status().isUnauthorized());
    mvc.perform(post("/api/health")).andExpect(status().isUnauthorized());
  }

  @Test void rejectsWrongMalformedAndDuplicateHeadersWithoutEchoingSecrets() throws Exception {
    for(String value:new String[]{"Bearer wrong","Basic abcdefghijklmnopqrstuvwxyzABCDEF","Bearer ","Bearer abcdefghijklmnopqrstuvwxyzABCDEF extra","Bearer abcdefghijklmnopqrstuvwxyzABCDEF, Bearer abcdefghijklmnopqrstuvwxyzABCDEF"})
      mvc.perform(get("/api/lines").header("Authorization",value)).andExpect(status().isUnauthorized()).andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("abcdefghijklmnopqrstuvwxyzABCDEF"))));
    mvc.perform(get("/api/lines").header("Authorization",AUTH,AUTH)).andExpect(status().isUnauthorized());
    mvc.perform(get("/api/lines").header("Forwarded","for=127.0.0.1;host=localhost;proto=https").header("X-Forwarded-For","127.0.0.1")).andExpect(status().isUnauthorized());
  }

  @Test void authenticatedAliasesAreRejectedBeforeControllerRouting() throws Exception {
    for(String path:new String[]{"/api/track;ignored","/api/%74rack","/api//track","/api/./track"})
      mvc.perform(post("/").with(request->{request.setRequestURI(path);return request;}).header("Authorization",AUTH).contentType("application/json").content("{}"))
        .andExpect(status().isBadRequest()).andExpect(jsonPath("$.error").value("API_INVALID_PATH"));
    mvc.perform(get("/api/live/trains;ignored").header("Authorization",AUTH))
      .andExpect(status().isBadRequest()).andExpect(jsonPath("$.error").value("API_INVALID_PATH"));
  }

  @Test void configuredBearerAllowsAccess() throws Exception {
    mvc.perform(get("/api/lines").header("Authorization",AUTH)).andExpect(status().isOk()).andExpect(jsonPath("$[0].id").value("2"));
  }

  @Test void apiKeyDoesNotReplaceLegacySessionCapability() throws Exception {
    String body="{\"lineId\":\"2\",\"direction\":\"UP\",\"boardingStation\":\"강남\",\"destinationStation\":\"삼성\",\"trainId\":\"1234\"}";
    var response=mvc.perform(post("/api/track").header("Authorization",AUTH).contentType("application/json").content(body)).andExpect(status().isOk()).andReturn();
    var created=json.readTree(response.getResponse().getContentAsString());
    String path="/api/track/"+created.path("id").asText()+"/status", secret=created.path("sessionToken").asText();
    mvc.perform(get(path).header("Authorization",AUTH)).andExpect(status().isNotFound());
    mvc.perform(get(path).header("Authorization",AUTH).header("X-Session-Token","wrong")).andExpect(status().isNotFound());
    mvc.perform(get(path).header("Authorization",AUTH).header("X-Session-Token",secret)).andExpect(status().isOk());
    mvc.perform(get(path).header("X-Session-Token",secret)).andExpect(status().isUnauthorized());
  }

  @Test void apiKeyDoesNotReplaceMonitorSessionCapability() throws Exception {
    String body="{\"lineId\":\"2\",\"trainId\":\"0202\",\"direction\":\"INNER\",\"previousStation\":\"선릉\",\"destinationStation\":\"삼성\",\"fcmToken\":\"test-token\",\"mode\":\"TEST\"}";
    var response=mvc.perform(post("/api/monitor-sessions").header("Authorization",AUTH).contentType("application/json").content(body)).andExpect(status().isOk()).andReturn();
    var created=json.readTree(response.getResponse().getContentAsString());
    String path="/api/monitor-sessions/"+created.path("id").asText(), secret=created.path("sessionToken").asText();
    mvc.perform(get(path).header("Authorization",AUTH)).andExpect(status().isNotFound());
    mvc.perform(delete(path).header("Authorization",AUTH).header("X-Session-Token","wrong")).andExpect(status().isNotFound());
    mvc.perform(get(path).header("Authorization",AUTH).header("X-Session-Token",secret)).andExpect(status().isOk());
    mvc.perform(delete(path).header("Authorization",AUTH).header("X-Session-Token",secret)).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("CANCELLED"));
  }
}
