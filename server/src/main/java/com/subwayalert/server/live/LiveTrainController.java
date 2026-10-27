package com.subwayalert.server.live;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/live")
public final class LiveTrainController {
  private final SeoulTrainProvider provider;
  public LiveTrainController(ObjectMapper mapper) { provider=SeoulTrainProvider.configured(mapper); }
  @GetMapping("/trains") public SeoulTrainProvider.Result trains(@RequestParam(defaultValue="2") String line){
    try{return provider.fetch(line);}
    catch(IllegalArgumentException e){throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Unsupported line");}
    catch(SeoulTrainProvider.ProviderException e){throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,"실시간 데이터 연결에 실패했습니다.");}
  }
}
