package com.subwayalert.server.monitor;

import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping(value="/api/monitor-sessions",produces=MediaType.APPLICATION_JSON_VALUE)
public final class MonitorController {
  private final MonitorService service;
  public MonitorController(MonitorService service){this.service=service;}
  @PostMapping public MonitorService.StartResponse start(@RequestBody MonitorService.StartRequest request){
    try{return service.start(request);}catch(IllegalArgumentException e){throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Invalid TEST session");}
    catch(MonitorService.Conflict e){throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"Session capacity reached");}
  }
  @GetMapping("/{id}") public MonitorService.StatusResponse status(@PathVariable UUID id,@RequestHeader(value="X-Session-Token",required=false) String secret){
    try{return service.status(id,secret);}catch(MonitorService.NotFound e){throw notFound();}
  }
  @DeleteMapping("/{id}") public MonitorService.StatusResponse cancel(@PathVariable UUID id,@RequestHeader(value="X-Session-Token",required=false) String secret){
    try{return service.cancel(id,secret);}catch(MonitorService.NotFound e){throw notFound();}
  }
  @PostMapping("/{id}/test") public MonitorService.StatusResponse test(@PathVariable UUID id,@RequestHeader(value="X-Session-Token",required=false) String secret){
    try{return service.test(id,secret);}catch(MonitorService.NotFound e){throw notFound();}
    catch(MonitorService.Conflict e){throw new ResponseStatusException(HttpStatus.CONFLICT,"Session inactive or test rate limited");}
  }
  private static ResponseStatusException notFound(){return new ResponseStatusException(HttpStatus.NOT_FOUND,"Session not found");}
}
