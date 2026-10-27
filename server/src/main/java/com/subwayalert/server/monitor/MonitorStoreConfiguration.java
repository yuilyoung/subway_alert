package com.subwayalert.server.monitor;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Set;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;

@Configuration
public class MonitorStoreConfiguration {
  @Bean(destroyMethod="close")
  MonitorReceiptStore monitorReceiptStore(Environment environment) {
    String mode=environment.getProperty("MONITOR_STORE","memory");
    if("memory".equals(mode))return MonitorReceiptStore.memory();
    if(!"postgres".equals(mode))throw new IllegalStateException("Invalid monitor store configuration");
    String url=environment.getProperty("MONITOR_DB_URL"),user=environment.getProperty("MONITOR_DB_USER"),password=environment.getProperty("MONITOR_DB_PASSWORD");
    if(!validDatabaseUrl(url)||user==null||user.isBlank()||password==null||password.isBlank())
      throw new IllegalStateException("Invalid monitor store configuration");
    return new PostgresMonitorReceiptStore(url,user,password);
  }
  /** Restrict parsing before JDBC can log an invalid URL containing credentials. */
  static boolean validDatabaseUrl(String url) {
    if(url==null||!url.startsWith("jdbc:postgresql://")||url.chars().anyMatch(Character::isISOControl))return false;
    try {
      URI uri=new URI(url.substring(5));
      String path=uri.getRawPath(),query=uri.getRawQuery();
      if(uri.getHost()==null||uri.getRawUserInfo()!=null||uri.getRawFragment()!=null||
         uri.getPort()==0||uri.getPort()>65535||path==null||path.length()<2||path.substring(1).contains("/"))return false;
      return query==null||Set.of("sslmode=disable","sslmode=allow","sslmode=prefer","sslmode=require","sslmode=verify-ca","sslmode=verify-full").contains(query);
    } catch(URISyntaxException e) {return false;}
  }
}
