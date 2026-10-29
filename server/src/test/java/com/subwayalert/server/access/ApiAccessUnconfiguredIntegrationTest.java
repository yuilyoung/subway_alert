package com.subwayalert.server.access;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(properties = {"SUBWAY_API_TOKENS=", "monitor.poll-interval-ms=3600000"})
@AutoConfigureMockMvc
class ApiAccessUnconfiguredIntegrationTest {
  @Autowired MockMvc mvc;

  @Test
  void missingServerKeysFailClosedButExactHealthStaysPublic() throws Exception {
    mvc.perform(get("/api/health")).andExpect(status().isOk());
    mvc.perform(get("/api/lines"))
        .andExpect(status().isServiceUnavailable())
        .andExpect(jsonPath("$.error").value("API_UNAVAILABLE"));
    mvc.perform(
            get("/api/lines").header("Authorization", "Bearer abcdefghijklmnopqrstuvwxyzABCDEF"))
        .andExpect(status().isServiceUnavailable());
    mvc.perform(get("/unknown")).andExpect(status().isServiceUnavailable());
  }
}
