package com.subwayalert.server.access;

import java.io.ByteArrayInputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.test.web.server.LocalServerPort;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT, properties={
    "SUBWAY_API_TOKENS=abcdefghijklmnopqrstuvwxyzABCDEF","monitor.poll-interval-ms=3600000"})
class ApiRequestBodyIntegrationTest {
  private static final int LIMIT=64*1024;
  private static final String AUTH="Bearer abcdefghijklmnopqrstuvwxyzABCDEF";
  private static final String TRACK="{\"lineId\":\"2\",\"direction\":\"UP\",\"boardingStation\":\"강남\",\"destinationStation\":\"삼성\",\"trainId\":\"0202\"}";
  private final HttpClient http=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();
  @LocalServerPort int port;

  @Test void enforcesJsonByteLimitForFixedLengthAndChunkedRequestsBeforeCreatingSessions() throws Exception {
    String exact=TRACK+" ".repeat(LIMIT-TRACK.getBytes(StandardCharsets.UTF_8).length);
    byte[] over=(exact+" ").getBytes(StandardCharsets.UTF_8);
    var fixed=HttpRequest.BodyPublishers.ofByteArray(over);
    var chunked=HttpRequest.BodyPublishers.ofInputStream(()->new ByteArrayInputStream(over));
    assertEquals(-1,chunked.contentLength());
    assertEquals(401,post("/api/track",fixed,false).statusCode());
    assertEquals(200,post("/api/track",HttpRequest.BodyPublishers.ofString(exact),true).statusCode());
    assertEquals(413,post("/api/track",fixed,true).statusCode());
    assertEquals(413,post("/api/track",chunked,true).statusCode());
  }

  @Test @ExtendWith(OutputCaptureExtension.class)
  void bindingErrorOmitsSubmittedValuesFromResponsesAndLogs(CapturedOutput output) throws Exception {
    String invalidTime="private-test-field";
    var response=post("/api/track/97b4b467-2241-49be-ad4e-605ba7eff0d7/demo-event",
        HttpRequest.BodyPublishers.ofString("{\"observedAt\":\""+invalidTime+"\"}"),true);
    assertEquals(400,response.statusCode());
    assertFalse(response.body().contains(invalidTime));
    assertFalse(response.body().contains("\"message\""));
    assertFalse(output.getAll().contains(invalidTime));
  }

  private HttpResponse<String> post(String path,HttpRequest.BodyPublisher body,boolean authenticated) throws Exception {
    var request=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+path))
        .header("Content-Type","application/json").POST(body);
    if(authenticated)request.header("Authorization",AUTH);
    return http.send(request.build(),HttpResponse.BodyHandlers.ofString());
  }
}
