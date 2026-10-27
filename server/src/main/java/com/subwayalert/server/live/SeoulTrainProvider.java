package com.subwayalert.server.live;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Supplier;

/** Seoul Open Data API reader. This is not a passenger train-identification or alert service. */
public final class SeoulTrainProvider {
  private static final String HOST="swopenapi.seoul.go.kr";
  private static final DateTimeFormatter DATE=DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss").withResolverStyle(java.time.format.ResolverStyle.STRICT);
  private static final ZoneId SEOUL=ZoneId.of("Asia/Seoul");
  @FunctionalInterface interface Transport { String get(URI uri) throws Exception; }
  public record Train(String lineId, String station, String trainId, String direction, String state, Instant observedAt, boolean express, boolean fresh) { }
  public record Page(int total,List<Train> trains) { }
  public record Result(String mode,List<Train> trains,String warning) { }
  public static final class ProviderException extends RuntimeException {
    public ProviderException(String message){super(message);}
  }
  private final String key;
  private final URI base;
  private final Transport transport;
  private final ObjectMapper mapper;
  private final Supplier<Instant> now;

  SeoulTrainProvider(String key,URI base,Transport transport,ObjectMapper mapper,Supplier<Instant> now){
    this.key=key; this.base=base; this.transport=transport; this.mapper=mapper; this.now=now;
    endpoint(base,key,0,5); // fail before sending a credential
  }
  public static SeoulTrainProvider configured(ObjectMapper mapper){
    String configured=System.getenv("SEOUL_SUBWAY_KEY");
    String key=(configured==null || configured.isBlank())?"sample":configured.trim();
    URI base=URI.create("sample".equals(key)?"http://"+HOST:"https://"+HOST);
    HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).followRedirects(HttpClient.Redirect.NEVER).build();
    Transport transport=uri->{
      var request=HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(10)).GET().build();
      var response=http.send(request,HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
      if(response.statusCode()!=200 || response.body().length()>2_000_000) throw new ProviderException("Upstream unavailable");
      return response.body();
    };
    return new SeoulTrainProvider(key,base,transport,mapper,Instant::now);
  }
  static URI endpoint(URI base,String key,int from,int to){
    if(base==null || !HOST.equalsIgnoreCase(base.getHost()) || base.getRawUserInfo()!=null || base.getPort()!=-1 || base.getRawQuery()!=null || base.getRawFragment()!=null || !(base.getRawPath()==null || base.getRawPath().isEmpty() || base.getRawPath().equals("/")) || key==null || !key.matches("[A-Za-z0-9_-]{1,128}") || from<0 || to<from) throw new IllegalArgumentException("Invalid provider configuration");
    boolean https="https".equalsIgnoreCase(base.getScheme());
    if(!https && !("http".equalsIgnoreCase(base.getScheme()) && "sample".equals(key))) throw new IllegalArgumentException("HTTPS required for credentials");
    return URI.create(base.getScheme().toLowerCase()+"://"+HOST+"/api/subway/"+key+"/json/realtimePosition/"+from+"/"+to+"/"+URLEncoder.encode("2호선",StandardCharsets.UTF_8));
  }
  public Result fetch(String line){
    if(!"2".equals(line))throw new IllegalArgumentException("Only line 2 is supported");
    boolean sample="sample".equals(key);
    int start=sample?0:1, pageSize=sample?5:1000;
    List<Train> trains=new ArrayList<>();
    boolean truncated=false;
    try {
      do {
        Page page=parse(transport.get(endpoint(base,key,start,sample?5:start+pageSize-1)),mapper,now.get());
        trains.addAll(page.trains());
        if(sample || page.trains().isEmpty() || start+pageSize-1>=page.total()) break;
        start+=pageSize;
        if(start>5000){truncated=true;break;}
      } while(true);
    } catch (ProviderException e) { throw e; }
      catch (Exception e) { throw new ProviderException("Seoul API request failed or timed out"); }
    String warning=sample?"공개 샘플키: 최대 5건만 반환되며 탑승 열차나 알림을 확인할 수 없습니다.":"수신 시각은 서울 시간으로 추정합니다. 탑승 여부와 실시간 정확도는 검증되지 않았습니다.";
    if(truncated) warning+=" 5000건으로 결과가 제한되었습니다.";
    return new Result(sample?"SAMPLE":"LIVE",List.copyOf(trains),warning);
  }
  static Page parse(String json,ObjectMapper mapper,Instant now){
    try {
      JsonNode root=mapper.readTree(json), error=root.path("errorMessage");
      String code=error.path("code").asText();
      if("INFO-200".equals(code)) return new Page(0,List.of());
      if(!"INFO-000".equals(code))throw new ProviderException("Seoul API returned an error");
      int total=error.path("total").asInt(-1);
      JsonNode rows=root.path("realtimePositionList");
      if(total<0 || !rows.isArray())throw new ProviderException("Invalid Seoul API response");
      List<Train> trains=new ArrayList<>();
      for(JsonNode row:rows){
        if(!"1002".equals(row.path("subwayId").asText()))throw new ProviderException("Unexpected line in Seoul response");
        String station=row.path("statnNm").asText(), trainId=row.path("trainNo").asText();
        if(station.isBlank() || trainId.isBlank())throw new ProviderException("Invalid train identity");
        String direction=switch(row.path("updnLine").asText()){case "0"->"INNER";case "1"->"OUTER";default->throw new ProviderException("Unknown direction");};
        String state=switch(row.path("trainSttus").asText()){case "0"->"ENTERING";case "1"->"ARRIVED";case "2"->"DEPARTED";case "3"->"PREVIOUS_DEPARTED";default->throw new ProviderException("Unknown train state");};
        String express=row.path("directAt").asText();
        if(!express.equals("0") && !express.equals("1") && !express.equals("7"))throw new ProviderException("Unknown express status");
        Instant observed=LocalDateTime.parse(row.path("recptnDt").asText(),DATE).atZone(SEOUL).toInstant();
        boolean fresh=!observed.isBefore(now.minusSeconds(60)) && !observed.isAfter(now.plusSeconds(5));
        trains.add(new Train("2",station,trainId,direction,state,observed,!express.equals("0"),fresh));
      }
      return new Page(total,List.copyOf(trains));
    }catch(ProviderException e){throw e;}catch(Exception e){throw new ProviderException("Invalid Seoul API response");}
  }
}
