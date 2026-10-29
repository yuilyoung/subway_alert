package com.subwayalert.server.monitor;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.subwayalert.server.live.SeoulTrainProvider;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;

/** Sample-only polling, shared across active sessions. No production monitoring. */
@Configuration
@EnableScheduling
public class MonitorScheduler {
  private final MonitorService service;
  private final SeoulTrainProvider provider;

  public MonitorScheduler(MonitorService service, ObjectMapper mapper) {
    this.service = service;
    this.provider = SeoulTrainProvider.sample(mapper);
  }

  @Scheduled(
      fixedDelayString = "${monitor.poll-interval-ms:120000}",
      initialDelayString = "${monitor.poll-interval-ms:120000}")
  public void poll() {
    service.poll(() -> provider.fetch("2"));
  }
}
