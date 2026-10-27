package com.subwayalert;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class Json {
    private final ObjectMapper mapper;
    public Json(ObjectMapper mapper) { this.mapper=mapper; }
    public String write(Object value) {
        try { return mapper.writeValueAsString(value); } catch(Exception e) { throw new IllegalStateException("JSON encode failed",e); }
    }
    public List<String> strings(String value) {
        try { return mapper.readValue(value,new TypeReference<List<String>>(){}); } catch(Exception e) { throw new IllegalStateException("Invalid stored route",e); }
    }
    public Map<String,String> data(String value) {
        try { return mapper.readValue(value,new TypeReference<Map<String,String>>(){}); } catch(Exception e) { throw new IllegalStateException("Invalid stored event",e); }
    }
}
