package com.subwayalert.server.live;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import java.net.URI;
import java.time.Instant;
import static org.junit.jupiter.api.Assertions.*;

class SeoulTrainProviderTest {
  private static final String RESPONSE = """
    {"errorMessage":{"code":"INFO-000","total":35},"realtimePositionList":[
      {"subwayId":"1002","statnNm":"강남","trainNo":"1234","recptnDt":"2026-10-27 21:52:00","updnLine":"0","trainSttus":"2","directAt":"0"},
      {"subwayId":"1002","statnNm":"삼성","trainNo":"5678","recptnDt":"2026-10-27 21:50:00","updnLine":"1","trainSttus":"1","directAt":"1"}]}
    """;
  @Test void mapsActualProviderFieldsAndExposesFreshness(){
    var page=SeoulTrainProvider.parse(RESPONSE,new ObjectMapper(),Instant.parse("2026-10-27T12:52:30Z"));
    assertEquals(35,page.total()); assertEquals(2,page.trains().size());
    var train=page.trains().get(0); assertEquals("2",train.lineId()); assertEquals("강남",train.station());
    assertEquals("1234",train.trainId()); assertEquals("INNER",train.direction()); assertEquals("DEPARTED",train.state());
    assertEquals(Instant.parse("2026-10-27T12:52:00Z"),train.observedAt()); assertTrue(train.fresh());
    assertFalse(page.trains().get(1).fresh()); assertTrue(page.trains().get(1).express());
  }
  @Test void rejectsProviderErrorMalformedTimeAndUnexpectedLine(){
    assertThrows(SeoulTrainProvider.ProviderException.class,()->SeoulTrainProvider.parse("{\"errorMessage\":{\"code\":\"ERROR-300\"}}",new ObjectMapper(),Instant.now()));
    assertThrows(SeoulTrainProvider.ProviderException.class,()->SeoulTrainProvider.parse(RESPONSE.replace("2026-10-27 21:52:00","bad"),new ObjectMapper(),Instant.now()));
    assertThrows(SeoulTrainProvider.ProviderException.class,()->SeoulTrainProvider.parse(RESPONSE.replace("1002","1001"),new ObjectMapper(),Instant.now()));
  }
  @Test void neverSendsLiveSecretsOverHttpOrOtherHosts(){
    assertThrows(IllegalArgumentException.class,()->SeoulTrainProvider.endpoint(URI.create("http://swopenapi.seoul.go.kr"),"private",0,5));
    assertThrows(IllegalArgumentException.class,()->SeoulTrainProvider.endpoint(URI.create("https://evil.test"),"private",0,5));
    assertDoesNotThrow(()->SeoulTrainProvider.endpoint(URI.create("http://swopenapi.seoul.go.kr"),"sample",0,5));
    assertDoesNotThrow(()->SeoulTrainProvider.endpoint(URI.create("https://swopenapi.seoul.go.kr"),"private",0,999));
  }
  @Test void sampleIsExplicitAndLimitedToOneSmallPage(){
    var seen=new java.util.ArrayList<URI>();
    var provider=new SeoulTrainProvider("sample",URI.create("http://swopenapi.seoul.go.kr"), (uri)->{seen.add(uri); return RESPONSE;}, new ObjectMapper(), ()->Instant.parse("2026-10-27T12:52:30Z"));
    var result=provider.fetch("2"); assertEquals("SAMPLE",result.mode()); assertEquals(2,result.trains().size()); assertTrue(result.warning().contains("5")); assertEquals(1,seen.size()); assertTrue(seen.get(0).getPath().contains("/realtimePosition/0/5/"));
    assertThrows(IllegalArgumentException.class,()->provider.fetch("7"));
  }
  @Test void sampleFactoryAlwaysUsesOnlyPublicSampleCredential(){
    var seen=new java.util.ArrayList<URI>();
    var provider=SeoulTrainProvider.sample(new ObjectMapper(),uri->{seen.add(uri);return RESPONSE;},()->Instant.parse("2026-10-27T12:52:30Z"));
    assertEquals("SAMPLE",provider.fetch("2").mode());
    assertEquals("http",seen.get(0).getScheme());
    assertTrue(seen.get(0).getPath().startsWith("/api/subway/sample/"));
  }
}
