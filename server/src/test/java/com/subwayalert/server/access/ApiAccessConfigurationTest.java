package com.subwayalert.server.access;

import com.subwayalert.server.SubwayAlertApplication;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import static org.assertj.core.api.Assertions.assertThat;

class ApiAccessConfigurationTest {
  @Test void malformedConfigurationStopsStartupWithoutIncludingTheCredential() {
    for(String invalid:new String[]{"secret-with-invalid-character!1234567890", "short", "abcdefghijklmnopqrstuvwxyzABCDEF,", "a".repeat(129), String.join(",",java.util.Collections.nCopies(21,"abcdefghijklmnopqrstuvwxyzABCDEF"))}) {
      new WebApplicationContextRunner().withUserConfiguration(SubwayAlertApplication.class)
        .withPropertyValues("SUBWAY_API_TOKENS="+invalid,"monitor.poll-interval-ms=3600000")
        .run(context->{
          assertThat(context).hasFailed();
          for(Throwable cause=context.getStartupFailure();cause!=null;cause=cause.getCause())
            assertThat(cause.getMessage()).doesNotContain(invalid);
        });
    }
  }
}
