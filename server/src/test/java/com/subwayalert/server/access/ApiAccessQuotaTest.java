package com.subwayalert.server.access;

import static org.junit.jupiter.api.Assertions.*;

import jakarta.servlet.FilterChain;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class ApiAccessQuotaTest {
  static final String KEY = "abcdefghijklmnopqrstuvwxyzABCDEF",
      OTHER = "01234567890123456789012345678901";
  final AtomicLong elapsed = new AtomicLong();
  final MutableClock wall = new MutableClock(Instant.parse("2026-10-27T14:59:59Z"));
  final AtomicInteger reachedController = new AtomicInteger();
  final ApiAccessFilter filter = new ApiAccessFilter(KEY + "," + OTHER, elapsed::get, wall);
  final FilterChain controller =
      (request, response) -> {
        reachedController.incrementAndGet();
        ((jakarta.servlet.http.HttpServletResponse) response).setStatus(204);
      };

  @Test
  void perKeySixtyPerMinuteContinuouslyRefillsAndKeysHaveSeparateBudgets() throws Exception {
    for (int i = 0; i < 60; i++) assertEquals(204, request("GET", "/api/lines", KEY).getStatus());
    assertLimited(request("GET", "/api/lines", KEY), "1");
    assertEquals(204, request("GET", "/api/lines", OTHER).getStatus());
    elapsed.set(500_000_000L);
    assertLimited(request("GET", "/api/lines", KEY), "1");
    elapsed.set(1_000_000_000L);
    assertEquals(204, request("GET", "/api/lines", KEY).getStatus());
    assertEquals(62, reachedController.get());
  }

  @Test
  void preAuthenticationGlobalLimitBoundsUntrustedRequestsWithoutCreatingKeyState()
      throws Exception {
    for (int i = 0; i < 600; i++) assertEquals(401, request("GET", "/api/lines", null).getStatus());
    assertLimited(request("GET", "/api/lines", OTHER), "1");
    assertEquals(0, reachedController.get());
    elapsed.set(100_000_000L);
    assertEquals(204, request("GET", "/api/lines", KEY).getStatus());
  }

  @Test
  void publicHealthDoesNotUseThePrivateApiBudget() throws Exception {
    for (int i = 0; i < 650; i++)
      assertEquals(204, request("GET", "/api/health", null).getStatus());
    assertEquals(401, request("GET", "/api/lines", null).getStatus());
  }

  @Test
  void sessionCreationSharesThreePerMinuteAcrossBothCreationEndpoints() throws Exception {
    assertEquals(204, request("POST", "/api/track", KEY).getStatus());
    assertEquals(204, request("POST", "/api/monitor-sessions", KEY).getStatus());
    assertEquals(204, request("POST", "/api/track", KEY).getStatus());
    assertLimited(request("POST", "/api/monitor-sessions", KEY), "20");
    assertEquals(204, request("POST", "/api/monitor-sessions", OTHER).getStatus());
    elapsed.set(20_000_000_000L);
    assertEquals(204, request("POST", "/api/track", KEY).getStatus());
    assertEquals(5, reachedController.get());
  }

  @Test
  void globalLiveLimitIncludesHeadAndIsSharedAcrossKeysBeforeAnyProviderWork() throws Exception {
    for (int i = 0; i < 6; i++)
      assertEquals(
          204,
          request(i % 2 == 0 ? "GET" : "HEAD", "/api/live/trains", i % 2 == 0 ? KEY : OTHER)
              .getStatus());
    assertLimited(request("GET", "/api/live/trains", OTHER), "10");
    assertLimited(request("HEAD", "/api/live/trains", KEY), "10");
    assertEquals(6, reachedController.get());
    elapsed.set(10_000_000_000L);
    assertEquals(204, request("GET", "/api/live/trains", KEY).getStatus());
  }

  @Test
  void liveDailyBudgetResetsAtSeoulMidnightAndIsIndependentOfMinuteRefill() throws Exception {
    for (int i = 0; i < 240; i++) {
      elapsed.set(i * 10_000_000_000L);
      assertEquals(204, request("GET", "/api/live/trains", i % 2 == 0 ? KEY : OTHER).getStatus());
    }
    elapsed.addAndGet(10_000_000_000L);
    assertLimited(request("GET", "/api/live/trains", KEY), "1");
    assertEquals(240, reachedController.get());
    wall.now = Instant.parse("2026-10-27T15:00:00Z");
    assertEquals(204, request("GET", "/api/live/trains", KEY).getStatus());
  }

  @Test
  void noncanonicalPathsCannotAliasControllersAndBypassTheirQuotas() throws Exception {
    for (String path :
        new String[] {
          "/api/live/trains;ignored",
          "/api/track;ignored",
          "/api/%74rack",
          "/api//track",
          "/api/./track",
          "/api/a/../track",
          "/api\\track"
        }) assertEquals(400, request("POST", path, KEY).getStatus());
    assertEquals(0, reachedController.get());
  }

  @Test
  void servletContextPrefixCannotBypassLiveOrCreationBudgets() throws Exception {
    for (int i = 0; i < 6; i++)
      assertEquals(204, requestInContext("GET", "/prefix/api/live/trains", KEY).getStatus());
    assertLimited(requestInContext("GET", "/prefix/api/live/trains", KEY), "10");
    for (int i = 0; i < 3; i++)
      assertEquals(204, requestInContext("POST", "/prefix/api/track", KEY).getStatus());
    assertLimited(requestInContext("POST", "/prefix/api/monitor-sessions", KEY), "20");
  }

  @Test
  void dispatcherServletPrefixCannotBypassLiveOrCreationBudgets() throws Exception {
    for (int i = 0; i < 6; i++)
      assertEquals(204, requestInServlet("GET", "/api/live/trains").getStatus());
    assertLimited(requestInServlet("GET", "/api/live/trains"), "10");
    for (int i = 0; i < 3; i++)
      assertEquals(204, requestInServlet("POST", "/api/track").getStatus());
    assertLimited(requestInServlet("POST", "/api/monitor-sessions"), "20");
  }

  @Test
  void concurrentLiveCallsNeverExceedGlobalAllowance() throws Exception {
    var pool = Executors.newFixedThreadPool(12);
    var start = new CountDownLatch(1);
    List<java.util.concurrent.Future<Integer>> results = new ArrayList<>();
    try {
      for (int i = 0; i < 24; i++) {
        final String token = i % 2 == 0 ? KEY : OTHER;
        results.add(
            pool.submit(
                () -> {
                  start.await();
                  return request("GET", "/api/live/trains", token).getStatus();
                }));
      }
      start.countDown();
      int allowed = 0, limited = 0;
      for (var result : results) {
        int status = result.get();
        if (status == 204) allowed++;
        else if (status == 429) limited++;
        else fail("Unexpected status " + status);
      }
      assertEquals(6, allowed);
      assertEquals(18, limited);
      assertEquals(6, reachedController.get());
    } finally {
      pool.shutdownNow();
    }
  }

  @Test
  void concurrentRequestsNeverExceedOneKeysAllowance() throws Exception {
    var pool = Executors.newFixedThreadPool(12);
    var start = new CountDownLatch(1);
    List<java.util.concurrent.Future<Integer>> results = new ArrayList<>();
    try {
      for (int i = 0; i < 120; i++)
        results.add(
            pool.submit(
                () -> {
                  start.await();
                  return request("GET", "/api/lines", KEY).getStatus();
                }));
      start.countDown();
      int allowed = 0, limited = 0;
      for (var result : results) {
        int status = result.get();
        if (status == 204) allowed++;
        else if (status == 429) limited++;
        else fail("Unexpected status " + status);
      }
      assertEquals(60, allowed);
      assertEquals(60, limited);
      assertEquals(60, reachedController.get());
    } finally {
      pool.shutdownNow();
    }
  }

  private MockHttpServletResponse request(String method, String path, String key) throws Exception {
    var request = new MockHttpServletRequest(method, path);
    if (key != null) request.addHeader("Authorization", "Bearer " + key);
    var response = new MockHttpServletResponse();
    filter.doFilter(request, response, controller);
    return response;
  }

  private MockHttpServletResponse requestInContext(String method, String path, String key)
      throws Exception {
    var request = new MockHttpServletRequest(method, path);
    request.setContextPath("/prefix");
    request.addHeader("Authorization", "Bearer " + key);
    var response = new MockHttpServletResponse();
    filter.doFilter(request, response, controller);
    return response;
  }

  private MockHttpServletResponse requestInServlet(String method, String path) throws Exception {
    var request = new MockHttpServletRequest(method, "/prefix" + path);
    request.setServletPath("/prefix");
    request.setPathInfo(path);
    request.addHeader("Authorization", "Bearer " + KEY);
    var response = new MockHttpServletResponse();
    filter.doFilter(request, response, controller);
    return response;
  }

  private static void assertLimited(MockHttpServletResponse response, String retry)
      throws Exception {
    assertEquals(429, response.getStatus());
    assertEquals(retry, response.getHeader("Retry-After"));
    assertEquals("application/json;charset=UTF-8", response.getContentType());
    assertEquals(
        "API_RATE_LIMITED",
        new com.fasterxml.jackson.databind.ObjectMapper()
            .readTree(response.getContentAsString())
            .path("error")
            .asText());
    assertFalse(response.getContentAsString().contains(KEY));
  }

  static final class MutableClock extends Clock {
    volatile Instant now;

    MutableClock(Instant now) {
      this.now = now;
    }

    public ZoneId getZone() {
      return ZoneOffset.UTC;
    }

    public Clock withZone(ZoneId zone) {
      return this;
    }

    public Instant instant() {
      return now;
    }
  }
}
