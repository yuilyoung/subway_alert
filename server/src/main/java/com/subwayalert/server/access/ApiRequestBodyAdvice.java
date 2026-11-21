package com.subwayalert.server.access;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Type;
import java.util.Map;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpInputMessage;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.RequestBodyAdviceAdapter;

@RestControllerAdvice
public final class ApiRequestBodyAdvice extends RequestBodyAdviceAdapter {
  private static final int MAX_BODY_BYTES = 64 * 1024;

  @Override public boolean supports(MethodParameter parameter, Type target, Class<? extends HttpMessageConverter<?>> converter) {
    return true;
  }

  @Override public HttpInputMessage beforeBodyRead(HttpInputMessage input, MethodParameter parameter,
      Type target, Class<? extends HttpMessageConverter<?>> converter) throws IOException {
    if (input.getHeaders().getContentLength() > MAX_BODY_BYTES) throw new ResponseStatusException(HttpStatus.CONTENT_TOO_LARGE);
    // A chunked request has no declared length. Check actual bytes before handing the body to Jackson.
    byte[] bytes = input.getBody().readNBytes(MAX_BODY_BYTES + 1);
    if (bytes.length > MAX_BODY_BYTES) throw new ResponseStatusException(HttpStatus.CONTENT_TOO_LARGE);
    return new HttpInputMessage() {
      @Override public HttpHeaders getHeaders() { return input.getHeaders(); }
      @Override public InputStream getBody() { return new ByteArrayInputStream(bytes); }
    };
  }

  @ExceptionHandler(HttpMessageNotReadableException.class)
  public ResponseEntity<Map<String,String>> unreadableRequest() {
    // The default resolver includes the rejected input value in its warning log.
    return ResponseEntity.badRequest().body(Map.of("error","API_INVALID_JSON"));
  }
}
