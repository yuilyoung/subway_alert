package com.subwayalert.server.monitor;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import static org.junit.jupiter.api.Assertions.*;

class MonitorStoreConfigurationTest {
  final MonitorStoreConfiguration configuration=new MonitorStoreConfiguration();
  @Test void defaultAndExplicitMemoryRequireNoDatabase(){
    assertNotNull(configuration.monitorReceiptStore(new MockEnvironment()));
    assertNotNull(configuration.monitorReceiptStore(new MockEnvironment().withProperty("MONITOR_STORE","memory")));
  }
  @Test void unsupportedStoreFailsWithoutFallingBack(){
    for(String value:new String[]{"","postgresql","POSTGRES","redis"})
      assertThrows(IllegalStateException.class,()->configuration.monitorReceiptStore(new MockEnvironment().withProperty("MONITOR_STORE",value)));
  }
  @Test void postgresRequiresEverySettingWithoutIncludingSecretsInErrors(){
    for(String missing:new String[]{"MONITOR_DB_URL","MONITOR_DB_USER","MONITOR_DB_PASSWORD"}) {
      var environment=new MockEnvironment().withProperty("MONITOR_STORE","postgres")
        .withProperty("MONITOR_DB_URL","jdbc:postgresql://private-host/private-db").withProperty("MONITOR_DB_USER","private-user").withProperty("MONITOR_DB_PASSWORD","private-password");
      environment.setProperty(missing,"");
      var error=assertThrows(IllegalStateException.class,()->configuration.monitorReceiptStore(environment));
      assertEquals("Invalid monitor store configuration",error.getMessage());assertNull(error.getCause());
    }
  }
  @Test void unsafeOrMalformedJdbcUrlsAreRejectedBeforeDriverParsing(){
    for(String url:new String[]{"jdbc:postgresql:database","jdbc:postgresql://user:private-password@localhost/db", "jdbc:postgresql://localhost/db?password=private-password", "jdbc:postgresql://localhost/db?socketTimeout=0", "jdbc:postgresql://localhost:99999/db", "jdbc:postgresql://localhost/", "jdbc:postgresql://localhost/db?sslmode=invalid", "jdbc:postgresql://localhost/db%GG", "jdbc:postgresql://localhost/db\n"}) {
      var environment=new MockEnvironment().withProperty("MONITOR_STORE","postgres").withProperty("MONITOR_DB_URL",url)
        .withProperty("MONITOR_DB_USER","private-user").withProperty("MONITOR_DB_PASSWORD","private-password");
      var error=assertThrows(IllegalStateException.class,()->configuration.monitorReceiptStore(environment));
      assertEquals("Invalid monitor store configuration",error.getMessage());assertNull(error.getCause());
    }
  }
  @Test void postgresRejectsNonJdbcConfigurationWithoutAttemptingAConnection(){
    var environment=new MockEnvironment().withProperty("MONITOR_STORE","postgres").withProperty("MONITOR_DB_URL","postgresql://user:private-password@host/db")
      .withProperty("MONITOR_DB_USER","private-user").withProperty("MONITOR_DB_PASSWORD","private-password");
    assertThrows(IllegalStateException.class,()->configuration.monitorReceiptStore(environment));
  }
}
