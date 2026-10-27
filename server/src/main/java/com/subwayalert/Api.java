package com.subwayalert;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.*;
import org.springframework.http.*;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class Api {
    public record Start(@NotBlank @Size(max=20) String lineId,@NotNull @Pattern(regexp="[01]") String direction,
        @NotBlank @Size(max=80) String boardingStationId,@NotBlank @Size(max=80) String destinationStationId,
        @NotBlank @Size(max=4096) String fcmToken,@NotBlank @Pattern(regexp="[A-Za-z0-9:_-]{1,128}") String idempotencyKey) {}
    public record Boarding(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,100}") String trainNo) {}
    public record DeviceToken(@NotBlank @Size(max=4096) String fcmToken) {}
    public record Active(TrackingService.View session) {}
    public record Detail(Catalog.Station station,List<Catalog.Facility> facilities,String informationNotice) {}
    private final TrackingService tracking; private final Catalog catalog; private final Config config;
    public Api(TrackingService tracking,Catalog catalog,Config config){this.tracking=tracking;this.catalog=catalog;this.config=config;}
    @GetMapping("/api/health") public Map<String,Object> health(){return Map.of("status","UP","mode",config.demo()?"DEMO":"LIVE","catalogReady",!catalog.lines().isEmpty());}
    @GetMapping("/api/lines") public List<Catalog.Line> lines(){return catalog.lines();}
    @GetMapping("/api/stations/search") public List<Catalog.Station> search(@RequestParam(defaultValue="") String q,@RequestParam(defaultValue="") String lineId){return catalog.stations(q,lineId);}
    @GetMapping("/api/stations/{lineId}") public List<Catalog.Station> stations(@PathVariable String lineId){catalog.line(lineId);return catalog.stations("",lineId);}
    @GetMapping("/api/stations/nearby") public List<Catalog.Station> nearby(@RequestParam double latitude,@RequestParam double longitude){return catalog.nearby(latitude,longitude);}
    @GetMapping("/api/station/{id}") public Detail station(@PathVariable String id){return new Detail(catalog.station(id),catalog.facilities(id),"시설 정보는 출처·확인일을 함께 확인하세요. 없는 항목은 위치를 추정하지 않습니다.");}
    @GetMapping("/api/routes") public List<Catalog.Station> route(@RequestParam String lineId,@RequestParam String direction,@RequestParam String from,@RequestParam String to){return catalog.route(lineId,direction,from,to).stream().map(catalog::station).toList();}
    @PostMapping("/api/track") public TrackingService.View start(@RequestAttribute("uid") String uid,@Valid @RequestBody Start request){return tracking.start(uid,request);}
    @GetMapping("/api/track/active") public Active active(@RequestAttribute("uid") String uid){return new Active(tracking.active(uid));}
    @PutMapping("/api/track/device-token") public Map<String,Boolean> token(@RequestAttribute("uid") String uid,@Valid @RequestBody DeviceToken token){tracking.token(uid,token.fcmToken());return Map.of("updated",true);}
    @GetMapping("/api/track/{id}/status") public TrackingService.View status(@RequestAttribute("uid") String uid,@PathVariable UUID id){return tracking.status(uid,id);}
    @GetMapping("/api/track/{id}/candidates") public List<TrackingService.Candidate> candidates(@RequestAttribute("uid") String uid,@PathVariable UUID id){return tracking.candidates(uid,id);}
    @PostMapping("/api/track/{id}/board") public TrackingService.View board(@RequestAttribute("uid") String uid,@PathVariable UUID id,@Valid @RequestBody Boarding board){return tracking.board(uid,id,board.trainNo());}
    @DeleteMapping("/api/track/{id}") public TrackingService.View cancel(@RequestAttribute("uid") String uid,@PathVariable UUID id){return tracking.cancel(uid,id);}
}

@RestControllerAdvice
class ApiErrors {
    @ExceptionHandler(ResponseStatusException.class) ResponseEntity<Map<String,String>> status(ResponseStatusException e){return ResponseEntity.status(e.getStatusCode()).body(Map.of("error",e.getReason()==null?"요청을 처리할 수 없습니다.":e.getReason()));}
    @ExceptionHandler({IllegalArgumentException.class,MethodArgumentNotValidException.class}) ResponseEntity<Map<String,String>> invalid(Exception e){
        String message=e instanceof MethodArgumentNotValidException?"입력 항목의 형식이나 길이를 확인하세요.":e.getMessage();
        return ResponseEntity.badRequest().body(Map.of("error",message==null?"입력 값을 확인하세요.":message));
    }
}
