package com.subwayalert.server.monitor;

import com.subwayalert.server.access.ApiAccessFilter;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Collections;
import java.util.Map;
import java.util.UUID;
import java.util.function.LongSupplier;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping(value="/api/monitor-sessions",produces=MediaType.APPLICATION_JSON_VALUE)
public final class MonitorController {
  private final MonitorService service;
  public MonitorController(MonitorService service){this.service=service;}
  @PostMapping public MonitorService.StartResponse start(@RequestBody MonitorService.StartRequest request,HttpServletRequest http){
    try{
      String key=singleHeader(http,"Idempotency-Key"),secret=singleHeader(http,"X-Session-Token");
      if(!key.matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"))
        throw new IllegalArgumentException("Invalid registration identity");
      return service.start(UUID.fromString(key),secret,request);
    }catch(IllegalArgumentException e){throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Invalid TEST session");}
    catch(MonitorService.Conflict e){throw new ResponseStatusException(HttpStatus.CONFLICT,"Registration conflict");}
    catch(MonitorService.CapacityExceeded e){throw capacityExceeded();}
  }
  @GetMapping("/{id}") public MonitorService.StatusResponse status(@PathVariable UUID id,@RequestHeader(value="X-Session-Token",required=false) String secret){
    try{return service.status(id,secret);}catch(MonitorService.NotFound e){throw notFound();}
  }
  @DeleteMapping("/{id}") public MonitorService.StatusResponse cancel(@PathVariable UUID id,@RequestHeader(value="X-Session-Token",required=false) String secret,
      @RequestAttribute(ApiAccessFilter.CREATION_BUDGET) LongSupplier creationBudget){
    try{return service.cancel(id,secret,creationBudget);}catch(MonitorService.NotFound e){throw notFound();}
    catch(IllegalArgumentException e){throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Invalid registration identity");}
    catch(MonitorService.CapacityExceeded e){throw capacityExceeded();}
  }
  @ExceptionHandler(MonitorService.CreationRateLimited.class)
  public ResponseEntity<Map<String,String>> creationRateLimited(MonitorService.CreationRateLimited e){
    return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS).header(HttpHeaders.RETRY_AFTER,Long.toString(e.retryAfter))
        .body(Map.of("error","API_RATE_LIMITED"));
  }
  @PostMapping("/{id}/test") public MonitorService.StatusResponse test(@PathVariable UUID id,@RequestHeader(value="X-Session-Token",required=false) String secret){
    try{return service.test(id,secret);}catch(MonitorService.NotFound e){throw notFound();}
    catch(MonitorService.Conflict e){throw new ResponseStatusException(HttpStatus.CONFLICT,"Session inactive or test rate limited");}
  }
  private static String singleHeader(HttpServletRequest request,String name){
    var values=Collections.list(request.getHeaders(name));
    if(values.size()!=1)throw new IllegalArgumentException("Invalid registration headers");
    return values.get(0);
  }
  private static ResponseStatusException capacityExceeded(){return new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"Session capacity reached");}
  private static ResponseStatusException notFound(){return new ResponseStatusException(HttpStatus.NOT_FOUND,"Session not found");}
}
