package com.subwayalert;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.subwayalert.core.JourneyEngine.Observation;
import java.io.InputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class TopisClient {
    private record Cached(Instant fetched,List<Observation> positions,boolean failed) {}
    private final Map<String,Cached> cache=new HashMap<>();
    private final Config config; private final Catalog catalog; private final ObjectMapper json; private final Clock clock;
    private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
    private LocalDate budgetDay; private int requests;
    public TopisClient(Config config,Catalog catalog,ObjectMapper json,Clock clock){this.config=config;this.catalog=catalog;this.json=json;this.clock=clock;}
    public synchronized List<Observation> positions(String lineId) {
        Instant now=clock.instant(); Cached existing=cache.get(lineId);
        if(existing!=null&&Duration.between(existing.fetched(),now).toMillis()<10_000) {
            if(existing.failed()) throw unavailable();
            return existing.positions();
        }
        LocalDate day=now.atZone(ZoneId.of("Asia/Seoul")).toLocalDate();
        if(!day.equals(budgetDay)){budgetDay=day;requests=0;}
        if(requests>=config.budget()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"실시간 API 일일 호출 예산에 도달했습니다.");
        requests++;
        try {
            String key=config.get("app.topis-key"), base=config.get("app.topis-base-url");
            if(!key.matches("[A-Za-z0-9]+")||!base.startsWith("https://")) throw new IllegalArgumentException("Invalid TOPIS configuration");
            String name=URLEncoder.encode(catalog.line(lineId).topisName(),StandardCharsets.UTF_8).replace("+","%20");
            URI uri=URI.create(base.replaceAll("/$","")+"/"+key+"/json/realtimePosition/0/1000/"+name);
            HttpResponse<InputStream> response=http.send(HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(5)).GET().build(),HttpResponse.BodyHandlers.ofInputStream());
            byte[] bytes;
            try(InputStream in=response.body()){bytes=in.readNBytes(2_000_001);}
            if(response.statusCode()!=200||bytes.length>2_000_000) throw new IllegalStateException("TOPIS transport error");
            JsonNode root=json.readTree(bytes), rows=root.path("realtimePositionList");
            if(!rows.isArray()) throw new IllegalStateException("TOPIS response missing positions");
            List<Observation> result=new ArrayList<>();
            for(JsonNode row:rows) {
                try {
                    String direction=row.path("updnLine").asText(), train=row.path("trainNo").asText();
                    if(!row.path("subwayId").asText().equals(lineId)||!Set.of("0","1").contains(direction)||train.isBlank()) continue;
                    Optional<String> station=catalog.fromTopis(lineId,row.path("statnId").asText());
                    if(station.isEmpty()) continue;
                    String terminal=catalog.fromTopis(lineId,row.path("statnTid").asText()).orElse("");
                    String state=switch(row.path("trainSttus").asText()){case "0"->"ENTERING";case "1"->"ARRIVED";case "2"->"DEPARTED";default->"UNKNOWN";};
                    Instant observed=LocalDateTime.parse(row.path("recptnDt").asText().replace(' ','T')).atZone(ZoneId.of("Asia/Seoul")).toInstant();
                    // Unknown express flags are not assumed to mean an ordinary train.
                    boolean express=!"0".equals(row.path("directAt").asText());
                    result.add(new Observation(train,lineId,direction,station.get(),state,observed,express,terminal));
                } catch(RuntimeException invalidRow) { /* Ignore an invalid observation, never fabricate fields. */ }
            }
            List<Observation> immutable=List.copyOf(result);
            cache.put(lineId,new Cached(now,immutable,false));return immutable;
        } catch(InterruptedException e) {
            Thread.currentThread().interrupt(); cache.put(lineId,new Cached(now,List.of(),true));throw unavailable();
        } catch(Exception e) {
            cache.put(lineId,new Cached(now,List.of(),true));throw unavailable();
        }
    }
    private static ResponseStatusException unavailable(){return new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"실시간 열차 정보를 가져오지 못했습니다. 잠시 후 다시 시도하세요.");}
}
